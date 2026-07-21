# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Tests for per-group (cat-entanglement block) DES scheduling."""

from dataclasses import dataclass
from typing import cast

import networkx as nx
import pytest
from openqasm3 import ast

import memq_dqc.scheduler.schedule as schedule_module
from memq_dqc.circuit import DistributedCircuit
from memq_dqc.circuit.dag import DistributedCircuitDAG
from memq_dqc.circuit.op import Op
from memq_dqc.preprocessing.qasm.types import CircuitQubit
from memq_dqc.scheduler import (
    DESLinkFIFOScheduler,
    SchedulerHardwareProfile,
    des_link_critical_path_schedule,
    des_link_fifo_schedule,
    des_link_shortest_duration_schedule,
)
from memq_dqc.scheduler.des_link_scheduler import (
    _build_catent_groups,
    _canonical_link_key,
    _LinkState,
    _PendingLinkRequest,
    _RemoteLinkRequest,
    _RemoteRequest,
)

# Patched timing model: 1q=10, 2q=500, measure=3 → catent=513, catdisent=23.
# A high entanglement rate makes EPR generation succeed on the first cycle.
_CATENT_TIME = 513.0
_CATDISENT_TIME = 23.0
_ONE_QUBIT_TIME = 10.0
_TWO_QUBIT_TIME = 500.0


def _q(register: str, index: int = 0) -> CircuitQubit:
    return CircuitQubit(register_name=register, index=index)


def _op(
    op_id: int,
    name: str,
    qubits: list[CircuitQubit],
    *,
    is_remote: bool = False,
) -> Op:
    return Op(
        op_id=op_id,
        statement_id=op_id,
        name=name,
        is_remote=is_remote,
        qubits=tuple(qubits),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier(name),
            arguments=[],
            qubits=[],
        ),
    )


@dataclass(slots=True)
class _SyntheticDAG:
    graph: nx.DiGraph


def _circuit(
    ops: list[Op],
    edges: list[tuple[int, int]],
) -> DistributedCircuit:
    graph = nx.DiGraph()
    for op in ops:
        graph.add_node(op.op_id, op=op)
    for predecessor, successor in edges:
        graph.add_edge(predecessor, successor)
    return DistributedCircuit(
        program=ast.Program(statements=[], version="3.0"),
        statements=[],
        ops=ops,
        num_two_qubit_gates=sum(1 for op in ops if op.is_remote),
        num_remote_gates=sum(1 for op in ops if op.is_remote),
        num_local_swaps_added=0,
        dag=cast(DistributedCircuitDAG, _SyntheticDAG(graph=graph)),
    )


def _patch_timing(monkeypatch: pytest.MonkeyPatch) -> None:
    def _load(
        hardware_profile: SchedulerHardwareProfile,
    ) -> schedule_module.SchedulerTimingModel:
        return schedule_module.SchedulerTimingModel(
            hardware_profile=hardware_profile,
            local_one_qubit_gate_time=_ONE_QUBIT_TIME,
            local_two_qubit_gate_time=_TWO_QUBIT_TIME,
            entanglement_generation_rate=100.0,
            des_entanglement_time_step=1.0,
            epr_lifetime=50.0,
        )

    monkeypatch.setattr(
        schedule_module,
        "_load_scheduler_timing_model",
        _load,
    )


def test_build_catent_groups_scopes_members_to_entangled_qubits():
    # Arrange: catent block over data q0,q1 with a target-qubit local gate
    # (counts) and an unrelated-qubit local gate (excluded).
    ops = [
        _op(0, "catent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
        _op(1, "rcx", [_q("q0"), _q("q1")], is_remote=True),
        _op(2, "rz", [_q("q1")]),
        _op(3, "rz", [_q("q9")]),
        _op(4, "catdisent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
    ]
    op_by_id = {op.op_id: op for op in ops}

    # Act
    groups, group_by_op_id = _build_catent_groups(op_by_id)

    # Assert: the rcx and the target-qubit rz are members; unrelated rz is not.
    assert set(groups) == {0}
    group = groups[0]
    assert group.member_op_ids == (1, 2)
    assert group.catdisent_op_id == 4
    assert group_by_op_id[4] == 0
    assert group_by_op_id[3] == 0  # still mapped for link release lookups


def test_group_duration_sums_entangled_gates_only(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_timing(monkeypatch)
    ops = [
        _op(0, "catent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
        _op(1, "rcx", [_q("q0"), _q("q1")], is_remote=True),
        _op(2, "rz", [_q("q1")]),
        _op(3, "rz", [_q("q9")]),
        _op(4, "catdisent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
    ]
    circuit = _circuit(ops, [(0, 1), (1, 2), (2, 4), (3, 4), (0, 4)])
    scheduler = DESLinkFIFOScheduler(
        circuit,
        profile=SchedulerHardwareProfile(),
        seed=0,
    )

    scheduler._reset_run_state()

    # catent + catdisent + rcx(2q) + target rz(1q); unrelated rz excluded.
    expected = (
        _CATENT_TIME + _CATDISENT_TIME + _TWO_QUBIT_TIME + _ONE_QUBIT_TIME
    )
    assert scheduler._group_durations[0] == expected


def test_block_holds_link_until_catdisent_completes(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_timing(monkeypatch)
    # Block on link (c0,c1) plus an independent competitor on the same link.
    ops = [
        _op(0, "catent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
        _op(1, "rcx", [_q("q0"), _q("q1")], is_remote=True),
        _op(2, "catdisent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
        _op(
            3,
            "rcx",
            [_q("q2"), _q("q3"), _q("c0"), _q("c1")],
            is_remote=True,
        ),
    ]
    circuit = _circuit(ops, [(0, 1), (1, 2), (0, 2)])

    schedule = des_link_fifo_schedule(circuit, seed=0)

    member = next(
        event
        for event in schedule.operations
        if event.name == "rcx" and "q0[0]" in event.qubits
    )
    competitor = next(
        event
        for event in schedule.operations
        if event.name == "rcx" and "q2[0]" in event.qubits
    )
    catdisent = next(
        event for event in schedule.operations if event.name == "catdisent"
    )

    # Per-op events keep their individual durations (timeline preserved).
    assert member.start_time == 514.0
    assert member.duration == _TWO_QUBIT_TIME
    # The competitor cannot seize the link until catdisent completes.
    assert competitor.start_time >= catdisent.end_time


def test_block_members_share_a_single_entanglement(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_timing(monkeypatch)
    # A block whose second remote gate is not a direct catent successor and
    # even carries its own candidate comm qubits; it must still reuse the
    # catent's entanglement rather than generate a second EPR pair.
    ops = [
        _op(0, "catent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
        _op(1, "rcx", [_q("q0"), _q("q1")], is_remote=True),
        _op(2, "rz", [_q("q1")]),
        _op(
            3,
            "rcx",
            [_q("q0"), _q("q1"), _q("c2"), _q("c3")],
            is_remote=True,
        ),
        _op(4, "catdisent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
    ]
    circuit = _circuit(ops, [(0, 1), (1, 2), (2, 3), (3, 4), (0, 4)])

    schedule = des_link_fifo_schedule(circuit, seed=0)

    # Exactly one EPR generation for the whole block, and both remote gates
    # still execute.
    epr_events = [e for e in schedule.operations if e.name == "epr"]
    rcx_events = [e for e in schedule.operations if e.name == "rcx"]
    assert len(epr_events) == 1
    assert len(rcx_events) == 2


def test_shortest_duration_prefers_smaller_block(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_timing(monkeypatch)
    # Block B (larger: extra target-qubit gates, lower op ids) and block A
    # (smaller), contending for the same link.
    ops = [
        _op(0, "catent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
        _op(1, "rcx", [_q("q0"), _q("q1")], is_remote=True),
        _op(2, "rz", [_q("q1")]),
        _op(3, "rz", [_q("q1")]),
        _op(4, "catdisent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
        _op(5, "catent", [_q("q4"), _q("q5"), _q("c0"), _q("c1")]),
        _op(6, "rcx", [_q("q4"), _q("q5")], is_remote=True),
        _op(7, "catdisent", [_q("q4"), _q("q5"), _q("c0"), _q("c1")]),
    ]
    edges = [
        (0, 1),
        (1, 2),
        (2, 3),
        (3, 4),
        (0, 4),
        (5, 6),
        (6, 7),
        (5, 7),
    ]
    circuit = _circuit(ops, edges)

    def _first_catent_data(schedule) -> str:
        catent = min(
            (e for e in schedule.operations if e.name == "catent"),
            key=lambda e: e.start_time,
        )
        return catent.qubits[0]

    fifo = des_link_fifo_schedule(circuit, seed=0)
    shortest = des_link_shortest_duration_schedule(circuit, seed=0)

    # FIFO serves the earlier-enqueued (larger) block B first; shortest
    # duration serves the smaller block A (q4) first.
    assert _first_catent_data(fifo) == "q0[0]"
    assert _first_catent_data(shortest) == "q4[0]"


def test_critical_path_prefers_block_with_longer_tail(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_timing(monkeypatch)
    # Block P (no tail, lower op ids) and block Q (long local tail), same link.
    ops = [
        _op(0, "catent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
        _op(1, "rcx", [_q("q0"), _q("q1")], is_remote=True),
        _op(2, "catdisent", [_q("q0"), _q("q1"), _q("c0"), _q("c1")]),
        _op(3, "catent", [_q("q4"), _q("q5"), _q("c0"), _q("c1")]),
        _op(4, "rcx", [_q("q4"), _q("q5")], is_remote=True),
        _op(5, "catdisent", [_q("q4"), _q("q5"), _q("c0"), _q("c1")]),
        _op(6, "rz", [_q("q5")]),
        _op(7, "rz", [_q("q5")]),
        _op(8, "rz", [_q("q5")]),
    ]
    edges = [
        (0, 1),
        (1, 2),
        (0, 2),
        (3, 4),
        (4, 5),
        (3, 5),
        (5, 6),
        (6, 7),
        (7, 8),
    ]
    circuit = _circuit(ops, edges)

    def _first_catent_data(schedule) -> str:
        catent = min(
            (e for e in schedule.operations if e.name == "catent"),
            key=lambda e: e.start_time,
        )
        return catent.qubits[0]

    fifo = des_link_fifo_schedule(circuit, seed=0)
    critical = des_link_critical_path_schedule(circuit, seed=0)

    # FIFO serves the earlier block P first; critical-path serves block Q
    # (q4) first because of its longer downstream tail.
    assert _first_catent_data(fifo) == "q0[0]"
    assert _first_catent_data(critical) == "q4[0]"


def _multi_link_request(
    op: Op, links: list[tuple[str, str]]
) -> _RemoteRequest:
    link_requests = {}
    for link_qubits in links:
        link_key = _canonical_link_key(link_qubits)
        link_requests[link_key] = _RemoteLinkRequest(
            link_qubits=link_qubits, link_key=link_key
        )
    return _RemoteRequest(
        op=op,
        op_qubits=tuple(q.register_name for q in op.qubits),
        data_qubits=(op.qubits[0].register_name, op.qubits[1].register_name),
        link_requests=link_requests,
    )


def test_multi_link_activation_is_all_or_nothing(
    monkeypatch: pytest.MonkeyPatch,
):
    # Two remote requests each need BOTH links (c0,c1) and (c2,c3). While
    # either link is held by a different request, neither may take partial
    # ownership of the other -- the hold-and-wait pattern that previously
    # let crossed multi-link requests livelock. Links are granted only when
    # all of a request's links are simultaneously free.
    _patch_timing(monkeypatch)
    circuit = _circuit([_op(0, "h", [_q("q0")])], [])
    scheduler = DESLinkFIFOScheduler(
        circuit, profile=SchedulerHardwareProfile(), seed=0
    )
    scheduler._reset_run_state()

    l1 = _canonical_link_key(("c0", "c1"))
    l2 = _canonical_link_key(("c2", "c3"))
    op_a = _op(10, "rcx", [_q("q0"), _q("q1")], is_remote=True)
    op_b = _op(11, "rcx", [_q("q4"), _q("q5")], is_remote=True)
    scheduler._remote_requests[10] = _multi_link_request(
        op_a, [("c0", "c1"), ("c2", "c3")]
    )
    scheduler._remote_requests[11] = _multi_link_request(
        op_b, [("c0", "c1"), ("c2", "c3")]
    )

    # Both links are currently held by unrelated requests, with A and B
    # queued behind them on each link.
    scheduler._link_states[l1] = _LinkState(
        active_request_id=98,
        pending_requests=[
            _PendingLinkRequest(op_id=10, enqueue_sequence=0),
            _PendingLinkRequest(op_id=11, enqueue_sequence=2),
        ],
    )
    scheduler._link_states[l2] = _LinkState(
        active_request_id=99,
        pending_requests=[
            _PendingLinkRequest(op_id=10, enqueue_sequence=1),
            _PendingLinkRequest(op_id=11, enqueue_sequence=3),
        ],
    )

    # Free only L1: no request may activate, because each still needs L2
    # (held by request 99). Old logic would have granted L1 to a request,
    # creating a partial hold.
    scheduler._link_states[l1].active_request_id = None
    assert (
        scheduler._select_activatable_request(
            scheduler._link_states[l1], link_key=l1, time=0.0
        )
        is None
    )
    assert not scheduler._request_links_available(10)

    # Free L2 as well: request 10 (lowest arbitration key) can now take
    # both links atomically.
    scheduler._link_states[l2].active_request_id = None
    assert scheduler._request_links_available(10)
    assert (
        scheduler._select_activatable_request(
            scheduler._link_states[l1], link_key=l1, time=0.0
        )
        == 10
    )
    scheduler._activate_request_links(10, 0.0)
    assert scheduler._link_states[l1].active_request_id == 10
    assert scheduler._link_states[l2].active_request_id == 10
    # Request 10 is no longer queued on either link.
    assert all(
        pending.op_id != 10
        for pending in scheduler._link_states[l1].pending_requests
    )
    assert all(
        pending.op_id != 10
        for pending in scheduler._link_states[l2].pending_requests
    )


def test_crossed_multi_link_blocks_terminate_and_serialize(
    monkeypatch: pytest.MonkeyPatch,
):
    # Two cat-entanglement blocks that each hold the same two links for the
    # whole block. Scheduling must terminate and serialize the blocks on the
    # shared links rather than deadlock with each holding one link.
    _patch_timing(monkeypatch)
    ops = [
        _op(
            0,
            "catent",
            [_q("q0"), _q("q1"), _q("c0"), _q("c1"), _q("c2"), _q("c3")],
        ),
        _op(1, "rcx", [_q("q0"), _q("q1")], is_remote=True),
        _op(
            2,
            "catdisent",
            [_q("q0"), _q("q1"), _q("c0"), _q("c1"), _q("c2"), _q("c3")],
        ),
        _op(
            3,
            "catent",
            [_q("q4"), _q("q5"), _q("c0"), _q("c1"), _q("c2"), _q("c3")],
        ),
        _op(4, "rcx", [_q("q4"), _q("q5")], is_remote=True),
        _op(
            5,
            "catdisent",
            [_q("q4"), _q("q5"), _q("c0"), _q("c1"), _q("c2"), _q("c3")],
        ),
    ]
    edges = [(0, 1), (1, 2), (0, 2), (3, 4), (4, 5), (3, 5)]
    circuit = _circuit(ops, edges)

    for scheduler_fn in (
        des_link_fifo_schedule,
        des_link_critical_path_schedule,
        des_link_shortest_duration_schedule,
    ):
        schedule = scheduler_fn(circuit, seed=0)
        scheduled_op_ids = {
            event.op_id
            for event in schedule.operations
            if hasattr(event, "op_id")
        }
        # Every operation is scheduled (the run terminates).
        assert {0, 1, 2, 3, 4, 5} <= scheduled_op_ids

        first_catdisent = min(
            (e for e in schedule.operations if e.name == "catdisent"),
            key=lambda e: e.start_time,
        )
        second_catent = max(
            (e for e in schedule.operations if e.name == "catent"),
            key=lambda e: e.start_time,
        )
        # The blocks do not overlap on the shared links: the second block's
        # catent starts only after the first block releases them.
        assert second_catent.start_time >= first_catdisent.end_time
