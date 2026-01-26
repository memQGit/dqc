# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import pytest
from openqasm3 import ast

from memq_dqc.circuit.dag import CircuitDAG
from memq_dqc.utils import (
    count_total_qubits,
    create_subcircuit_graphs,
    extract_qubit_index,
    extract_two_qubit_gates,
    load_qasm_program,
)


@pytest.mark.parametrize(
    "fixture_name",
    [
        "bell_circuit_path",
        "simple1_circuit_path",
    ],
)
def test_load_qasm_program(
    request: pytest.FixtureRequest,
    fixture_name: str,
) -> None:
    qasm_path = request.getfixturevalue(fixture_name)
    program = load_qasm_program(str(qasm_path))
    assert program is not None
    assert hasattr(program, "statements")


def test_load_qasm_program_file_not_found() -> None:
    try:
        load_qasm_program("non_existent_file.qasm")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Expected FileNotFoundError was not raised.")


@pytest.mark.parametrize(
    ("fixture_name", "expected"),
    [
        ("simple1_circuit_path", 6),
    ],
)
def test_count_total_qubits(
    request: pytest.FixtureRequest,
    fixture_name: str,
    expected: int,
) -> None:
    qasm_path = request.getfixturevalue(fixture_name)
    total_qubits = count_total_qubits(str(qasm_path))
    assert total_qubits == expected


@pytest.mark.parametrize(
    "fixture_name",
    [
        "bell_circuit_path",
    ],
)
def test_extract_qubit_index(
    request: pytest.FixtureRequest,
    fixture_name: str,
) -> None:
    qasm_path = request.getfixturevalue(fixture_name)
    program = load_qasm_program(str(qasm_path))
    for statement in program.statements:
        if (
            isinstance(statement, ast.QuantumGate)
            and len(statement.qubits) == 2
        ):
            i, j = sorted(extract_qubit_index(q) for q in statement.qubits)
            result = sorted((i, j))
    if result is None:
        raise AssertionError("No QuantumGate statement found in the program.")
    assert result == [0, 1]


@pytest.mark.parametrize(
    ("fixture_name", "expected_counts"),
    [
        ("bell_circuit_path", {(0, 1): 1}),
        (
            "simple1_circuit_path",
            {
                (0, 1): 2,
                (1, 2): 1,
                (2, 3): 1,
                (3, 4): 2,
                (4, 5): 1,
                (0, 5): 1,
            },
        ),
    ],
)
def test_extract_two_qubit_gates(
    request: pytest.FixtureRequest,
    fixture_name: str,
    expected_counts: dict[tuple[int, int], int],
) -> None:
    qasm_path = request.getfixturevalue(fixture_name)
    gate_counts = extract_two_qubit_gates(str(qasm_path))
    assert gate_counts == expected_counts


@pytest.mark.parametrize(
    "fixture_name",
    [
        "simple1_circuit_path",
    ],
)
def _graph_edges(graph) -> dict[tuple[int, int], int]:
    edges: dict[tuple[int, int], int] = {}
    for u, v, data in graph.edges(data=True):
        key = (u, v) if u <= v else (v, u)
        edges[key] = int(data.get("weight", 1))
    return edges


@pytest.mark.parametrize(
    (
        "fixture_name",
        "num_subcircuits",
        "partition",
        "expected_graphs",
    ),
    [
        (
            "bell_circuit_path",
            1,
            [{0}, {1}],
            # Manually computed expected subcircuit graphs for partition above
            [{(0, 1): 1}],
        ),
        (
            "simple1_circuit_path",
            4,
            [{0, 1, 2}, {3, 4, 5}],
            # Manually computed expected subcircuit graphs for partition above
            [
                {(0, 1): 2, (1, 2): 2},
                {(0, 1): 2, (2, 3): 1, (3, 4): 2},
                {(4, 5): 2},
                {(3, 4): 2, (0, 5): 1},
            ],
        ),
    ],
)
def test_create_subcircuit_graphs(
    request: pytest.FixtureRequest,
    fixture_name: str,
    num_subcircuits: int,
    partition: list[set[int]],
    expected_graphs: list[dict[tuple[int, int], int]],
) -> None:
    qasm_path = request.getfixturevalue(fixture_name)
    program = load_qasm_program(str(qasm_path))
    dag = CircuitDAG(program)
    dags = create_subcircuit_graphs(
        dag,
        num_subcircuits=num_subcircuits,
        partition=partition,
    )
    assert len(dags) == len(expected_graphs)
    for graph, expected in zip(dags, expected_graphs, strict=True):
        assert _graph_edges(graph) == expected
        expected_nodes = {n for edge in expected for n in edge}
        assert set(graph.nodes) == expected_nodes
