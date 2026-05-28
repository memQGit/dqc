"""First-In First-Out (FIFO) distributed scheduler implementation."""

from __future__ import annotations

from memq_dqc.circuit import DistributedCircuit, Op
from memq_dqc.scheduler.schedule import (
    DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE,
    DEFAULT_SCHEDULER_MODALITY,
    BaseScheduler,
    EntanglementGeneration,
    OperationSchedule,
    ScheduledOperation,
    ScheduleEvent,
    SchedulerEntanglementProfile,
    SchedulerHardwareProfile,
    SchedulerModality,
    _build_qubit_timelines,
    _catent_ebit_labels,
    _ebit_assignment_labels,
    _is_catent_operation,
    _operation_duration,
    _physical_qubit_label,
    _remote_ebit_assignment_candidates,
    _remote_operation_qubit_labels,
    _remote_ops_with_catent_predecessor,
)


class FIFOScheduler(BaseScheduler):
    """Schedule operations by walking DAG layers in FIFO order."""

    def run(self) -> None:
        """Build a FIFO schedule for the configured distributed circuit."""
        qubit_timers: dict[str, float] = {}
        qubit_order: list[str] = []
        scheduled_operations: list[ScheduleEvent] = []
        remote_ops_with_catent = _remote_ops_with_catent_predecessor(
            self.distributed_circuit
        )
        # need to add: check of available e-bit
        for layer in self.distributed_circuit.dag.layers:
            for op in layer:
                # we would like to forward look to see if local operations
                # can be done simultaneously with remote operations
                entanglement_events: list[EntanglementGeneration] = []
                if _is_catent_operation(op):
                    if len(op.qubits) > 2:
                        qubits = tuple(
                            _physical_qubit_label(qubit) for qubit in op.qubits
                        )
                        (
                            entanglement_events,
                            start_time,
                        ) = _schedule_entanglement_generation(
                            data_qubits=(qubits[0], qubits[1]),
                            ebit_qubits=_catent_ebit_labels(op),
                            qubit_timers=qubit_timers,
                            entanglement_time=(
                                self.timing_model.entanglement_time
                            ),
                            multiplex_entangle=self.multiplex_entangle,
                        )
                    else:
                        (
                            qubits,
                            entanglement_events,
                            start_time,
                        ) = _select_remote_ebit_assignment(
                            distributed_circuit=self.distributed_circuit,
                            op=op,
                            qubit_timers=qubit_timers,
                            entanglement_time=(
                                self.timing_model.entanglement_time
                            ),
                            multiplex_entangle=self.multiplex_entangle,
                        )
                elif op.is_remote and op.op_id not in remote_ops_with_catent:
                    (
                        qubits,
                        entanglement_events,
                        start_time,
                    ) = _select_remote_ebit_assignment(
                        distributed_circuit=self.distributed_circuit,
                        op=op,
                        qubit_timers=qubit_timers,
                        entanglement_time=(
                            self.timing_model.entanglement_time
                        ),
                        multiplex_entangle=self.multiplex_entangle,
                    )
                else:
                    qubits = tuple(
                        _physical_qubit_label(qubit) for qubit in op.qubits
                    )
                    start_time = max(
                        (qubit_timers.get(qubit, 0.0) for qubit in qubits),
                        default=0.0,
                    )

                for qubit in qubits:
                    if qubit not in qubit_timers:
                        qubit_timers[qubit] = 0.0
                        qubit_order.append(qubit)

                scheduled_operations.extend(entanglement_events)

                scheduled_op = ScheduledOperation(
                    op_id=op.op_id,
                    statement_id=op.statement_id,
                    name=op.name,
                    qubits=qubits,
                    start_time=start_time,
                    duration=_operation_duration(op, self.timing_model),
                    is_remote=op.is_remote,
                )
                scheduled_operations.append(scheduled_op)

                for qubit in qubits:
                    qubit_timers[qubit] = scheduled_op.end_time

        self.schedule = OperationSchedule(
            operations=tuple(scheduled_operations),
            timelines=_build_qubit_timelines(
                scheduled_operations,
                tuple(qubit_order),
            ),
            makespan=max(
                (
                    scheduled_event.end_time
                    for scheduled_event in scheduled_operations
                ),
                default=0.0,
            ),
        )


def fifo_schedule(
    distributed_circuit: DistributedCircuit,
    *,
    profile: SchedulerHardwareProfile | None = None,
    modality: SchedulerModality = DEFAULT_SCHEDULER_MODALITY,
    entanglement_profile: SchedulerEntanglementProfile = (
        DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
    ),
    multiplex_entangle: bool = True,
) -> OperationSchedule:
    """Build a FIFO schedule for a distributed circuit DAG.

    Args:
        distributed_circuit: Distributed circuit to schedule.
        profile: Optional convenience object selecting both modality and
            entanglement profile. When provided, ``modality`` and
            ``entanglement_profile`` must be left at their defaults.
        modality: Hardware timing profile used for local 1Q/2Q gate
            durations. Defaults to ``"trapped_ion.ba"`` (Ba+ trapped ion).
        entanglement_profile: Entanglement-generation profile used for
            entanglement timing. Defaults to ``"ion.time_bin"``.
        multiplex_entangle: Reserved for future entanglement multiplexing
            behavior.(# TODO)

    Returns:
        An operation-level schedule with per-qubit timelines.
    """
    scheduler = FIFOScheduler(
        distributed_circuit=distributed_circuit,
        profile=profile,
        modality=modality,
        entanglement_profile=entanglement_profile,
        multiplex_entangle=multiplex_entangle,
    )
    scheduler.run()
    if scheduler.schedule is None:
        raise RuntimeError("FIFO scheduler did not produce a schedule.")
    return scheduler.schedule


def _select_remote_ebit_assignment(
    *,
    distributed_circuit: DistributedCircuit,
    op: Op,
    qubit_timers: dict[str, float],
    entanglement_time: float,
    multiplex_entangle: bool,
) -> tuple[tuple[str, ...], list[EntanglementGeneration], float]:
    """Choose the FIFO e-bit assignment with earliest remote start."""
    best_score: tuple[float, int] | None = None
    best_result: (
        tuple[tuple[str, ...], list[EntanglementGeneration], float] | None
    ) = None

    for index, assignment in enumerate(
        _remote_ebit_assignment_candidates(distributed_circuit, op)
    ):
        qubits = _remote_operation_qubit_labels(op, assignment)
        entanglement_events, start_time = _schedule_entanglement_generation(
            data_qubits=(qubits[0], qubits[1]),
            ebit_qubits=_ebit_assignment_labels(assignment),
            qubit_timers=qubit_timers,
            entanglement_time=entanglement_time,
            multiplex_entangle=multiplex_entangle,
        )
        score = (start_time, index)
        if best_score is None or score < best_score:
            best_score = score
            best_result = (qubits, entanglement_events, start_time)

    if best_result is None:
        raise ValueError(
            f"Remote operation {op.op_id} has no viable e-bit assignments."
        )
    return best_result


def _schedule_entanglement_generation(
    *,
    data_qubits: tuple[str, str],
    ebit_qubits: tuple[tuple[str, str], ...],
    qubit_timers: dict[str, float],
    entanglement_time: float,
    multiplex_entangle: bool,
) -> tuple[list[EntanglementGeneration], float]:
    """Return just-in-time entanglement events and the remote-op start time."""
    data_ready = max(
        (qubit_timers.get(qubit, 0.0) for qubit in data_qubits), default=0.0
    )
    if not ebit_qubits:
        return [], data_ready

    if multiplex_entangle or len(ebit_qubits) == 1:
        start_time = max(
            data_ready,
            max(
                max(
                    qubit_timers.get(pair[0], 0.0),
                    qubit_timers.get(pair[1], 0.0),
                )
                + entanglement_time
                for pair in ebit_qubits
            ),
        )
        return [
            EntanglementGeneration(
                qubits=pair,
                start_time=start_time - entanglement_time,
                duration=entanglement_time,
            )
            for pair in ebit_qubits
        ], start_time

    else:
        pass
        # TODO
        # Non-multiplexed entanglement: generate same-qpu e-bits sequentially
        # we will implement this with DES
    start_time = data_ready
    total_pairs = len(ebit_qubits)
    for index, pair in enumerate(ebit_qubits):
        slot_count = total_pairs - index
        pair_ready = max(
            qubit_timers.get(pair[0], 0.0),
            qubit_timers.get(pair[1], 0.0),
        )
        start_time = max(
            start_time,
            pair_ready + (slot_count * entanglement_time),
        )

    return [
        EntanglementGeneration(
            qubits=pair,
            start_time=start_time
            - ((total_pairs - index) * entanglement_time),
            duration=entanglement_time,
        )
        for index, pair in enumerate(ebit_qubits)
    ], start_time
