"""Discrete-event entanglement scheduler for distributed circuits."""

from __future__ import annotations

import heapq
import random
from collections import deque
from dataclasses import dataclass, field
from typing import TypeAlias

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
    _operation_duration,
    _physical_qubit_label,
)

_START_EPR_REQUEST = "START_EPR_REQUEST"
_EPR_ATTEMPT = "EPR_ATTEMPT"
_EPR_READY = "EPR_READY"
_REMOTE_OP_START = "REMOTE_OP_START"
_OP_COMPLETE = "OP_COMPLETE"
_EventType: TypeAlias = str

_EVENT_PRIORITY: dict[_EventType, int] = {
    _OP_COMPLETE: 0,
    _START_EPR_REQUEST: 1,
    _EPR_ATTEMPT: 2,
    _EPR_READY: 3,
    _REMOTE_OP_START: 4,
}


@dataclass(order=True, slots=True, frozen=True)
class _QueueEvent:
    """One event scheduled on the DES priority queue."""

    time: float
    priority: int
    sequence: int
    event_type: _EventType = field(compare=False)
    op_id: int = field(compare=False)
    link_key: tuple[str, str] | None = field(compare=False, default=None)


@dataclass(slots=True)
class _LinkState:
    """Track active and queued entanglement requests for one link."""

    active_request_id: int | None = None
    pending_request_ids: deque[int] = field(default_factory=deque)


@dataclass(slots=True)
class _RemoteLinkRequest:
    """Track one EPR-producing link for a remote operation."""

    link_qubits: tuple[str, str]
    link_key: tuple[str, str]
    process_start_time: float | None = None
    ready_time: float | None = None


@dataclass(slots=True)
class _RemoteRequest:
    """Track one remote operation's entanglement request lifecycle."""

    op: Op
    op_qubits: tuple[str, ...]
    data_qubits: tuple[str, str]
    link_requests: dict[tuple[str, str], _RemoteLinkRequest]
    start_enqueued: bool = False


class DESEntanglementScheduler(BaseScheduler):
    """Schedule remote operations with event-driven EPR generation."""

    def __init__(
        self,
        distributed_circuit: DistributedCircuit,
        *,
        profile: SchedulerHardwareProfile | None = None,
        modality: SchedulerModality = DEFAULT_SCHEDULER_MODALITY,
        entanglement_profile: SchedulerEntanglementProfile = (
            DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
        ),
        multiplex_entangle: bool = True,
        seed: int | None = None,
    ) -> None:
        """Initialize the scheduler with DES link parameters.

        Args:
            distributed_circuit: Distributed circuit DAG to schedule.
            profile: Optional convenience object selecting both modality and
                entanglement profile. When provided, ``modality`` and
                ``entanglement_profile`` must be left at their defaults.
            modality: Hardware timing profile used for local 1Q/2Q gate
                durations. Defaults to ``"trapped_ion.ba"`` (Ba+ trapped ion).
            entanglement_profile: Entanglement-generation profile used for
                entanglement timing. Defaults to ``"ion.time_bin"``.
            multiplex_entangle: Preserved for API compatibility. The DES still
                enforces one active entanglement process per link.
            seed: Optional random seed for deterministic simulations.
        """
        super().__init__(
            distributed_circuit,
            profile=profile,
            modality=modality,
            entanglement_profile=entanglement_profile,
            multiplex_entangle=multiplex_entangle,
        )
        self.t_cycle = self.timing_model.des_t_cycle
        self.p_success = self.timing_model.des_success_probability
        self.seed = seed
        self._rng = random.Random()
        self._op_by_id: dict[int, Op] = {}
        self._successors_by_op: dict[int, tuple[int, ...]] = {}
        self._remaining_predecessors: dict[int, int] = {}
        self._qubit_timers: dict[str, float] = {}
        self._qubit_order: list[str] = []
        self._op_qubits: dict[int, tuple[str, ...]] = {}
        self._event_queue: list[_QueueEvent] = []
        self._link_states: dict[tuple[str, str], _LinkState] = {}
        self._remote_requests: dict[int, _RemoteRequest] = {}
        self._scheduled_records: list[tuple[float, int, ScheduleEvent]] = []
        self._event_sequence = 0
        self._record_sequence = 0

    def run(self) -> None:
        """Build an operation schedule using a discrete-event simulator.

        The scheduler initializes DES state from the distributed circuit DAG,
        seeds the event queue with operations whose predecessors are already
        satisfied, then processes events in timestamp order until the queue is
        empty.

        Raises:
            RuntimeError: If an event refers to inconsistent internal state.
            ValueError: If the scheduler configuration is invalid or a remote
                operation is missing its EPR metadata.
        """
        self._validate_parameters()
        self._reset_run_state()

        # Initialize the queue
        for op_id in sorted(self._op_by_id):
            if self._remaining_predecessors[op_id] == 0:
                self._schedule_ready_operation(self._op_by_id[op_id])

        # Walk the DES one event at a time until nothing is left to process.
        while self._event_queue:
            self._handle_event(heapq.heappop(self._event_queue))

        # Convert the recorded events into the public schedule object.
        self._finalize_schedule()

    def _validate_parameters(self) -> None:
        """Validate stochastic link parameters before simulation.

        Raises:
            ValueError: If ``t_cycle`` is not positive or ``p_success`` falls
                outside the supported ``(0, 1]`` interval.
        """
        if self.t_cycle <= 0.0:
            raise ValueError("t_cycle must be greater than 0.")
        if not 0.0 < self.p_success <= 1.0:
            raise ValueError("p_success must be greater than 0 and at most 1.")

    def _reset_run_state(self) -> None:
        """Initialize per-run simulation state from the distributed DAG.

        This resets all mutable DES state so a scheduler instance can produce
        a fresh schedule each time ``run()`` is invoked.
        """
        # reset random number generator
        self._rng = random.Random(self.seed)
        graph = self.distributed_circuit.dag.graph
        self._op_by_id = {
            op_id: graph.nodes[op_id]["op"] for op_id in graph.nodes
        }
        self._successors_by_op = {
            op_id: tuple(graph.successors(op_id)) for op_id in self._op_by_id
        }
        self._remaining_predecessors = {
            op_id: graph.in_degree(op_id) for op_id in self._op_by_id
        }
        (
            self._qubit_timers,
            self._qubit_order,
            self._op_qubits,
        ) = _initialize_qubit_state(
            tuple(self._op_by_id[op_id] for op_id in sorted(self._op_by_id))
        )
        self._event_queue = []
        self._link_states = {}
        self._remote_requests = {}
        self._scheduled_records = []
        self._event_sequence = 0
        self._record_sequence = 0

    def _enqueue_event(
        self,
        time: float,
        event_type: _EventType,
        op_id: int,
        link_key: tuple[str, str] | None = None,
    ) -> None:
        """Push one event onto the DES priority queue.

        Args:
            time: Simulation timestamp for the event.
            event_type: Kind of event being scheduled.
            op_id: Operation identifier associated with the event.
            link_key: Optional link identifier for link-scoped events.
        """
        heapq.heappush(
            self._event_queue,
            _QueueEvent(
                time=time,
                priority=_EVENT_PRIORITY[event_type],
                sequence=self._event_sequence,
                event_type=event_type,
                op_id=op_id,
                link_key=link_key,
            ),
        )
        self._event_sequence += 1

    def _record_scheduled_event(self, event: ScheduleEvent) -> None:
        """Record one visible schedule event with stable output ordering.

        Args:
            event: Schedule event to expose in the final ``OperationSchedule``.
        """
        self._scheduled_records.append(
            (event.start_time, self._record_sequence, event)
        )
        self._record_sequence += 1

    def _mark_operation_completed(self, op_id: int) -> None:
        """Release successors once an operation has finished.

        Args:
            op_id: Identifier of the operation that just completed.
        """
        for successor_id in self._successors_by_op[op_id]:
            self._remaining_predecessors[successor_id] -= 1
            if self._remaining_predecessors[successor_id] == 0:
                self._schedule_ready_operation(self._op_by_id[successor_id])

    def _schedule_ready_operation(self, op: Op) -> None:
        """Schedule a ready local op or issue a remote EPR request.

        Args:
            op: Operation whose predecessor constraints are already satisfied.
        """
        if op.is_remote:
            self._schedule_remote_request(op)
        else:
            self._schedule_local_operation(op)

    def _schedule_local_operation(self, op: Op) -> None:
        """Reserve qubits for a local operation and enqueue its completion.

        Args:
            op: Local operation to schedule.
        """
        op_labels = self._op_qubits[op.op_id]
        start_time = max(
            (self._qubit_timers[qubit] for qubit in op_labels),
            default=0.0,
        )
        scheduled_op = ScheduledOperation(
            op_id=op.op_id,
            statement_id=op.statement_id,
            name=op.name,
            qubits=op_labels,
            start_time=start_time,
            duration=_operation_duration(op, self.timing_model),
            is_remote=False,
        )
        self._record_scheduled_event(scheduled_op)
        for qubit in op_labels:
            self._qubit_timers[qubit] = scheduled_op.end_time
        self._enqueue_event(scheduled_op.end_time, _OP_COMPLETE, op.op_id)

    def _schedule_remote_request(self, op: Op) -> None:
        """Create one remote request and queue its first scheduling event.

        Remote operations directly request the EPR pairs they need.

        Args:
            op: Remote operation that requires one or more EPR pairs.

        Raises:
            ValueError: If the remote operation is missing EPR metadata or
                reuses the same communication link within one request.
        """
        ebit_pairs = op.ebit_pairs
        if ebit_pairs is None:
            raise ValueError(
                "Remote operation is missing required EPR pair metadata."
            )

        op_labels = self._op_qubits[op.op_id]
        link_requests: dict[tuple[str, str], _RemoteLinkRequest] = {}
        for ebit_pair in ebit_pairs:
            link_qubits = (
                _physical_qubit_label(ebit_pair[0]),
                _physical_qubit_label(ebit_pair[1]),
            )
            link_key = _canonical_link_key(link_qubits)
            if link_key in link_requests:
                raise ValueError(
                    "Remote operation reuses the same EPR link within one "
                    "request."
                )
            link_requests[link_key] = _RemoteLinkRequest(
                link_qubits=link_qubits,
                link_key=link_key,
            )

        self._remote_requests[op.op_id] = _RemoteRequest(
            op=op,
            op_qubits=op_labels,
            data_qubits=(op_labels[0], op_labels[1]),
            link_requests=link_requests,
        )

        # v1 does not buffer EPR pairs, so we wait until the op's qubits are
        # free before we even ask the link to start trying.
        start_time = max(
            (self._qubit_timers[qubit] for qubit in op_labels),
            default=0.0,
        )
        for link_key in link_requests:
            self._enqueue_event(
                start_time,
                _START_EPR_REQUEST,
                op.op_id,
                link_key=link_key,
            )

    def _activate_remote_request(
        self,
        op_id: int,
        link_key: tuple[str, str],
        time: float,
    ) -> None:
        """Start entanglement attempts for one remote request.

        Args:
            op_id: Identifier of the remote operation request to activate.
            link_key: Communication link assigned to this EPR attempt stream.
            time: Simulation time at which the link begins attempting EPR
                generation.
        """
        request = self._remote_requests[op_id]
        link_request = request.link_requests[link_key]
        link_request.process_start_time = time
        link_state = self._link_states.setdefault(link_key, _LinkState())
        link_state.active_request_id = op_id
        cycle_time, _ = self._resolve_link_parameters(link_key)
        self._enqueue_event(
            time + cycle_time,
            _EPR_ATTEMPT,
            op_id,
            link_key=link_key,
        )

    def _resolve_link_parameters(
        self,
        link_key: tuple[str, str],
    ) -> tuple[float, float]:
        """Return link parameters while keeping lookup centralized.

        Args:
            link_key: Canonical identifier for the communication link.

        Returns:
            The entanglement attempt cycle time and per-attempt success
            probability for the requested link.
        """
        del link_key
        return self.t_cycle, self.p_success

    def _handle_event(self, event: _QueueEvent) -> None:
        """Dispatch one DES event.

        Args:
            event: Event popped from the DES priority queue.

        Raises:
            RuntimeError: If the event type is not recognized.
        """
        if event.event_type == _OP_COMPLETE:
            self._mark_operation_completed(event.op_id)
            return
        if event.event_type == _START_EPR_REQUEST:
            self._handle_start_epr_request(event)
            return
        if event.event_type == _EPR_ATTEMPT:
            self._handle_epr_attempt(event)
            return
        if event.event_type == _EPR_READY:
            self._handle_epr_ready(event)
            return
        if event.event_type == _REMOTE_OP_START:
            self._handle_remote_op_start(event)
            return
        raise RuntimeError(f"Unsupported DES event type: {event.event_type}")

    def _handle_start_epr_request(self, event: _QueueEvent) -> None:
        """Queue or activate a remote request when its link is examined.

        Args:
            event: ``START_EPR_REQUEST`` event for one remote operation.

        Raises:
            RuntimeError: If the event does not carry a link identifier.
        """
        if event.link_key is None:
            raise RuntimeError("START_EPR_REQUEST requires a link key.")
        link_state = self._link_states.setdefault(event.link_key, _LinkState())

        # Keep one in-flight entanglement process per link.
        if (
            link_state.active_request_id is not None
            and link_state.active_request_id != event.op_id
        ):
            if event.op_id not in link_state.pending_request_ids:
                link_state.pending_request_ids.append(event.op_id)
            return
        self._activate_remote_request(event.op_id, event.link_key, event.time)

    def _handle_epr_attempt(self, event: _QueueEvent) -> None:
        """Sample one entanglement attempt and queue the next step.

        Args:
            event: ``EPR_ATTEMPT`` event for the active link request.

        Raises:
            RuntimeError: If the event does not carry a link identifier.
        """
        if event.link_key is None:
            raise RuntimeError("EPR_ATTEMPT requires a link key.")
        link_state = self._link_states.setdefault(event.link_key, _LinkState())
        if link_state.active_request_id != event.op_id:
            return

        _, success_probability = self._resolve_link_parameters(event.link_key)
        if self._rng.random() < success_probability:
            self._enqueue_event(
                event.time,
                _EPR_READY,
                event.op_id,
                link_key=event.link_key,
            )
            return

        cycle_time, _ = self._resolve_link_parameters(event.link_key)
        self._enqueue_event(
            time=event.time + cycle_time,
            event_type=_EPR_ATTEMPT,
            op_id=event.op_id,
            link_key=event.link_key,
        )

    def _handle_epr_ready(self, event: _QueueEvent) -> None:
        """Mark the request ready and hand control to the remote op.

        Args:
            event: ``EPR_READY`` event for the active link request.

        Raises:
            RuntimeError: If the event does not carry a link identifier.
        """
        request = self._remote_requests[event.op_id]
        if event.link_key is None:
            raise RuntimeError("EPR_READY requires a link key.")
        link_state = self._link_states.setdefault(event.link_key, _LinkState())
        if link_state.active_request_id != event.op_id:
            return

        request.link_requests[event.link_key].ready_time = event.time
        if not request.start_enqueued and all(
            link_request.ready_time is not None
            for link_request in request.link_requests.values()
        ):
            request.start_enqueued = True
            self._enqueue_event(event.time, _REMOTE_OP_START, event.op_id)

    def _handle_remote_op_start(self, event: _QueueEvent) -> None:
        """Emit visible EPR and remote-op events once the link succeeds.

        Args:
            event: ``REMOTE_OP_START`` event for a ready remote request.

        Raises:
            RuntimeError: If the request is missing the timestamps required to
                emit the visible EPR and remote-operation schedule events.
        """
        request = self._remote_requests[event.op_id]
        if not all(
            self._link_states.setdefault(
                link_key, _LinkState()
            ).active_request_id
            == event.op_id
            for link_key in request.link_requests
        ):
            return

        # Collapse all retries into one visible EPR block in the schedule.
        for link_request in request.link_requests.values():
            if link_request.process_start_time is None:
                raise RuntimeError(
                    "Remote request missing entanglement start time."
                )
            if link_request.ready_time is None:
                raise RuntimeError(
                    "Remote request missing entanglement ready time."
                )
            self._record_scheduled_event(
                EntanglementGeneration(
                    qubits=link_request.link_qubits,
                    start_time=link_request.process_start_time,
                    duration=(
                        link_request.ready_time
                        - link_request.process_start_time
                    ),
                )
            )

        scheduled_op = ScheduledOperation(
            op_id=request.op.op_id,
            statement_id=request.op.statement_id,
            name=request.op.name,
            qubits=request.op_qubits,
            start_time=event.time,
            duration=_operation_duration(request.op, self.timing_model),
            is_remote=True,
        )
        self._record_scheduled_event(scheduled_op)
        for qubit in request.op_qubits:
            self._qubit_timers[qubit] = scheduled_op.end_time
        self._enqueue_event(scheduled_op.end_time, _OP_COMPLETE, event.op_id)

        for link_request in request.link_requests.values():
            link_state = self._link_states.setdefault(
                link_request.link_key,
                _LinkState(),
            )
            link_state.active_request_id = None
            if link_state.pending_request_ids:
                next_request_id = link_state.pending_request_ids.popleft()
                self._activate_remote_request(
                    next_request_id,
                    link_request.link_key,
                    event.time,
                )

    def _finalize_schedule(self) -> None:
        """Build the public schedule object from recorded events.

        Recorded events are sorted by start time and stable insertion order
        before qubit timelines and the overall makespan are derived.
        """
        ordered_operations = tuple(
            event
            for _, _, event in sorted(
                self._scheduled_records,
                key=lambda item: (item[0], item[1]),
            )
        )
        operations_list = list(ordered_operations)
        self.schedule = OperationSchedule(
            operations=ordered_operations,
            timelines=_build_qubit_timelines(
                operations_list,
                tuple(self._qubit_order),
            ),
            makespan=max(
                (
                    scheduled_event.end_time
                    for scheduled_event in ordered_operations
                ),
                default=0.0,
            ),
        )


def des_epr_schedule(
    distributed_circuit: DistributedCircuit,
    *,
    profile: SchedulerHardwareProfile | None = None,
    modality: SchedulerModality = DEFAULT_SCHEDULER_MODALITY,
    entanglement_profile: SchedulerEntanglementProfile = (
        DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
    ),
    multiplex_entangle: bool = True,
    seed: int | None = None,
) -> OperationSchedule:
    """Build a DES-based schedule for a distributed circuit DAG.

    Args:
        distributed_circuit: Distributed circuit to schedule.
        profile: Optional convenience object selecting both modality and
            entanglement profile. When provided, ``modality`` and
            ``entanglement_profile`` must be left at their defaults.
        modality: Hardware timing profile used for local 1Q/2Q gate
            durations. Defaults to ``"trapped_ion.ba"`` (Ba+ trapped ion).
        entanglement_profile: Entanglement-generation profile used for
            entanglement timing. Defaults to ``"ion.time_bin"``.
        multiplex_entangle: Preserved for API compatibility. The DES still
            enforces one active entanglement process per link.
        seed: Optional random seed for deterministic simulations.

    Returns:
        An operation-level schedule with stochastic entanglement timing.
    """
    scheduler = DESEntanglementScheduler(
        distributed_circuit,
        profile=profile,
        modality=modality,
        entanglement_profile=entanglement_profile,
        multiplex_entangle=multiplex_entangle,
        seed=seed,
    )
    scheduler.run()
    if scheduler.schedule is None:
        raise RuntimeError("DES scheduler did not produce a schedule.")
    return scheduler.schedule


def _canonical_link_key(link_qubits: tuple[str, str]) -> tuple[str, str]:
    """Return a stable key for link-state lookups.

    Args:
        link_qubits: Physical communication-qubit labels for one link.

    Returns:
        A deterministically ordered link key suitable for dictionary lookups.
    """
    ordered_qubits = sorted(link_qubits)
    return ordered_qubits[0], ordered_qubits[1]


def _initialize_qubit_state(
    ops: tuple[Op, ...],
) -> tuple[dict[str, float], list[str], dict[int, tuple[str, ...]]]:
    """Return initial per-qubit timers and stable qubit ordering.

    Args:
        ops: Distributed operations in source order.

    Returns:
        Per-qubit availability times, stable qubit order, and physical labels
        for each operation id.
    """
    qubit_timers: dict[str, float] = {}
    qubit_order: list[str] = []
    op_qubits: dict[int, tuple[str, ...]] = {}

    for op in ops:
        labels = tuple(_physical_qubit_label(qubit) for qubit in op.qubits)
        op_qubits[op.op_id] = labels
        for label in labels:
            if label not in qubit_timers:
                qubit_timers[label] = 0.0
                qubit_order.append(label)

    return qubit_timers, qubit_order, op_qubits
