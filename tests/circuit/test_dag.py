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

from memq_dqc.circuit.dag import DAG
from memq_dqc.utils.circuit_utils import load_qasm_program


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
        edges[(u, v)] = set(data["qubits"])
    return edges


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

    memq_ops = [(op.name, op.qubits) for op in memq_dag.ops]
    qiskit_ops = _qiskit_op_signatures(qiskit_dag, qiskit_nodes)
    assert memq_ops == qiskit_ops
    assert _memq_edges(memq_dag) == _qiskit_edges(qiskit_dag, qiskit_nodes)
