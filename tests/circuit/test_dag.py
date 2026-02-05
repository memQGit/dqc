# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

import pytest
from qiskit import qasm3
from qiskit.converters import circuit_to_dag
from qiskit.dagcircuit import DAGCircuit, DAGOpNode

from memq_dqc.circuit.dag import CircuitDAG as DAG
from memq_dqc.circuit.dag import DistributedCircuitDAG
from memq_dqc.io.qasm import load_qasm_program


def _build_memq_dag(qasm_path: Path) -> DAG:
    program = load_qasm_program(str(qasm_path))
    return DAG(program)


def _build_qiskit_dag(qasm_path: Path) -> DAGCircuit:
    qasm_source = qasm_path.read_text(encoding="utf-8")
    circuit = qasm3.loads(qasm_source)
    return circuit_to_dag(circuit)


def _qiskit_op_nodes(dag: DAGCircuit) -> list[DAGOpNode]:
    return list(dag.op_nodes())


def _qiskit_op_signatures(
    dag: DAGCircuit,
    nodes: list[DAGOpNode],
) -> list[tuple[str, tuple[int, ...]]]:
    qubit_index = {qubit: idx for idx, qubit in enumerate(dag.qubits)}
    return [
        (node.name, tuple(qubit_index[q] for q in node.qargs))
        for node in nodes
    ]


def _qiskit_edges(
    dag: DAGCircuit,
    nodes: list[DAGOpNode],
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


def _memq_edges(dag: DAG) -> dict[tuple[int, int], set[int]]:
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


def _memq_layers(dag: DAG) -> list[frozenset[tuple[str, tuple[int, ...]]]]:
    return [
        frozenset((op.name, op.qubit_indices) for op in layer)
        for layer in dag.extract_layers()
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
    memq_dag = _build_memq_dag(qasm_path)
    qiskit_dag = _build_qiskit_dag(qasm_path)
    qiskit_nodes = _qiskit_op_nodes(qiskit_dag)

    memq_ops = [(op.name, op.qubit_indices) for op in memq_dag.ops]
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
    dag = _build_memq_dag(qasm_path)
    assert dag.num_two_qubit_gates == expected_two_qubit_gates


def test_distributed_dag_counts_remote_gates(
    request: pytest.FixtureRequest,
) -> None:
    qasm_path = request.getfixturevalue("bell_circuit_path")
    base_dag = _build_memq_dag(qasm_path)
    remote_statement_ids = {
        op.statement_id for op in base_dag.ops if op.is_two_qubit
    }

    dist_dag = DistributedCircuitDAG(base_dag, remote_statement_ids)

    assert dist_dag.num_remote_gates == len(remote_statement_ids)
    assert dist_dag.num_remote_gates == sum(
        1 for op in dist_dag.ops if op.name.startswith("r")
    )
