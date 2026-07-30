# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import io
from pathlib import Path
from typing import Any

import openqasm3
import pytest
from qiskit import qasm3
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit

from xdqc.builder.extract_utils import SwapOp
from xdqc.circuit import Circuit, DistributedCircuit, Op
from xdqc.circuit.dag import CircuitDAG
from xdqc.network import NetworkGraph, PhysicalQubit
from xdqc.partition.partitioner import QPU
from xdqc.preprocessing.qasm.types import CircuitQubit, CleanedQuantumGate


def _build_memq_circuit(qasm_path: Path) -> Circuit:
    return Circuit(str(qasm_path))


def _build_memq_dag(qasm_path: Path) -> CircuitDAG:
    return _build_memq_circuit(qasm_path).mono.dag


def _build_distributed(
    circuit: Circuit,
    remote_statement_ids: set[int],
    *,
    swaps_schedule: list[list[SwapOp]],
    windows: list[list[Op]],
    schedule: list[dict[QPU, set[int]]],
    network: Any,
    comp_qubits_per_qpu: list[int] | None = None,
    comm_qubits_per_qpu: list[int] | None = None,
    ebit_assignment: bool = True,
) -> DistributedCircuit:
    return circuit.build_distributed(
        remote_statement_ids=remote_statement_ids,
        swaps_schedule=swaps_schedule,
        windows=windows,
        schedule=schedule,
        network=network,
        comp_qubits_per_qpu=comp_qubits_per_qpu,
        comm_qubits_per_qpu=comm_qubits_per_qpu,
        ebit_assignment=ebit_assignment,
    )


def _build_qiskit_dag(qasm_path: Path) -> DAGCircuit:
    qasm_source = qasm_path.read_text(encoding="utf-8")
    circuit = qasm3.loads(qasm_source)
    return circuit_to_dag(circuit)


def _qiskit_op_nodes(dag: DAGCircuit) -> list[Any]:
    return list(dag.op_nodes())


def _qiskit_op_signatures(
    dag: DAGCircuit,
    nodes: list[Any],
) -> list[tuple[str, tuple[int, ...]]]:
    qubit_index = {qubit: idx for idx, qubit in enumerate(dag.qubits)}
    return [
        (node.name, tuple(qubit_index[q] for q in node.qargs))
        for node in nodes
    ]


def _qiskit_edges(
    dag: DAGCircuit,
    nodes: list[Any],
) -> dict[tuple[int, int], set[int]]:
    node_index = {node: idx for idx, node in enumerate(nodes)}
    edges: dict[tuple[int, int], set[int]] = {}
    for q_index, wire in enumerate(dag.qubits):
        wire_nodes = list(dag.nodes_on_wire(wire, only_ops=True))
        for prev_node, next_node in zip(
            wire_nodes,
            wire_nodes[1:],
            strict=False,
        ):
            key = (node_index[prev_node], node_index[next_node])
            edges.setdefault(key, set()).add(q_index)
    return edges


def _memq_edges(dag: CircuitDAG) -> dict[tuple[int, int], set[int]]:
    edges: dict[tuple[int, int], set[int]] = {}
    for u, v, data in dag.graph.edges(data=True):
        edges[(u, v)] = {q.index for q in data["qubits"]}
    return edges


def _qiskit_layers(
    dag: DAGCircuit,
) -> list[frozenset[tuple[str, tuple[int, ...]]]]:
    qubit_index = {qubit: idx for idx, qubit in enumerate(dag.qubits)}
    layers: list[frozenset[tuple[str, tuple[int, ...]]]] = []
    for layer in dag.layers():
        layer_dag = layer
        if isinstance(layer, dict):
            layer_dag = layer.get("graph", layer)
        nodes = list(layer_dag.op_nodes())
        layers.append(
            frozenset(
                (node.name, tuple(qubit_index[q] for q in node.qargs))
                for node in nodes
            )
        )
    return layers


def _memq_layers(
    dag: CircuitDAG,
) -> list[frozenset[tuple[str, tuple[int, ...]]]]:
    return [
        frozenset((op.name, op.qubit_indices) for op in layer)
        for layer in dag.layers
    ]


@pytest.mark.parametrize(
    "fixture_name",
    [
        "bell_circuit_path",
        "simple1_circuit_path",
    ],
)
def test_dag_matches_qiskit(
    request: pytest.FixtureRequest,
    fixture_name: str,
) -> None:
    qasm_path = request.getfixturevalue(fixture_name)
    memq_circuit = _build_memq_circuit(qasm_path)
    memq_dag = _build_memq_dag(qasm_path)
    qiskit_dag = _build_qiskit_dag(qasm_path)
    qiskit_nodes = _qiskit_op_nodes(qiskit_dag)

    memq_ops = [(op.name, op.qubit_indices) for op in memq_circuit.mono.ops]
    qiskit_ops = _qiskit_op_signatures(qiskit_dag, qiskit_nodes)
    assert memq_ops == qiskit_ops
    assert _memq_edges(memq_dag) == _qiskit_edges(qiskit_dag, qiskit_nodes)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "bell_circuit_path",
        "simple1_circuit_path",
    ],
)
def test_depth_matches_qiskit(
    request: pytest.FixtureRequest,
    fixture_name: str,
) -> None:
    qasm_path = request.getfixturevalue(fixture_name)
    memq_dag = _build_memq_dag(qasm_path)
    qiskit_dag = _build_qiskit_dag(qasm_path)

    assert memq_dag.depth == qiskit_dag.depth()


@pytest.mark.parametrize(
    "fixture_name",
    [
        "bell_circuit_path",
        "simple1_circuit_path",
    ],
)
def test_layers_match_qiskit(
    request: pytest.FixtureRequest,
    fixture_name: str,
) -> None:
    qasm_path = request.getfixturevalue(fixture_name)
    memq_dag = _build_memq_dag(qasm_path)
    qiskit_dag = _build_qiskit_dag(qasm_path)

    assert _memq_layers(memq_dag) == _qiskit_layers(qiskit_dag)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "bell_circuit_path",
        "simple1_circuit_path",
    ],
)
def test_layer_qubits_are_sorted_unique(
    request: pytest.FixtureRequest,
    fixture_name: str,
) -> None:
    qasm_path = request.getfixturevalue(fixture_name)
    memq_dag = _build_memq_dag(qasm_path)

    for layer in memq_dag.layers:
        expected = sorted({q for op in layer for q in op.qubit_indices})
        assert layer.qubits == expected


@pytest.mark.parametrize(
    ("fixture_name", "expected_two_qubit_gates"),
    [
        ("simple1_circuit_path", 8),
        ("bell_circuit_path", 1),
    ],
)
def test_count_two_qubit_gates(
    request: pytest.FixtureRequest,
    fixture_name: str,
    expected_two_qubit_gates: int,
) -> None:
    qasm_path = request.getfixturevalue(fixture_name)
    circuit = _build_memq_circuit(qasm_path)
    assert circuit.mono.num_two_qubit_gates == expected_two_qubit_gates


def test_distributed_dag_counts_remote_gates(
    tmp_path: Path,
) -> None:
    class _RemoteGateNetwork:
        def __init__(self) -> None:
            self.qubit_type_map = {
                PhysicalQubit(0, 0, "computation"): "computation",
                PhysicalQubit(1, 0, "computation"): "computation",
            }

        def get_comm_pair_options(self, qubit_a, qubit_b):
            comm_pair = (
                PhysicalQubit(0, 0, "communication"),
                PhysicalQubit(1, 0, "communication"),
            )
            return [
                (
                    0,
                    comm_pair,
                    ([qubit_a, comm_pair[0]], [qubit_b, comm_pair[1]]),
                )
            ]

    qasm_path = tmp_path / "single_remote.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\ncx q[0], q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    remote_statement_ids = {circuit.mono.ops[0].statement_id}
    distributed = _build_distributed(
        circuit,
        remote_statement_ids,
        swaps_schedule=[],
        windows=[circuit.mono.ops],
        schedule=[{QPU(id=0): {0}, QPU(id=1): {1}}],
        comp_qubits_per_qpu=[1, 1],
        comm_qubits_per_qpu=[1, 1],
        network=_RemoteGateNetwork(),
    )

    assert distributed.num_remote_gates == 1
    assert distributed.dag.depth == len(distributed.dag.layers)


def test_distributed_dag_validates_schedule_and_swaps_shape(
    request: pytest.FixtureRequest,
) -> None:
    class _StubNetwork:
        qpus = {0: object()}

    qasm_path = request.getfixturevalue("bell_circuit_path")
    circuit = _build_memq_circuit(qasm_path)
    remote_statement_ids: set[int] = set()
    qpu0 = QPU(id=0)
    all_qubits = {q.index for op in circuit.mono.ops for q in op.qubits}
    windows = [circuit.mono.ops[:1], circuit.mono.ops[1:]]
    schedule = [{qpu0: all_qubits}]
    swaps_schedule: list[list[SwapOp]] = []

    with pytest.raises(ValueError, match="schedule/windows length mismatch"):
        _build_distributed(
            circuit,
            remote_statement_ids,
            swaps_schedule=swaps_schedule,
            windows=windows,
            schedule=schedule,
            network=_StubNetwork(),
        )


def test_distributed_dag_remote_gate_uses_final_swapped_qubits(
    tmp_path: Path,
) -> None:
    class _StubNetwork:
        def __init__(self) -> None:
            self.qubit_type_map = {
                PhysicalQubit(0, 0, "computation"): "computation",
                PhysicalQubit(1, 0, "computation"): "computation",
            }

        def get_comm_pair_options(self, qubit_a, qubit_b):
            comm_pair = (
                PhysicalQubit(0, 0, "communication"),
                PhysicalQubit(1, 0, "communication"),
            )
            path_a = [
                qubit_a,
                PhysicalQubit(qubit_a.qpu_id, 1, "computation"),
                comm_pair[0],
            ]
            path_b = [
                qubit_b,
                PhysicalQubit(qubit_b.qpu_id, 2, "computation"),
                comm_pair[1],
            ]
            return [(2, comm_pair, (path_a, path_b))]

    qasm_path = tmp_path / "single_remote.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\ncx q[0], q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    remote_statement_ids = {circuit.mono.ops[0].statement_id}
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    windows = [circuit.mono.ops]
    schedule = [{qpu0: {0}, qpu1: {1}}]

    distributed = _build_distributed(
        circuit,
        remote_statement_ids=remote_statement_ids,
        swaps_schedule=[],
        windows=windows,
        schedule=schedule,
        comp_qubits_per_qpu=[3, 3],
        comm_qubits_per_qpu=[1, 1],
        network=_StubNetwork(),
    )

    remote_gates = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate)
        and statement.name == "rcx"
    ]
    assert len(remote_gates) == 1
    assert remote_gates[0].qubits[:2] == [
        CircuitQubit("q0", 1),
        CircuitQubit("q1", 2),
    ]


def test_distributed_dag_iterates_topologically_with_remote_ops(
    tmp_path: Path,
) -> None:
    class _RemoteGateNetwork:
        def __init__(self) -> None:
            self.qubit_type_map = {
                PhysicalQubit(0, 0, "computation"): "computation",
                PhysicalQubit(1, 0, "computation"): "computation",
            }

        def get_comm_pair_options(self, qubit_a, qubit_b):
            comm_pair = (
                PhysicalQubit(0, 0, "communication"),
                PhysicalQubit(1, 0, "communication"),
            )
            return [
                (
                    0,
                    comm_pair,
                    ([qubit_a, comm_pair[0]], [qubit_b, comm_pair[1]]),
                )
            ]

    qasm_path = tmp_path / "remote_after_local.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\nh q[0];\ncx q[0], q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    remote_statement_ids = {circuit.mono.ops[1].statement_id}
    distributed = _build_distributed(
        circuit,
        remote_statement_ids=remote_statement_ids,
        swaps_schedule=[],
        windows=[circuit.mono.ops],
        schedule=[{QPU(id=0): {0}, QPU(id=1): {1}}],
        comp_qubits_per_qpu=[1, 1],
        comm_qubits_per_qpu=[1, 1],
        network=_RemoteGateNetwork(),
    )

    ops = list(distributed.dag)

    assert [op.name for op in ops] == ["h", "catent", "rcx", "catdisent"]
    assert [op.is_remote for op in ops] == [False, False, True, False]
    assert ops == list(distributed.dag.iter_topological())


def test_distributed_dag_remote_gate_local_swaps_follow_path_order(
    tmp_path: Path,
) -> None:
    class _MultiHopNetwork:
        def __init__(self) -> None:
            self.qubit_type_map = {
                PhysicalQubit(0, 0, "computation"): "computation",
                PhysicalQubit(1, 0, "computation"): "computation",
            }

        def get_comm_pair_options(self, qubit_a, qubit_b):
            comm_pair = (
                PhysicalQubit(0, 0, "communication"),
                PhysicalQubit(1, 0, "communication"),
            )
            path_a = [qubit_a, comm_pair[0]]
            path_b = [
                qubit_b,
                PhysicalQubit(qubit_b.qpu_id, 1, "computation"),
                PhysicalQubit(qubit_b.qpu_id, 2, "computation"),
                comm_pair[1],
            ]
            return [(3, comm_pair, (path_a, path_b))]

    qasm_path = tmp_path / "single_remote.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\ncx q[0], q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    remote_statement_ids = {circuit.mono.ops[0].statement_id}
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    windows = [circuit.mono.ops]
    schedule = [{qpu0: {0}, qpu1: {1}}]

    distributed = _build_distributed(
        circuit,
        remote_statement_ids=remote_statement_ids,
        swaps_schedule=[],
        windows=windows,
        schedule=schedule,
        comp_qubits_per_qpu=[3, 3],
        comm_qubits_per_qpu=[1, 1],
        network=_MultiHopNetwork(),
    )

    remote_gate_sequence = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate)
    ]

    assert [statement.name for statement in remote_gate_sequence] == [
        "swap",
        "swap",
        "catent",
        "rcx",
        "catdisent",
    ]
    # swap
    assert remote_gate_sequence[0].qubits == [
        CircuitQubit("q1", 0),
        CircuitQubit("q1", 1),
    ]
    # swap
    assert remote_gate_sequence[1].qubits == [
        CircuitQubit("q1", 1),
        CircuitQubit("q1", 2),
    ]
    # catent
    assert remote_gate_sequence[2].qubits == [
        CircuitQubit("q0", 0),
        CircuitQubit("q1", 2),
        CircuitQubit("c0", 0),
        CircuitQubit("c1", 0),
    ]
    # rcx
    assert remote_gate_sequence[3].qubits[:2] == [
        CircuitQubit("q0", 0),
        CircuitQubit("q1", 2),
    ]
    # catdisent
    assert remote_gate_sequence[4].qubits == [
        CircuitQubit("q0", 0),
        CircuitQubit("q1", 2),
        CircuitQubit("c0", 0),
        CircuitQubit("c1", 0),
    ]


def test_distributed_dag_tracks_persistent_local_routing_swaps(
    tmp_path: Path,
) -> None:
    class _MultiHopNetwork:
        def __init__(self) -> None:
            self.qubit_type_map = {
                PhysicalQubit(0, 0, "computation"): "computation",
                PhysicalQubit(1, 0, "computation"): "computation",
            }

        def get_comm_pair_options(self, qubit_a, qubit_b):
            comm_pair = (
                PhysicalQubit(0, 0, "communication"),
                PhysicalQubit(1, 0, "communication"),
            )
            return [
                (
                    3,
                    comm_pair,
                    (
                        [qubit_a, comm_pair[0]],
                        [
                            qubit_b,
                            PhysicalQubit(qubit_b.qpu_id, 1, "computation"),
                            PhysicalQubit(qubit_b.qpu_id, 2, "computation"),
                            comm_pair[1],
                        ],
                    ),
                )
            ]

    qasm_path = tmp_path / "remote_then_local.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\ncx q[0], q[1];\nh q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    remote_statement_ids = {circuit.mono.ops[0].statement_id}

    distributed = _build_distributed(
        circuit,
        remote_statement_ids=remote_statement_ids,
        swaps_schedule=[],
        windows=[circuit.mono.ops],
        schedule=[{QPU(id=0): {0}, QPU(id=1): {1}}],
        comp_qubits_per_qpu=[3, 3],
        comm_qubits_per_qpu=[1, 1],
        network=_MultiHopNetwork(),
    )

    local_h = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate) and statement.name == "h"
    ]

    assert len(local_h) == 1
    assert local_h[0].qubits == [CircuitQubit("q1", 2)]


def test_distributed_dag_remote_gate_rejects_comm_data_operands(
    tmp_path: Path,
) -> None:
    class _FallbackNetwork:
        def __init__(self) -> None:
            self.qubit_type_map = {
                PhysicalQubit(0, 0, "computation"): "computation",
                PhysicalQubit(1, 0, "computation"): "computation",
            }

        def get_comm_pair_options(self, qubit_a, qubit_b):
            bad_comm_pair = (
                PhysicalQubit(0, 1, "communication"),
                PhysicalQubit(1, 0, "communication"),
            )
            bad_path_a = [
                qubit_a,
                PhysicalQubit(0, 0, "communication"),
                bad_comm_pair[0],
            ]
            bad_path_b = [
                qubit_b,
                PhysicalQubit(1, 1, "computation"),
                bad_comm_pair[1],
            ]

            good_comm_pair = (
                PhysicalQubit(0, 2, "communication"),
                PhysicalQubit(1, 2, "communication"),
            )
            good_path_a = [
                qubit_a,
                PhysicalQubit(0, 1, "computation"),
                good_comm_pair[0],
            ]
            good_path_b = [
                qubit_b,
                PhysicalQubit(1, 1, "computation"),
                good_comm_pair[1],
            ]
            return [
                (2, bad_comm_pair, (bad_path_a, bad_path_b)),
                (2, good_comm_pair, (good_path_a, good_path_b)),
            ]

    qasm_path = tmp_path / "single_remote.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\ncp(pi/8) q[0], q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    remote_statement_ids = {circuit.mono.ops[0].statement_id}
    schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]
    windows = [circuit.mono.ops]

    distributed = _build_distributed(
        circuit,
        remote_statement_ids=remote_statement_ids,
        swaps_schedule=[],
        windows=windows,
        schedule=schedule,
        comp_qubits_per_qpu=[3, 3],
        comm_qubits_per_qpu=[3, 3],
        network=_FallbackNetwork(),
    )

    remote_gates = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate)
        and statement.name == "rcp"
    ]
    assert len(remote_gates) == 1
    assert all(
        qubit.register_name.startswith("q")
        for qubit in remote_gates[0].qubits[:2]
    )


def test_distributed_dag_remote_cry_is_rewritten_to_rcry(
    tmp_path: Path,
) -> None:
    class _CryNetwork:
        def __init__(self) -> None:
            self.qubit_type_map = {
                PhysicalQubit(0, 0, "computation"): "computation",
                PhysicalQubit(1, 0, "computation"): "computation",
            }

        def get_comm_pair_options(self, qubit_a, qubit_b):
            comm_pair = (
                PhysicalQubit(0, 0, "communication"),
                PhysicalQubit(1, 0, "communication"),
            )
            return [
                (
                    0,
                    comm_pair,
                    ([qubit_a, comm_pair[0]], [qubit_b, comm_pair[1]]),
                )
            ]

    qasm_path = tmp_path / "single_remote_cry.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\ncry(pi/8) q[0], q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    remote_statement_ids = {circuit.mono.ops[0].statement_id}
    schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]
    windows = [circuit.mono.ops]

    distributed = _build_distributed(
        circuit,
        remote_statement_ids=remote_statement_ids,
        swaps_schedule=[],
        windows=windows,
        schedule=schedule,
        comp_qubits_per_qpu=[1, 1],
        comm_qubits_per_qpu=[1, 1],
        network=_CryNetwork(),
    )

    remote_gates = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate)
        and statement.name == "rcry"
    ]
    assert len(remote_gates) == 1
    assert len(remote_gates[0].qubits) == 4
    assert remote_gates[0].qubits[:2] == [
        CircuitQubit("q0", 0),
        CircuitQubit("q1", 0),
    ]


def test_distributed_dag_unsupported_remote_gate_raises_direct_error(
    tmp_path: Path,
) -> None:
    class _UnsupportedGateNetwork:
        def __init__(self) -> None:
            self.qubit_type_map = {
                PhysicalQubit(0, 0, "computation"): "computation",
                PhysicalQubit(1, 0, "computation"): "computation",
            }

        def get_comm_pair_options(self, qubit_a, qubit_b):
            comm_pair = (
                PhysicalQubit(0, 0, "communication"),
                PhysicalQubit(1, 0, "communication"),
            )
            return [
                (
                    0,
                    comm_pair,
                    ([qubit_a, comm_pair[0]], [qubit_b, comm_pair[1]]),
                )
            ]

        def get_qpu_route(self, source_qpu_id, target_qpu_id):
            return [source_qpu_id, target_qpu_id]

    qasm_path = tmp_path / "single_remote_unsupported.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\ncy q[0], q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    remote_statement_ids = {circuit.mono.ops[0].statement_id}
    schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]
    windows = [circuit.mono.ops]

    with pytest.raises(
        ValueError,
        match="Unsupported remote two-qubit gate 'cy'",
    ):
        _build_distributed(
            circuit,
            remote_statement_ids=remote_statement_ids,
            swaps_schedule=[],
            windows=windows,
            schedule=schedule,
            comp_qubits_per_qpu=[1, 1],
            comm_qubits_per_qpu=[1, 1],
            network=_UnsupportedGateNetwork(),
        )


def test_distributed_dag_routes_remote_gate_through_intermediary_qpu(
    tmp_path: Path,
    simple1_network_path: Path,
) -> None:
    network_path = simple1_network_path.parent / "nonuniform_1.json"
    network = NetworkGraph(str(network_path))

    qasm_path = tmp_path / "single_remote.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\ncx q[0], q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    remote_statement_ids = {circuit.mono.ops[0].statement_id}
    schedule = [{QPU(id=1): {0}, QPU(id=2): set(), QPU(id=3): {1}}]
    windows = [circuit.mono.ops]

    distributed = _build_distributed(
        circuit,
        remote_statement_ids=remote_statement_ids,
        swaps_schedule=[],
        windows=windows,
        schedule=schedule,
        comp_qubits_per_qpu=network.comp_qubits_per_qpu(),
        comm_qubits_per_qpu=network.comm_qubits_per_qpu(),
        network=network,
    )

    routed_rswaps = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate)
        and statement.name == "rswap"
    ]
    routed_remote_gates = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate)
        and statement.name == "rcx"
    ]

    assert len(routed_rswaps) == 1
    assert all(len(statement.qubits) == 6 for statement in routed_rswaps)
    assert len(routed_remote_gates) == 1
    assert len(routed_remote_gates[0].qubits) == 4


def test_distributed_dag_tracks_persistent_routed_remote_gate_hops(
    tmp_path: Path,
    simple1_network_path: Path,
) -> None:
    network_path = simple1_network_path.parent / "nonuniform_1.json"
    network = NetworkGraph(str(network_path))

    qasm_path = tmp_path / "routed_remote_then_local.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\ncx q[0], q[1];\nh q[0];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    remote_statement_ids = {circuit.mono.ops[0].statement_id}

    distributed = _build_distributed(
        circuit,
        remote_statement_ids=remote_statement_ids,
        swaps_schedule=[],
        windows=[circuit.mono.ops],
        schedule=[{QPU(id=1): {0}, QPU(id=2): set(), QPU(id=3): {1}}],
        comp_qubits_per_qpu=network.comp_qubits_per_qpu(),
        comm_qubits_per_qpu=network.comm_qubits_per_qpu(),
        network=network,
    )

    local_h = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate) and statement.name == "h"
    ]

    assert len(local_h) == 1
    assert local_h[0].qubits == [CircuitQubit("q2", 0)]


def test_distributed_dag_remote_swaps_require_network(
    tmp_path: Path,
) -> None:
    qasm_path = tmp_path / "two_ops.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\nh q[0];\nx q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    schedule = [{qpu0: {0}, qpu1: {1}}, {qpu0: {0}, qpu1: {1}}]
    windows = [circuit.mono.ops[:1], circuit.mono.ops[1:]]
    swaps_schedule = [
        [SwapOp(q0=0, q1=1, pos0=(0, 0), pos1=(1, 0))],
    ]

    with pytest.raises(
        ValueError,
        match="Network graph is required to build distributed circuits",
    ):
        _build_distributed(
            circuit,
            remote_statement_ids=set(),
            swaps_schedule=swaps_schedule,
            windows=windows,
            schedule=schedule,
            comp_qubits_per_qpu=[1, 1],
            comm_qubits_per_qpu=[2, 2],
            network=None,
        )


def test_distributed_dag_remote_swap_uses_two_disjoint_comm_pairs(
    tmp_path: Path,
) -> None:
    class _RswapNetwork:
        def __init__(self) -> None:
            self.qubit_type_map = {
                PhysicalQubit(0, 0, "computation"): "computation",
                PhysicalQubit(1, 0, "computation"): "computation",
            }

        def get_comm_pair_options(self, qubit_a, qubit_b):
            pair_1 = (
                PhysicalQubit(qubit_a.qpu_id, 0, "communication"),
                PhysicalQubit(qubit_b.qpu_id, 0, "communication"),
            )
            pair_2 = (
                PhysicalQubit(qubit_a.qpu_id, 1, "communication"),
                PhysicalQubit(qubit_b.qpu_id, 1, "communication"),
            )
            return [
                (0, pair_1, ([qubit_a, pair_1[0]], [qubit_b, pair_1[1]])),
                (1, pair_2, ([qubit_a, pair_2[0]], [qubit_b, pair_2[1]])),
            ]

    qasm_path = tmp_path / "two_ops.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\nh q[0];\nx q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    schedule = [{qpu0: {0}, qpu1: {1}}, {qpu0: {0}, qpu1: {1}}]
    windows = [circuit.mono.ops[:1], circuit.mono.ops[1:]]
    swaps_schedule = [
        [SwapOp(q0=0, q1=1, pos0=(0, 0), pos1=(1, 0))],
    ]
    distributed = _build_distributed(
        circuit,
        remote_statement_ids=set(),
        swaps_schedule=swaps_schedule,
        windows=windows,
        schedule=schedule,
        comp_qubits_per_qpu=[1, 1],
        comm_qubits_per_qpu=[2, 2],
        network=_RswapNetwork(),
    )

    rswaps = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate)
        and statement.name == "rswap"
    ]
    quantum_gate_names = [
        statement.name
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate)
    ]
    # A remote swap is teleportation-based: it is emitted standalone, with
    # no surrounding catent / catdisent.
    assert quantum_gate_names == ["h", "rswap", "x"]
    assert len(rswaps) == 1
    assert rswaps[0].qubits == [
        CircuitQubit("q0", 0),
        CircuitQubit("q1", 0),
        CircuitQubit("c0", 0),
        CircuitQubit("c1", 0),
        CircuitQubit("c0", 1),
        CircuitQubit("c1", 1),
    ]
    output = io.StringIO()
    openqasm3.dump(distributed.program, output)
    dumped_qasm = output.getvalue()
    assert "rswap q0[0], q1[0], c0[0], c1[0], c0[1], c1[1];" in dumped_qasm
    assert "catent" not in dumped_qasm
    assert "catdisent" not in dumped_qasm

    deferred = _build_distributed(
        circuit,
        remote_statement_ids=set(),
        swaps_schedule=swaps_schedule,
        windows=windows,
        schedule=schedule,
        comp_qubits_per_qpu=[1, 1],
        comm_qubits_per_qpu=[2, 2],
        network=_RswapNetwork(),
        ebit_assignment=False,
    )
    rswap_op = next(op for op in deferred.ops if op.name == "rswap")
    assert deferred.ebit_candidates_by_op_id is not None
    rswap_candidates = deferred.ebit_candidates_by_op_id[rswap_op.op_id]
    assert rswap_candidates
    assert all(len(candidate) == 2 for candidate in rswap_candidates)


def test_distributed_dag_routes_nonadjacent_partition_swap(
    tmp_path: Path,
) -> None:
    class _LineRoutingSwapNetwork:
        def __init__(self) -> None:
            self.qubit_type_map = {
                PhysicalQubit(0, 0, "computation"): "computation",
                PhysicalQubit(1, 0, "computation"): "computation",
                PhysicalQubit(2, 0, "computation"): "computation",
            }

        def _remote_comm_pair_counts(self) -> dict[tuple[int, int], int]:
            return {(0, 1): 2, (1, 2): 2}

        def _shortest_qpu_path_with_min_pairs(
            self,
            source_qpu_id: int,
            target_qpu_id: int,
            min_pairs: int,
            pair_counts: dict[tuple[int, int], int],
        ) -> list[int]:
            if source_qpu_id == target_qpu_id:
                return [source_qpu_id]
            if min_pairs > 2:
                raise ValueError(
                    "No QPU path found with required e-bit pairs."
                )
            if (
                source_qpu_id,
                target_qpu_id,
            ) in {(0, 2), (2, 0)} and pair_counts.get((1, 2), 0) >= 2:
                return [source_qpu_id, 1, target_qpu_id]
            if (
                pair_counts.get(
                    (
                        min(source_qpu_id, target_qpu_id),
                        max(source_qpu_id, target_qpu_id),
                    ),
                    0,
                )
                >= min_pairs
            ):
                return [source_qpu_id, target_qpu_id]
            raise ValueError("No QPU path found with required e-bit pairs.")

        def get_comm_pair_options(self, qubit_a, qubit_b):
            pair_key = tuple(sorted((qubit_a.qpu_id, qubit_b.qpu_id)))
            if pair_key not in {(0, 1), (1, 2)}:
                raise ValueError(
                    "No communication pairs found to connect "
                    f"{qubit_a!r} and {qubit_b!r}."
                )
            pair_1 = (
                PhysicalQubit(qubit_a.qpu_id, 0, "communication"),
                PhysicalQubit(qubit_b.qpu_id, 0, "communication"),
            )
            pair_2 = (
                PhysicalQubit(qubit_a.qpu_id, 1, "communication"),
                PhysicalQubit(qubit_b.qpu_id, 1, "communication"),
            )
            return [
                (0, pair_1, ([qubit_a, pair_1[0]], [qubit_b, pair_1[1]])),
                (0, pair_2, ([qubit_a, pair_2[0]], [qubit_b, pair_2[1]])),
            ]

    qasm_path = tmp_path / "two_ops.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[3] q;\nh q[0];\nx q[2];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    schedule = [
        {QPU(id=0): {0}, QPU(id=1): {1}, QPU(id=2): {2}},
        {QPU(id=0): {2}, QPU(id=1): {1}, QPU(id=2): {0}},
    ]
    windows = [circuit.mono.ops[:1], circuit.mono.ops[1:]]
    swaps_schedule = [
        [SwapOp(q0=0, q1=2, pos0=(0, 0), pos1=(2, 0))],
    ]
    distributed = _build_distributed(
        circuit,
        remote_statement_ids=set(),
        swaps_schedule=swaps_schedule,
        windows=windows,
        schedule=schedule,
        comp_qubits_per_qpu=[1, 1, 1],
        comm_qubits_per_qpu=[2, 2, 2],
        network=_LineRoutingSwapNetwork(),
    )

    rswaps = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate)
        and statement.name == "rswap"
    ]
    catents = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate)
        and statement.name == "catent"
    ]
    catdisents = [
        statement
        for statement in distributed.statements
        if isinstance(statement, CleanedQuantumGate)
        and statement.name == "catdisent"
    ]
    assert len(rswaps) == 3
    # Routed remote swaps are emitted standalone, without cat-entanglement.
    assert catents == []
    assert catdisents == []
    assert [
        (s.qubits[0].register_name, s.qubits[1].register_name) for s in rswaps
    ] == [
        ("q0", "q1"),
        ("q1", "q2"),
        ("q0", "q1"),
    ]


def test_distributed_dag_remote_swap_requires_two_disjoint_ebit_pairs(
    tmp_path: Path,
) -> None:
    class _SinglePairRswapNetwork:
        def __init__(self) -> None:
            self.qubit_type_map = {
                PhysicalQubit(0, 0, "computation"): "computation",
                PhysicalQubit(1, 0, "computation"): "computation",
            }

        def get_comm_pair_options(self, qubit_a, qubit_b):
            pair_1 = (
                PhysicalQubit(qubit_a.qpu_id, 0, "communication"),
                PhysicalQubit(qubit_b.qpu_id, 0, "communication"),
            )
            return [
                (0, pair_1, ([qubit_a, pair_1[0]], [qubit_b, pair_1[1]])),
            ]

    qasm_path = tmp_path / "two_ops.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\nh q[0];\nx q[1];\n",
        encoding="utf-8",
    )
    circuit = _build_memq_circuit(qasm_path)
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    schedule = [{qpu0: {0}, qpu1: {1}}, {qpu0: {0}, qpu1: {1}}]
    windows = [circuit.mono.ops[:1], circuit.mono.ops[1:]]
    swaps_schedule = [
        [SwapOp(q0=0, q1=1, pos0=(0, 0), pos1=(1, 0))],
    ]

    with pytest.raises(
        ValueError,
        match="State teleportation not supported - currently requires "
        "2 e-bit pairs.",
    ):
        _build_distributed(
            circuit,
            remote_statement_ids=set(),
            swaps_schedule=swaps_schedule,
            windows=windows,
            schedule=schedule,
            comp_qubits_per_qpu=[1, 1],
            comm_qubits_per_qpu=[2, 2],
            network=_SinglePairRswapNetwork(),
        )


def _source_swap_circuit(tmp_path: Path) -> Circuit:
    qasm_path = tmp_path / "source_swap.qasm"
    qasm_path.write_text(
        'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
        "qubit[2] q;\nswap q[0], q[1];\n",
        encoding="utf-8",
    )
    return _build_memq_circuit(qasm_path)


def test_source_swap_across_qpus_emits_standalone_two_pair_rswap(
    tmp_path: Path,
    eight_comp_four_comm_network_path: Path,
) -> None:
    # A `swap` written in the source circuit whose operands land on different
    # QPUs becomes an rswap, and must be provisioned like every other remote
    # swap: two disjoint e-bit pairs, no cat-entanglement wrapper.
    circuit = _source_swap_circuit(tmp_path)
    network = NetworkGraph(str(eight_comp_four_comm_network_path))
    schedule = [{QPU(id=1): {0}, QPU(id=2): {1}}]

    distributed = _build_distributed(
        circuit,
        remote_statement_ids={circuit.mono.ops[0].statement_id},
        swaps_schedule=[],
        windows=[circuit.mono.ops],
        schedule=schedule,
        comp_qubits_per_qpu=network.comp_qubits_per_qpu(),
        comm_qubits_per_qpu=network.comm_qubits_per_qpu(),
        network=network,
    )

    gate_names = [op.name for op in distributed.ops]
    assert "catent" not in gate_names
    assert "catdisent" not in gate_names

    rswap = next(op for op in distributed.ops if op.name == "rswap")
    ebit_pairs = rswap.ebit_pairs
    assert ebit_pairs is not None
    assert len(ebit_pairs) == 2
    # The two pairs must be disjoint: four distinct communication qubits.
    assert len({qubit for pair in ebit_pairs for qubit in pair}) == 4


def test_source_swap_across_qpus_requires_two_disjoint_ebit_pairs(
    tmp_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    # Only one communication pair links the two QPUs, so the teleportation
    # error must surface rather than a misleading remote-gate routing error.
    circuit = _source_swap_circuit(tmp_path)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]

    with pytest.raises(
        ValueError,
        match="State teleportation not supported - currently requires "
        "2 e-bit pairs.",
    ):
        _build_distributed(
            circuit,
            remote_statement_ids={circuit.mono.ops[0].statement_id},
            swaps_schedule=[],
            windows=[circuit.mono.ops],
            schedule=schedule,
            comp_qubits_per_qpu=network.comp_qubits_per_qpu(),
            comm_qubits_per_qpu=network.comm_qubits_per_qpu(),
            network=network,
        )
