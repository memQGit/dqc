"""First-In First-Out (FIFO) distributed scheduler implementation."""

from __future__ import annotations

from memq_dqc.circuit import DistributedCircuit
from memq_dqc.scheduler.schedule import (
    _ENTANGLEMENT_TIME,
    BaseScheduler,
    EntanglementGeneration,
    OperationSchedule,
    ScheduledOperation,
    ScheduleEvent,
    _build_qubit_timelines,
    _operation_duration,
    _physical_qubit_label,
)


class FIFOScheduler(BaseScheduler):
    """Schedule operations by walking DAG layers in FIFO order."""

    def run(self) -> None:
        """Build a FIFO schedule for the configured distributed circuit."""
        qubit_timers: dict[str, float] = {}
        qubit_order: list[str] = []
        scheduled_operations: list[ScheduleEvent] = []
        # need to add: check of available e-bit
        for layer in self.distributed_circuit.dag.layers:
            for op in layer:
                qubits = tuple(
                    _physical_qubit_label(qubit) for qubit in op.qubits
                )
                for qubit in qubits:
                    if qubit not in qubit_timers:
                        qubit_timers[qubit] = 0.0
                        qubit_order.append(qubit)

                entanglement_events: list[EntanglementGeneration] = []
                if op.is_remote:
                    ebits = op.ebit_pairs
                    if ebits is not None:
                        # Entanglement generation is just-in-time (not FIFO)
                        entanglement_events, start_time = (
                            _schedule_entanglement_generation(
                                data_qubits=qubits[:2],
                                ebit_qubits=tuple(
                                    (
                                        _physical_qubit_label(ebit[0]),
                                        _physical_qubit_label(ebit[1]),
                                    )
                                    for ebit in ebits
                                ),
                                qubit_timers=qubit_timers,
                                multiplex_entangle=self.multiplex_entangle,
                            )
                        )
                    else:
                        start_time = max(
                            (qubit_timers[qubit] for qubit in qubits),
                            default=0.0,
                        )
                else:
                    start_time = max(
                        (qubit_timers[qubit] for qubit in qubits),
                        default=0.0,
                    )

                scheduled_operations.extend(entanglement_events)

                scheduled_op = ScheduledOperation(
                    op_id=op.op_id,
                    statement_id=op.statement_id,
                    name=op.name,
                    qubits=qubits,
                    start_time=start_time,
                    duration=_operation_duration(op),
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
    multiplex_entangle: bool = True,
) -> OperationSchedule:
    """Build a FIFO schedule for a distributed circuit DAG.

    Args:
        distributed_circuit: Distributed circuit to schedule.
        multiplex_entangle: Reserved for future entanglement multiplexing
            behavior.

    Returns:
        An operation-level schedule with per-qubit timelines.
    """
    scheduler = FIFOScheduler(
        distributed_circuit,
        multiplex_entangle=multiplex_entangle,
    )
    scheduler.run()
    if scheduler.schedule is None:
        raise RuntimeError("FIFO scheduler did not produce a schedule.")
    return scheduler.schedule


def _schedule_entanglement_generation(
    *,
    data_qubits: tuple[str, str],
    ebit_qubits: tuple[tuple[str, str], ...],
    qubit_timers: dict[str, float],
    multiplex_entangle: bool,
) -> tuple[list[EntanglementGeneration], float]:
    """Return just-in-time entanglement events and the remote-op start time."""
    data_ready = max(
        (qubit_timers[qubit] for qubit in data_qubits), default=0.0
    )
    if not ebit_qubits:
        return [], data_ready

    if multiplex_entangle or len(ebit_qubits) == 1:
        start_time = max(
            data_ready,
            max(
                max(qubit_timers[pair[0]], qubit_timers[pair[1]])
                + _ENTANGLEMENT_TIME
                for pair in ebit_qubits
            ),
        )
        return [
            EntanglementGeneration(
                qubits=pair,
                start_time=start_time - _ENTANGLEMENT_TIME,
            )
            for pair in ebit_qubits
        ], start_time

    start_time = data_ready
    total_pairs = len(ebit_qubits)
    for index, pair in enumerate(ebit_qubits):
        slot_count = total_pairs - index
        pair_ready = max(qubit_timers[pair[0]], qubit_timers[pair[1]])
        start_time = max(
            start_time,
            pair_ready + (slot_count * _ENTANGLEMENT_TIME),
        )

    return [
        EntanglementGeneration(
            qubits=pair,
            start_time=start_time
            - ((total_pairs - index) * _ENTANGLEMENT_TIME),
        )
        for index, pair in enumerate(ebit_qubits)
    ], start_time
