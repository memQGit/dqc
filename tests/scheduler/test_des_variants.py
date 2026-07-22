# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import networkx as nx
import pytest
from openqasm3 import ast

import memq_dqc.scheduler.schedule as schedule_module
from memq_dqc.builder import extract_distributed_circuit
from memq_dqc.circuit import DistributedCircuit
from memq_dqc.circuit.op import Op
from memq_dqc.network import NetworkGraph
from memq_dqc.partition import Partitioner
from memq_dqc.partition.partitioner import QPU, BasePartitioner
from memq_dqc.preprocessing.qasm.io import load_qasm_program
from memq_dqc.preprocessing.qasm.types import CircuitQubit
from memq_dqc.scheduler import (
    DESLinkCriticalPathScheduler,
    DESLinkShortestDurationScheduler,
    OperationSchedule,
    Scheduler,
)
from memq_dqc.scheduler.des_link_scheduler import (
    _LinkState,
    _PendingLinkRequest,
    _RemoteLinkRequest,
    _RemoteRequest,
)
from memq_dqc.scheduler.schedule import (
    SchedulerHardwareProfile,
    SchedulerTimingModel,
)


def _register_single_link_request(scheduler, op_id, link):
    link_key = tuple(sorted(link))
    scheduler._remote_requests[op_id] = _RemoteRequest(
        op=None,
        op_qubits=(),
        data_qubits=("", ""),
        link_requests={
            link_key: _RemoteLinkRequest(link_qubits=link, link_key=link_key)
        },
    )


class _TwoQpuPartitioner(BasePartitioner):
    def run(self) -> None:
        self.windows = [self.circuit.mono.ops]
        self.schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]
        self.cost = 0.0


class _SyntheticDAG:
    def __init__(self, graph):
        self.graph = graph


def _build_distributed_circuit(tmp_path, network_path):
    qasm_path = tmp_path / "des_variant_schedule.qasm"
    qasm_path.write_text(
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[2] q;\n"
            "cx q[0], q[1];\n"
        ),
        encoding="utf-8",
    )
    program = load_qasm_program(str(qasm_path))
    network = NetworkGraph(str(network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_TwoQpuPartitioner(network, program),
    )
    partitioner.run()
    extract_distributed_circuit(partitioner)
    assert partitioner.circuit.distributed is not None
    return partitioner.circuit.distributed


def _remote_gate(
    op_id: int, name: str, data_register_a: str, data_register_b: str
) -> Op:
    qubits: tuple[CircuitQubit, ...] = (
        CircuitQubit(register_name=data_register_a, index=0),
        CircuitQubit(register_name=data_register_b, index=0),
        CircuitQubit(register_name="c0", index=0),
        CircuitQubit(register_name="c1", index=0),
    )
    if name == "rswap":
        qubits += (
            CircuitQubit(register_name="c0", index=1),
            CircuitQubit(register_name="c1", index=1),
        )

    return Op(
        op_id=op_id,
        statement_id=op_id,
        name=name,
        is_remote=True,
        qubits=qubits,
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier(name),
            arguments=[],
            qubits=[],
        ),
    )


def _local_gate(op_id: int, name: str, register_name: str) -> Op:
    return Op(
        op_id=op_id,
        statement_id=op_id,
        name=name,
        is_remote=False,
        qubits=(CircuitQubit(register_name=register_name, index=0),),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier(name),
            arguments=[],
            qubits=[],
        ),
    )


def _build_divergence_case() -> DistributedCircuit:
    ops = [
        _remote_gate(0, "rcx", "q10", "q11"),
        _remote_gate(1, "rswap", "q0", "q1"),
        _remote_gate(2, "rcx", "q2", "q3"),
        _remote_gate(3, "rcx", "q4", "q5"),
        _local_gate(4, "x", "q4"),
        _local_gate(5, "h", "q4"),
        _local_gate(6, "z", "q4"),
        _local_gate(7, "x", "q4"),
        _local_gate(8, "h", "q4"),
    ]

    graph = nx.DiGraph()
    for op in ops:
        graph.add_node(op.op_id, op=op)

    for predecessor, successor in (
        (3, 4),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 8),
    ):
        graph.add_edge(predecessor, successor)

    return DistributedCircuit(
        program=ast.Program(statements=[], version="3.0"),
        statements=[],
        ops=ops,
        num_two_qubit_gates=4,
        num_remote_gates=4,
        num_local_swaps_added=0,
        dag=_SyntheticDAG(graph),
    )


def _build_canonical_three_request_case() -> DistributedCircuit:
    ops = [
        _remote_gate(0, "rcx", "q20", "q21"),
        _remote_gate(1, "rswap", "q0", "q1"),
        _remote_gate(2, "rcx", "q2", "q3"),
        _remote_gate(3, "rcx", "q4", "q5"),
        _local_gate(4, "x", "q4"),
        _local_gate(5, "h", "q4"),
        _local_gate(6, "z", "q4"),
        _local_gate(7, "x", "q4"),
        _local_gate(8, "h", "q4"),
        _local_gate(9, "z", "q4"),
        _local_gate(10, "x", "q4"),
        _local_gate(11, "h", "q4"),
        _local_gate(12, "z", "q4"),
        _local_gate(13, "x", "q4"),
    ]

    graph = nx.DiGraph()
    for op in ops:
        graph.add_node(op.op_id, op=op)

    for predecessor, successor in (
        (3, 4),
        (4, 5),
        (5, 6),
        (6, 7),
        (7, 8),
        (8, 9),
        (9, 10),
        (10, 11),
        (11, 12),
        (12, 13),
    ):
        graph.add_edge(predecessor, successor)

    return DistributedCircuit(
        program=ast.Program(statements=[], version="3.0"),
        statements=[],
        ops=ops,
        num_two_qubit_gates=4,
        num_remote_gates=4,
        num_local_swaps_added=0,
        dag=_SyntheticDAG(graph),
    )


def _build_initial_link_contention_case() -> DistributedCircuit:
    ops = [
        _remote_gate(0, "rswap", "q0", "q1"),
        _remote_gate(1, "rcx", "q2", "q3"),
        _remote_gate(2, "rcx", "q4", "q5"),
        _local_gate(3, "x", "q4"),
        _local_gate(4, "h", "q4"),
        _local_gate(5, "z", "q4"),
        _local_gate(6, "x", "q4"),
        _local_gate(7, "h", "q4"),
    ]

    graph = nx.DiGraph()
    for op in ops:
        graph.add_node(op.op_id, op=op)

    for predecessor, successor in (
        (2, 3),
        (3, 4),
        (4, 5),
        (5, 6),
        (6, 7),
    ):
        graph.add_edge(predecessor, successor)

    return DistributedCircuit(
        program=ast.Program(statements=[], version="3.0"),
        statements=[],
        ops=ops,
        num_two_qubit_gates=3,
        num_remote_gates=3,
        num_local_swaps_added=0,
        dag=_SyntheticDAG(graph),
    )


def _patch_scheduler_timing_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _load_timing_model(
        hardware_profile: SchedulerHardwareProfile,
    ) -> SchedulerTimingModel:
        return SchedulerTimingModel(
            hardware_profile=hardware_profile,
            local_one_qubit_gate_time=1.0,
            local_two_qubit_gate_time=5.0,
            entanglement_generation_rate=100.0,
            des_entanglement_time_step=1.0,
            epr_lifetime=50.0,
        )

    monkeypatch.setattr(
        schedule_module,
        "_load_scheduler_timing_model",
        _load_timing_model,
    )


def test_scheduler_runs_des_link_fifo_via_clear_registry_name(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )

    scheduler = Scheduler(
        distributed_circuit,
        algo="des_link_fifo",
        algo_kwargs={"seed": 0},
    )
    scheduler.run()

    assert isinstance(scheduler.schedule, OperationSchedule)
    assert [event.name for event in scheduler.schedule.operations] == [
        "epr",
        "catent",
        "rcx",
        "catdisent",
    ]


@pytest.mark.parametrize(
    "removed_name",
    [
        "des",
        "des_epr",
        "des_entanglement",
        "des_shortest_duration",
        "des_critical_path",
    ],
)
def test_scheduler_rejects_removed_legacy_registry_names(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    removed_name: str,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )

    with pytest.raises(ValueError, match="Unknown scheduling algorithm"):
        Scheduler(distributed_circuit, algo=removed_name)


def test_shortest_duration_variant_prefers_shorter_request(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )
    scheduler = DESLinkShortestDurationScheduler(distributed_circuit)
    monkeypatch.setattr(
        scheduler,
        "_remote_duration",
        lambda op_id: 20.0 if op_id == 0 else 5.0,
    )
    _register_single_link_request(scheduler, 0, ("c0[0]", "c1[0]"))
    _register_single_link_request(scheduler, 1, ("c0[0]", "c1[0]"))
    link_state = _LinkState(
        pending_requests=[
            _PendingLinkRequest(op_id=0, enqueue_sequence=0),
            _PendingLinkRequest(op_id=1, enqueue_sequence=1),
        ]
    )

    next_request_id = scheduler._select_activatable_request(
        link_state,
        link_key=("c0[0]", "c1[0]"),
        time=0.0,
    )

    assert next_request_id == 1


def test_critical_path_variant_prefers_larger_remaining_path(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )
    scheduler = DESLinkCriticalPathScheduler(distributed_circuit)
    monkeypatch.setattr(
        scheduler,
        "_remaining_path_cost",
        lambda op_id: 100.0 if op_id == 0 else 10.0,
    )
    _register_single_link_request(scheduler, 0, ("c0[0]", "c1[0]"))
    _register_single_link_request(scheduler, 1, ("c0[0]", "c1[0]"))
    link_state = _LinkState(
        pending_requests=[
            _PendingLinkRequest(op_id=0, enqueue_sequence=1),
            _PendingLinkRequest(op_id=1, enqueue_sequence=0),
        ]
    )

    next_request_id = scheduler._select_activatable_request(
        link_state,
        link_key=("c0[0]", "c1[0]"),
        time=0.0,
    )

    assert next_request_id == 0


def test_des_link_variants_arbitrate_initial_same_time_contention(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_scheduler_timing_model(monkeypatch)
    distributed_circuit = _build_initial_link_contention_case()

    first_remote_starts = {}
    for algorithm in (
        "des_link_fifo",
        "des_link_shortest_duration",
        "des_link_critical_path",
    ):
        scheduler = Scheduler(
            distributed_circuit,
            algo=algorithm,
            profile=SchedulerHardwareProfile(),
            algo_kwargs={"seed": 0},
        )
        scheduler.run()
        assert scheduler.schedule is not None
        first_remote_starts[algorithm] = next(
            event.op_id
            for event in scheduler.schedule.operations
            if hasattr(event, "op_id") and event.op_id in {0, 1, 2}
        )

    assert first_remote_starts == {
        "des_link_fifo": 0,
        "des_link_shortest_duration": 0,
        "des_link_critical_path": 2,
    }


def test_des_variants_diverge_on_shared_link_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_scheduler_timing_model(monkeypatch)
    distributed_circuit = _build_divergence_case()

    makespans = {}
    start_times = {}
    for algorithm in (
        "des_link_fifo",
        "des_link_shortest_duration",
        "des_link_critical_path",
    ):
        scheduler = Scheduler(
            distributed_circuit,
            algo=algorithm,
            profile=SchedulerHardwareProfile(),
            algo_kwargs={"seed": 0},
        )
        scheduler.run()
        assert scheduler.schedule is not None
        makespans[algorithm] = scheduler.schedule.makespan
        start_times[algorithm] = {
            event.op_id: event.start_time
            for event in scheduler.schedule.operations
            if hasattr(event, "op_id")
        }

    assert makespans == {
        "des_link_fifo": 14.0,
        "des_link_shortest_duration": 14.0,
        "des_link_critical_path": 11.0,
    }
    assert start_times["des_link_fifo"] == {
        0: 1.0,
        1: 2.0,
        2: 3.0,
        3: 4.0,
        4: 9.0,
        5: 10.0,
        6: 11.0,
        7: 12.0,
        8: 13.0,
    }
    assert start_times["des_link_shortest_duration"] == {
        0: 1.0,
        1: 2.0,
        2: 3.0,
        3: 4.0,
        4: 9.0,
        5: 10.0,
        6: 11.0,
        7: 12.0,
        8: 13.0,
    }
    assert start_times["des_link_critical_path"] == {
        0: 2.0,
        1: 3.0,
        2: 4.0,
        3: 1.0,
        4: 6.0,
        5: 7.0,
        6: 8.0,
        7: 9.0,
        8: 10.0,
    }


def test_des_variants_diverge_on_canonical_three_request_queue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_scheduler_timing_model(monkeypatch)
    distributed_circuit = _build_canonical_three_request_case()

    results = {}
    for algorithm in (
        "des_link_fifo",
        "des_link_shortest_duration",
        "des_link_critical_path",
    ):
        scheduler = Scheduler(
            distributed_circuit,
            algo=algorithm,
            profile=SchedulerHardwareProfile(),
            algo_kwargs={"seed": 0},
        )
        scheduler.run()
        assert scheduler.schedule is not None
        remote_start_order = [
            event.op_id
            for event in scheduler.schedule.operations
            if hasattr(event, "op_id") and event.op_id in {1, 2, 3}
        ]
        results[algorithm] = (
            scheduler.schedule.makespan,
            remote_start_order,
        )

    assert results == {
        "des_link_fifo": (19.0, [1, 2, 3]),
        "des_link_shortest_duration": (19.0, [1, 2, 3]),
        "des_link_critical_path": (16.0, [3, 1, 2]),
    }
