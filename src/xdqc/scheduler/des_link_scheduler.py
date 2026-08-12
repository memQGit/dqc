# Copyright 2026 memQ Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Shared discrete-event scheduler for link-mediated remote operations."""

from __future__ import annotations

import heapq
import logging
import math
import random
from dataclasses import dataclass, field
from typing import TypeAlias

from xdqc.circuit import DistributedCircuit, Op
from xdqc.network import PhysicalQubit
from xdqc.scheduler.schedule import (
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
    SchedulerTimingModel,
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

logger = logging.getLogger(__name__)

_START_EPR_REQUEST = "START_EPR_REQUEST"
_EPR_READY = "EPR_READY"
_EPR_EXPIRE = "EPR_EXPIRE"
_REMOTE_OP_START = "REMOTE_OP_START"

#: Expired pairs tolerated for one request before giving up on it.
#:
#: A multi-pair operation needs all its pairs alive at the same instant. Each
#: link generates independently, so whether they coincide is stochastic: a
#: profile whose EPR lifetime is below the *mean* generation time can still
#: assemble its pairs whenever its links happen to succeed early. Only the
#: simulation can decide that, so this is a termination safeguard, not a
#: feasibility test -- it exists so a configuration that in practice never
#: coincides stops instead of regenerating forever.
#:
#: Sized from measurement. With links each alive a fraction f of the time,
#: observed worst-case expiries before coinciding were 4 at f~33%, 50 at f~5%,
#: and 413 at f~0.5% -- roughly 2/f. This bound therefore leaves ample headroom
#: down to f~0.02%.
#:
#: Note the bound counts rounds, not work: each round costs about one mean
#: generation time, so a profile combining a very slow rate with a short
#: lifetime simulates for a long time before giving up. Such a profile needs
#: mean_generation^2 / lifetime events to succeed at all, so it is not
#: practically simulable either way.
_MAX_EXPIRED_PAIRS_PER_REQUEST = 10_000
_OP_COMPLETE = "OP_COMPLETE"
_EventType: TypeAlias = str

_EVENT_PRIORITY: dict[_EventType, int] = {
    _OP_COMPLETE: 0,
    _START_EPR_REQUEST: 1,
    _EPR_READY: 3,
    _REMOTE_OP_START: 4,
    _EPR_EXPIRE: 5,
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


@dataclass(frozen=True, slots=True)
class _PendingLinkRequest:
    """Queued remote request waiting for one contended communication link."""

    op_id: int
    enqueue_sequence: int


@dataclass(slots=True)
class _LinkState:
    """Track the active and queued requests on one communication link."""

    active_request_id: int | None = None
    pending_requests: list[_PendingLinkRequest] = field(default_factory=list)


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
    expired_pair_count: int = 0


@dataclass(frozen=True, slots=True)
class _CatentGroup:
    """One cat-entanglement block scheduled as a single remote operation.

    A block spans a ``catent`` op, the gates emitted before its deferred
    ``catdisent``, and the ``catdisent`` itself. The communication link the
    ``catent`` acquires is held until the ``catdisent`` completes, and the
    block's execution duration (used for arbitration) sums the catent /
    catdisent overhead and the gates acting on the cat-entangled qubits.

    Attributes:
        catent_op_id: Op id of the block's ``catent`` (the link requester).
        member_op_ids: Inner op ids acting on the cat-entangled qubits whose
            durations contribute to the block's execution time.
        catdisent_op_id: Op id of the block's ``catdisent`` (releases links).
    """

    catent_op_id: int
    member_op_ids: tuple[int, ...]
    catdisent_op_id: int


class BaseDESLinkScheduler(BaseScheduler):
    """Discrete-event scheduler with pluggable per-link arbitration policy."""

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
        """Initialize one DES scheduler instance.

        Args:
            distributed_circuit: Distributed circuit DAG to schedule.
            profile: Optional convenience object selecting both modality and
                entanglement profile. When provided, ``modality`` and
                ``entanglement_profile`` must be left at their defaults.
            modality: Hardware timing profile used for local 1Q/2Q gate
                durations. Defaults to ``"trapped_ion.ba"``.
            entanglement_profile: Entanglement-generation profile used for
                entanglement timing. Defaults to ``"ion.time_bin"``.
            multiplex_entangle: Whether entanglement generation for multi-pair
                remote requests may overlap. The current DES link model still
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
        self._remaining_path_costs: dict[int, float] = {}
        self._catent_groups: dict[int, _CatentGroup] = {}
        self._group_by_op_id: dict[int, int] = {}
        self._group_durations: dict[int, float] = {}
        self._group_remaining_path_costs: dict[int, float] = {}
        self._qubit_timers: dict[str, float] = {}
        self._qubit_order: list[str] = []
        self._op_qubits: dict[int, tuple[str, ...]] = {}
        self._event_queue: list[_QueueEvent] = []
        self._link_states: dict[tuple[str, str], _LinkState] = {}
        self._reserved_link_counts: dict[tuple[str, str], int] = {}
        self._remote_requests: dict[int, _RemoteRequest] = {}
        self._remote_ops_with_catent: set[int] = set()
        self._scheduled_records: list[tuple[float, int, ScheduleEvent]] = []
        self._event_sequence = 0
        self._record_sequence = 0
        self._pending_request_sequence = 0

    def run(self) -> None:
        """Build an operation schedule using a discrete-event simulation."""
        self._validate_parameters()
        self._reset_run_state()
        self._log_debug_snapshot("initialized")

        for op_id in sorted(self._op_by_id):
            if self._remaining_predecessors[op_id] == 0:
                self._schedule_ready_operation(self._op_by_id[op_id])
        self._log_debug_snapshot("seeded initial ready operations")

        while self._event_queue:
            event = heapq.heappop(self._event_queue)
            self._log_debug_snapshot(
                "dispatching event",
                current_event=event,
            )
            self._handle_event(event)
            self._log_debug_snapshot(
                "completed event",
                current_event=event,
            )

        self._finalize_schedule()

    def _validate_parameters(self) -> None:
        """Validate stochastic link parameters before simulation."""
        if self.t_cycle <= 0.0:
            raise ValueError("t_cycle must be greater than 0.")
        if not 0.0 < self.p_success <= 1.0:
            raise ValueError("p_success must be greater than 0 and at most 1.")
        if self.timing_model.epr_lifetime <= 0.0:
            raise ValueError("epr_lifetime must be greater than 0.")

    def _reset_run_state(self) -> None:
        """Initialize per-run simulation state from the distributed DAG."""
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
        self._remaining_path_costs = _build_remaining_path_costs(
            op_by_id=self._op_by_id,
            successors_by_op=self._successors_by_op,
            timing_model=self.timing_model,
        )
        self._catent_groups, self._group_by_op_id = _build_catent_groups(
            self._op_by_id
        )
        self._group_durations = {
            catent_op_id: self._group_execution_duration(group)
            for catent_op_id, group in self._catent_groups.items()
        }
        self._group_remaining_path_costs = {
            catent_op_id: (
                self._group_durations[catent_op_id]
                + (
                    self._remaining_path_costs[group.catdisent_op_id]
                    - self.timing_model.catdisent_time
                )
            )
            for catent_op_id, group in self._catent_groups.items()
        }
        # Every remote gate inside a catent block reuses the block's single
        # shared entanglement, so EPR generation only happens for the catent
        # itself. The predecessor-based set catches only the first member
        # (whose direct DAG predecessor is the catent); the group members add
        # the rest, which otherwise would each generate their own EPR pair.
        self._remote_ops_with_catent = _remote_ops_with_catent_predecessor(
            self.distributed_circuit
        )
        self._remote_ops_with_catent.update(
            member_op_id
            for group in self._catent_groups.values()
            for member_op_id in group.member_op_ids
            if self._op_by_id[member_op_id].is_remote
        )
        (
            self._qubit_timers,
            self._qubit_order,
            self._op_qubits,
        ) = _initialize_qubit_state(
            tuple(self._op_by_id[op_id] for op_id in sorted(self._op_by_id))
        )
        self._event_queue = []
        self._link_states = {}
        self._reserved_link_counts = {}
        self._remote_requests = {}
        self._scheduled_records = []
        self._event_sequence = 0
        self._record_sequence = 0
        self._pending_request_sequence = 0

    def _enqueue_event(
        self,
        time: float,
        event_type: _EventType,
        op_id: int,
        link_key: tuple[str, str] | None = None,
    ) -> None:
        """Push one event onto the DES priority queue."""
        queued_event = _QueueEvent(
            time=time,
            priority=_EVENT_PRIORITY[event_type],
            sequence=self._event_sequence,
            event_type=event_type,
            op_id=op_id,
            link_key=link_key,
        )
        heapq.heappush(self._event_queue, queued_event)
        self._event_sequence += 1
        logger.debug(
            "Enqueued DES event: %s",
            self._format_queue_event(queued_event),
        )

    def _record_scheduled_event(self, event: ScheduleEvent) -> None:
        """Record one visible schedule event with stable output ordering."""
        self._scheduled_records.append(
            (event.start_time, self._record_sequence, event)
        )
        self._record_sequence += 1

    def _mark_operation_completed(self, op_id: int) -> None:
        """Release successors once one operation has finished."""
        for successor_id in self._successors_by_op[op_id]:
            self._remaining_predecessors[successor_id] -= 1
            logger.debug(
                "Resolved predecessor for op=%d -> successor=%d; "
                "remaining_predecessors=%d.",
                op_id,
                successor_id,
                self._remaining_predecessors[successor_id],
            )
            if self._remaining_predecessors[successor_id] == 0:
                self._schedule_ready_operation(self._op_by_id[successor_id])

    def _schedule_ready_operation(self, op: Op) -> None:
        """Schedule one ready local op or issue a remote request."""
        if _is_catent_operation(op):
            if len(op.qubits) > 2:
                self._schedule_entangled_operation_request(
                    op,
                    _catent_ebit_labels(op),
                )
            else:
                self._schedule_remote_request(op)
        elif op.is_remote and op.op_id not in self._remote_ops_with_catent:
            self._schedule_remote_request(op)
        else:
            self._schedule_local_operation(op)

    def _schedule_local_operation(self, op: Op) -> None:
        """Reserve qubits for one local operation and enqueue completion."""
        op_labels = self._op_qubits[op.op_id]
        start_time = max(
            (self._qubit_timers[qubit] for qubit in op_labels),
            default=0.0,
        )
        logger.debug(
            "Scheduling operation op=%d name=%s qubits=%s at t=%.3f.",
            op.op_id,
            op.name,
            op_labels,
            start_time,
        )
        scheduled_op = ScheduledOperation(
            op_id=op.op_id,
            statement_id=op.statement_id,
            name=op.name,
            qubits=op_labels,
            start_time=start_time,
            duration=_operation_duration(op, self.timing_model),
            is_remote=op.is_remote,
        )
        self._record_scheduled_event(scheduled_op)
        for qubit in op_labels:
            self._qubit_timers[qubit] = scheduled_op.end_time
        self._enqueue_event(scheduled_op.end_time, _OP_COMPLETE, op.op_id)

    def _schedule_remote_request(self, op: Op) -> None:
        """Create one remote request and queue its initial link events."""
        ebit_pairs = self._select_remote_ebit_assignment(op)
        op_labels = _remote_operation_qubit_labels(op, ebit_pairs)
        self._schedule_entangled_operation_request(
            op,
            _ebit_assignment_labels(ebit_pairs),
            op_labels=op_labels,
        )

    def _schedule_entangled_operation_request(
        self,
        op: Op,
        ebit_labels: tuple[tuple[str, str], ...],
        *,
        op_labels: tuple[str, ...] | None = None,
    ) -> None:
        """Create one EPR-backed operation request and queue link events."""
        if op_labels is None:
            op_labels = self._op_qubits[op.op_id]
        for qubit in op_labels:
            if qubit not in self._qubit_timers:
                self._qubit_timers[qubit] = 0.0
                self._qubit_order.append(qubit)

        link_requests: dict[tuple[str, str], _RemoteLinkRequest] = {}
        for link_qubits in ebit_labels:
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
            self._reserved_link_counts[link_key] = (
                self._reserved_link_counts.get(link_key, 0) + 1
            )

        self._remote_requests[op.op_id] = _RemoteRequest(
            op=op,
            op_qubits=op_labels,
            data_qubits=(op_labels[0], op_labels[1]),
            link_requests=link_requests,
        )

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
        logger.debug(
            "Scheduling EPR-backed request op=%d name=%s data_qubits=%s "
            "op_qubits=%s links=%s start_time=%.3f.",
            op.op_id,
            op.name,
            self._remote_requests[op.op_id].data_qubits,
            op_labels,
            tuple(sorted(link_requests)),
            start_time,
        )

    def _select_remote_ebit_assignment(
        self,
        op: Op,
    ) -> tuple[tuple[PhysicalQubit, PhysicalQubit], ...]:
        """Choose a remote e-bit assignment for this DES scheduler."""
        best_score: tuple[int, float, int] | None = None
        best_assignment: tuple[tuple[PhysicalQubit, PhysicalQubit], ...] | None
        best_assignment = None
        for index, assignment in enumerate(
            _remote_ebit_assignment_candidates(self.distributed_circuit, op)
        ):
            op_labels = _remote_operation_qubit_labels(op, assignment)
            ready_time = max(
                (self._qubit_timers.get(qubit, 0.0) for qubit in op_labels),
                default=0.0,
            )
            link_load = sum(
                self._link_load(_canonical_link_key(pair))
                for pair in _ebit_assignment_labels(assignment)
            )
            score = (link_load, ready_time, index)
            if best_score is None or score < best_score:
                best_score = score
                best_assignment = assignment

        if best_assignment is None:
            raise ValueError(
                f"Remote operation {op.op_id} has no viable e-bit assignments."
            )
        return best_assignment

    def _link_load(self, link_key: tuple[str, str]) -> int:
        """Return a small contention score for one communication link."""
        link_state = self._link_states.get(link_key)
        active_count = (
            1
            if link_state is not None
            and link_state.active_request_id is not None
            else 0
        )
        pending_count = (
            len(link_state.pending_requests) if link_state is not None else 0
        )
        return (
            active_count
            + pending_count
            + self._reserved_link_counts.get(link_key, 0)
        )

    def _activate_remote_request(
        self,
        op_id: int,
        link_key: tuple[str, str],
        time: float,
    ) -> None:
        """Start entanglement generation for one remote request."""
        request = self._remote_requests[op_id]
        link_request = request.link_requests[link_key]
        link_request.process_start_time = time
        reserved_count = self._reserved_link_counts.get(link_key, 0)
        if reserved_count <= 1:
            self._reserved_link_counts.pop(link_key, None)
        else:
            self._reserved_link_counts[link_key] = reserved_count - 1
        link_state = self._link_states.setdefault(link_key, _LinkState())
        link_state.active_request_id = op_id
        cycle_time, success_probability = self._resolve_link_parameters(
            link_key
        )
        attempt_count = self._sample_geometric_attempt_count(
            success_probability
        )
        self._enqueue_event(
            time + (attempt_count * cycle_time),
            _EPR_READY,
            op_id,
            link_key=link_key,
        )

    def _sample_geometric_attempt_count(
        self,
        success_probability: float,
    ) -> int:
        """Return the cycle number of the first successful EPR attempt.

        Repeated independent attempts with per-cycle success probability
        ``p`` have ``P(N = n) = (1 - p) ** (n - 1) * p``. Inverse-transform
        sampling draws that geometric random variable directly, avoiding one
        DES event per failed cycle while preserving the exact discrete waiting
        time distribution of the former attempt-by-attempt loop.

        Args:
            success_probability: Probability that one attempt cycle succeeds.

        Returns:
            The one-indexed cycle number of the first success.
        """
        if success_probability == 1.0:
            return 1
        uniform_sample = self._rng.random()
        return (
            math.floor(
                math.log1p(-uniform_sample) / math.log1p(-success_probability)
            )
            + 1
        )

    def _resolve_link_parameters(
        self,
        link_key: tuple[str, str],
    ) -> tuple[float, float]:
        """Return the entanglement cycle time and success probability."""
        del link_key
        return self.t_cycle, self.p_success

    def _enqueue_pending_request(
        self,
        link_state: _LinkState,
        op_id: int,
    ) -> None:
        """Queue one blocked request for later arbitration on the link."""
        if any(
            pending_request.op_id == op_id
            for pending_request in link_state.pending_requests
        ):
            return

        link_state.pending_requests.append(
            _PendingLinkRequest(
                op_id=op_id,
                enqueue_sequence=self._pending_request_sequence,
            )
        )
        self._pending_request_sequence += 1

    def _pending_request_sort_key(
        self,
        pending_request: _PendingLinkRequest,
        *,
        link_key: tuple[str, str],
        time: float,
    ) -> tuple[float, ...]:
        """Return the arbitration key for one blocked link request."""
        del link_key
        del time
        return (float(pending_request.enqueue_sequence),)

    def _request_links_available(self, op_id: int) -> bool:
        """Return True if every link the request needs is free or its own.

        A link is available to the request when no other request currently
        holds it. This gate lets a request acquire its links all-or-nothing,
        so a multi-link request never takes partial ownership of some links
        while blocked waiting for the rest.
        """
        request = self._remote_requests[op_id]
        for link_key in request.link_requests:
            link_state = self._link_states.get(link_key)
            if (
                link_state is not None
                and link_state.active_request_id is not None
                and link_state.active_request_id != op_id
            ):
                return False
        return True

    def _select_activatable_request(
        self,
        link_state: _LinkState,
        *,
        link_key: tuple[str, str],
        time: float,
    ) -> int | None:
        """Return the next queued request whose links can all be acquired.

        Pending requests are considered in arbitration order, but a request
        is skipped when any communication link it needs is held by a
        different request. Granting links all-or-nothing prevents the
        hold-and-wait cycles that would otherwise livelock crossed
        multi-link requests (each holding a link the other needs).
        """
        if not link_state.pending_requests:
            return None

        ordered_requests = sorted(
            link_state.pending_requests,
            key=lambda pending_request: self._pending_request_sort_key(
                pending_request,
                link_key=link_key,
                time=time,
            ),
        )
        for pending_request in ordered_requests:
            if self._request_links_available(pending_request.op_id):
                return pending_request.op_id
        return None

    def _remove_pending_request(self, op_id: int) -> None:
        """Drop one request from the pending queue of every link it needs."""
        request = self._remote_requests[op_id]
        for link_key in request.link_requests:
            link_state = self._link_states.get(link_key)
            if link_state is None:
                continue
            link_state.pending_requests = [
                pending_request
                for pending_request in link_state.pending_requests
                if pending_request.op_id != op_id
            ]

    def _activate_request_links(self, op_id: int, time: float) -> None:
        """Atomically start entanglement on all of a request's links.

        The request is removed from every link's pending queue and each of
        its links that is not already active for it begins entanglement
        generation. Callers must first confirm the request's links are all
        available (see ``_request_links_available``).
        """
        self._remove_pending_request(op_id)
        request = self._remote_requests[op_id]
        for link_key in request.link_requests:
            link_state = self._link_states.get(link_key)
            if (
                link_state is not None
                and link_state.active_request_id == op_id
            ):
                continue
            self._activate_remote_request(op_id, link_key, time)

    def _collect_same_time_link_start_requests(
        self,
        event: _QueueEvent,
    ) -> tuple[int, ...]:
        """Remove and return same-time start requests for one link."""
        if event.link_key is None:
            raise RuntimeError("START_EPR_REQUEST requires a link key.")

        matching_events = [
            queued_event
            for queued_event in self._event_queue
            if queued_event.event_type == _START_EPR_REQUEST
            and queued_event.time == event.time
            and queued_event.link_key == event.link_key
        ]
        if matching_events:
            matching_event_ids = {
                id(queued_event) for queued_event in matching_events
            }
            self._event_queue = [
                queued_event
                for queued_event in self._event_queue
                if id(queued_event) not in matching_event_ids
            ]
            heapq.heapify(self._event_queue)

        ordered_events = (event, *sorted(matching_events))
        return tuple(queued_event.op_id for queued_event in ordered_events)

    def _handle_event(self, event: _QueueEvent) -> None:
        """Dispatch one DES event."""
        if event.event_type == _OP_COMPLETE:
            self._mark_operation_completed(event.op_id)
            self._release_group_links_on_catdisent(event.op_id, event.time)
            return
        if event.event_type == _START_EPR_REQUEST:
            self._handle_start_epr_request(event)
            return
        if event.event_type == _EPR_READY:
            self._handle_epr_ready(event)
            return
        if event.event_type == _EPR_EXPIRE:
            self._handle_epr_expire(event)
            return
        if event.event_type == _REMOTE_OP_START:
            self._handle_remote_op_start(event)
            return
        raise RuntimeError(f"Unsupported DES event type: {event.event_type}")

    def _handle_start_epr_request(self, event: _QueueEvent) -> None:
        """Queue or activate a remote request for one link."""
        if event.link_key is None:
            raise RuntimeError("START_EPR_REQUEST requires a link key.")
        link_state = self._link_states.setdefault(event.link_key, _LinkState())
        op_ids = self._collect_same_time_link_start_requests(event)
        for op_id in op_ids:
            if link_state.active_request_id == op_id:
                continue
            self._enqueue_pending_request(link_state, op_id)

        if link_state.active_request_id is not None:
            return

        next_request_id = self._select_activatable_request(
            link_state,
            link_key=event.link_key,
            time=event.time,
        )
        if next_request_id is None:
            return
        self._activate_request_links(next_request_id, event.time)

    def _handle_epr_ready(self, event: _QueueEvent) -> None:
        """Mark one request ready and hand control to the remote op."""
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
            return
        self._enqueue_event(
            event.time + self.timing_model.epr_lifetime,
            _EPR_EXPIRE,
            event.op_id,
            link_key=event.link_key,
        )

    def _handle_epr_expire(self, event: _QueueEvent) -> None:
        """Discard one unused EPR pair and restart generation for the link."""
        if event.link_key is None:
            raise RuntimeError("EPR_EXPIRE requires a link key.")

        request = self._remote_requests[event.op_id]
        link_state = self._link_states.setdefault(event.link_key, _LinkState())
        if link_state.active_request_id != event.op_id:
            return

        link_request = request.link_requests[event.link_key]
        if link_request.ready_time is None:
            return
        if event.time < (
            link_request.ready_time + self.timing_model.epr_lifetime
        ):
            return

        self._record_link_event(
            link_request,
            end_time=event.time,
            was_used=False,
        )
        request.expired_pair_count += 1
        if request.expired_pair_count > _MAX_EXPIRED_PAIRS_PER_REQUEST:
            raise ValueError(
                f"Operation {event.op_id} ({request.op.name!r}) needs "
                f"{len(request.link_requests)} e-bit pairs held at once, but "
                f"{request.expired_pair_count} pairs expired before they all "
                "coincided, so scheduling was abandoned. An EPR lifetime of "
                f"{self.timing_model.epr_lifetime:.3g} is short relative to "
                f"the ~{self.timing_model.entanglement_time:.3g} needed to "
                "generate one pair, so the links rarely succeed close enough "
                "together. Raise epr_lifetime or the entanglement rate."
            )
        request.start_enqueued = False
        self._activate_remote_request(event.op_id, event.link_key, event.time)

    def _handle_remote_op_start(self, event: _QueueEvent) -> None:
        """Emit visible EPR and remote-op events once all links are ready."""
        request = self._remote_requests[event.op_id]
        if not all(
            self._link_states.setdefault(
                link_key, _LinkState()
            ).active_request_id
            == event.op_id
            for link_key in request.link_requests
        ):
            return
        if not all(
            link_request.ready_time is not None
            and event.time
            <= (link_request.ready_time + self.timing_model.epr_lifetime)
            for link_request in request.link_requests.values()
        ):
            return

        for link_request in request.link_requests.values():
            self._record_link_event(
                link_request,
                end_time=event.time,
                was_used=True,
            )

        scheduled_op = ScheduledOperation(
            op_id=request.op.op_id,
            statement_id=request.op.statement_id,
            name=request.op.name,
            qubits=request.op_qubits,
            start_time=event.time,
            duration=_operation_duration(request.op, self.timing_model),
            is_remote=request.op.is_remote,
        )
        self._record_scheduled_event(scheduled_op)
        for qubit in request.op_qubits:
            self._qubit_timers[qubit] = scheduled_op.end_time
        self._enqueue_event(scheduled_op.end_time, _OP_COMPLETE, event.op_id)

        # A cat-entanglement block holds its link(s) for the whole block: the
        # release is deferred until the block's catdisent completes (see
        # _release_group_links_on_catdisent). Non-group requests release now.
        if event.op_id in self._catent_groups:
            return
        for link_request in request.link_requests.values():
            self._release_link_and_promote(link_request.link_key, event.time)

    def _release_link_and_promote(
        self,
        link_key: tuple[str, str],
        time: float,
    ) -> None:
        """Free one link and activate the next queued request, if any."""
        link_state = self._link_states.setdefault(link_key, _LinkState())
        link_state.active_request_id = None
        next_request_id = self._select_activatable_request(
            link_state,
            link_key=link_key,
            time=time,
        )
        if next_request_id is None:
            return
        self._activate_request_links(next_request_id, time)

    def _release_group_links_on_catdisent(
        self,
        op_id: int,
        time: float,
    ) -> None:
        """Release a cat-ent block's held links when its catdisent ends.

        Args:
            op_id: Op id of the just-completed operation.
            time: Completion time, used to start any promoted request.
        """
        catent_op_id = self._group_by_op_id.get(op_id)
        if catent_op_id is None:
            return
        group = self._catent_groups[catent_op_id]
        if op_id != group.catdisent_op_id:
            return
        request = self._remote_requests.get(catent_op_id)
        if request is None:
            return
        for link_request in request.link_requests.values():
            self._release_link_and_promote(link_request.link_key, time)

    def _record_link_event(
        self,
        link_request: _RemoteLinkRequest,
        *,
        end_time: float,
        was_used: bool,
    ) -> None:
        """Record one used or expired EPR lifetime in the public schedule."""
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
                duration=end_time - link_request.process_start_time,
                was_used=was_used,
            )
        )
        link_request.process_start_time = None
        link_request.ready_time = None

    def _finalize_schedule(self) -> None:
        """Build the public schedule object from recorded events."""
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

    def _group_execution_duration(self, group: _CatentGroup) -> float:
        """Return the deterministic execution time for one cat-ent block.

        Sums the catent and catdisent overhead with the durations of the
        member ops (gates acting on the cat-entangled qubits). The stochastic
        EPR generation the block incurs is modelled separately by the event
        loop and is not included here.

        Args:
            group: Cat-entanglement block to measure.

        Returns:
            The block's deterministic execution duration.
        """
        duration = (
            self.timing_model.catent_time + self.timing_model.catdisent_time
        )
        for member_op_id in group.member_op_ids:
            duration += _operation_duration(
                self._op_by_id[member_op_id],
                self.timing_model,
            )
        return duration

    def _remote_duration(self, op_id: int) -> float:
        """Return the deterministic remote-op duration for one request.

        For a request anchoring a cat-entanglement block, this is the whole
        block's execution duration so duration-aware arbitration reflects the
        work inside the block rather than the constant catent overhead.
        """
        if op_id in self._catent_groups:
            return self._group_durations[op_id]
        return _operation_duration(
            self._remote_requests[op_id].op,
            self.timing_model,
        )

    def _remaining_path_cost(self, op_id: int) -> float:
        """Return the downstream critical-path estimate for one request.

        For a request anchoring a cat-entanglement block, this is the block's
        execution duration plus the downstream tail after its catdisent.
        """
        if op_id in self._group_remaining_path_costs:
            return self._group_remaining_path_costs[op_id]
        return self._remaining_path_costs[op_id]

    def _log_debug_snapshot(
        self,
        label: str,
        *,
        current_event: _QueueEvent | None = None,
    ) -> None:
        """Emit one debug-level snapshot of the DES scheduler state."""
        if not logger.isEnabledFor(logging.DEBUG):
            return

        lines = [f"DES state snapshot: {label}"]
        if current_event is not None:
            lines.append(
                f"Current event: {self._format_queue_event(current_event)}"
            )
        lines.append(
            "Queue "
            f"({len(self._event_queue)} events): "
            f"{self._format_event_queue_contents()}"
        )
        lines.append(f"Link states: {self._format_link_states()}")
        lines.append(f"Remote requests: {self._format_remote_requests()}")
        lines.append(
            "Outstanding predecessors: "
            f"{self._format_remaining_predecessors()}"
        )
        logger.debug("\n".join(lines))

    def _format_event_queue_contents(self) -> str:
        """Return a stable text view of the pending event queue."""
        if not self._event_queue:
            return "<empty>"

        ordered_events = sorted(self._event_queue)
        return "\n".join(
            f"  [{index}] {self._format_queue_event(event)}"
            for index, event in enumerate(ordered_events)
        )

    def _format_queue_event(self, event: _QueueEvent) -> str:
        """Return one readable queue entry."""
        return (
            f"t={event.time:.3f} type={event.event_type} op={event.op_id} "
            f"prio={event.priority} seq={event.sequence} "
            f"link={self._format_link_key(event.link_key)}"
        )

    def _format_link_states(self) -> str:
        """Return a readable summary of tracked communication links."""
        link_keys = sorted(
            set(self._link_states) | set(self._reserved_link_counts)
        )
        if not link_keys:
            return "<none>"

        lines: list[str] = []
        for link_key in link_keys:
            link_state = self._link_states.get(link_key, _LinkState())
            pending_ops = [
                pending_request.op_id
                for pending_request in link_state.pending_requests
            ]
            lines.append(
                "  "
                f"{self._format_link_key(link_key)} "
                f"active={link_state.active_request_id} "
                f"pending={pending_ops} "
                f"reserved={self._reserved_link_counts.get(link_key, 0)}"
            )
        return "\n".join(lines)

    def _format_remote_requests(self) -> str:
        """Return a readable summary of remote request progress."""
        if not self._remote_requests:
            return "<none>"

        lines: list[str] = []
        for op_id in sorted(self._remote_requests):
            request = self._remote_requests[op_id]
            link_summaries: list[str] = []
            for link_key in sorted(request.link_requests):
                link_request = request.link_requests[link_key]
                start_time = self._format_optional_time(
                    link_request.process_start_time
                )
                ready_time = self._format_optional_time(
                    link_request.ready_time
                )
                link_summaries.append(
                    f"{self._format_link_key(link_key)}"
                    f"(start={start_time}, ready={ready_time})"
                )
            lines.append(
                "  "
                f"op={op_id} name={request.op.name} "
                f"start_enqueued={request.start_enqueued} "
                f"links=[{', '.join(link_summaries)}]"
            )
        return "\n".join(lines)

    def _format_remaining_predecessors(self) -> str:
        """Return operations that still wait on dependencies."""
        blocked_ops = {
            op_id: count
            for op_id, count in sorted(self._remaining_predecessors.items())
            if count > 0
        }
        if not blocked_ops:
            return "<none>"
        return ", ".join(
            f"op={op_id}:{count}" for op_id, count in blocked_ops.items()
        )

    def _format_link_key(
        self,
        link_key: tuple[str, str] | None,
    ) -> str:
        """Return one readable link label."""
        if link_key is None:
            return "-"
        return f"{link_key[0]} <-> {link_key[1]}"

    def _format_optional_time(self, value: float | None) -> str:
        """Return one optional time value for debug output."""
        if value is None:
            return "-"
        return f"{value:.3f}"


def _canonical_link_key(link_qubits: tuple[str, str]) -> tuple[str, str]:
    """Return a stable key for link-state lookups."""
    ordered_qubits = sorted(link_qubits)
    return ordered_qubits[0], ordered_qubits[1]


def _initialize_qubit_state(
    ops: tuple[Op, ...],
) -> tuple[dict[str, float], list[str], dict[int, tuple[str, ...]]]:
    """Return initial per-qubit timers and stable qubit ordering."""
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


def _build_remaining_path_costs(
    *,
    op_by_id: dict[int, Op],
    successors_by_op: dict[int, tuple[int, ...]],
    timing_model: SchedulerTimingModel,
) -> dict[int, float]:
    """Return deterministic downstream critical-path costs by op id."""
    remaining_path_costs: dict[int, float] = {}
    for op_id in sorted(op_by_id, reverse=True):
        duration = _operation_duration(op_by_id[op_id], timing_model)
        successor_cost = max(
            (
                remaining_path_costs[successor_id]
                for successor_id in successors_by_op[op_id]
            ),
            default=0.0,
        )
        remaining_path_costs[op_id] = duration + successor_cost
    return remaining_path_costs


def _build_catent_groups(
    op_by_id: dict[int, Op],
) -> tuple[dict[int, _CatentGroup], dict[int, int]]:
    """Return cat-entanglement blocks reconstructed from the op stream.

    Blocks are emitted contiguously by op id and never nest, so a single
    open ``catent`` is matched with the next ``catdisent``. Inner ops are
    those between the two; the duration-contributing members are the inner
    ops whose operands touch the block's cat-entangled qubits (the data
    operands of the ``catent`` and of every inner remote gate).

    Args:
        op_by_id: All scheduled ops keyed by op id.

    Returns:
        A ``(groups, group_by_op_id)`` pair, where ``groups`` maps each
        block's ``catent`` op id to its :class:`_CatentGroup`, and
        ``group_by_op_id`` maps every op id in a block (catent, inner ops,
        and catdisent) to its block's ``catent`` op id.
    """
    groups: dict[int, _CatentGroup] = {}
    group_by_op_id: dict[int, int] = {}
    open_catent_id: int | None = None
    inner_op_ids: list[int] = []
    for op_id in sorted(op_by_id):
        op = op_by_id[op_id]
        if op.name == "catent":
            open_catent_id = op_id
            inner_op_ids = []
        elif op.name == "catdisent":
            if open_catent_id is None:
                continue
            catent_op = op_by_id[open_catent_id]
            entangled_qubits = set(catent_op.qubits[:2])
            for inner_op_id in inner_op_ids:
                inner_op = op_by_id[inner_op_id]
                if inner_op.is_remote:
                    entangled_qubits.update(inner_op.qubits[:2])
            member_op_ids = tuple(
                inner_op_id
                for inner_op_id in inner_op_ids
                if entangled_qubits.intersection(op_by_id[inner_op_id].qubits)
            )
            groups[open_catent_id] = _CatentGroup(
                catent_op_id=open_catent_id,
                member_op_ids=member_op_ids,
                catdisent_op_id=op_id,
            )
            group_by_op_id[open_catent_id] = open_catent_id
            group_by_op_id[op_id] = open_catent_id
            for inner_op_id in inner_op_ids:
                group_by_op_id[inner_op_id] = open_catent_id
            open_catent_id = None
            inner_op_ids = []
        elif open_catent_id is not None:
            inner_op_ids.append(op_id)
    return groups, group_by_op_id
