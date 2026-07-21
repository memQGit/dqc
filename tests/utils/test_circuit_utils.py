# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from typing import Any, cast

import pytest
from openqasm3 import ast

from xdqc.circuit import Circuit
from xdqc.network import NetworkGraph
from xdqc.partition.partitioner import QPU
from xdqc.preprocessing.qasm import (
    count_total_qubits,
    extract_qubit_index,
    extract_two_qubit_gates,
)
from xdqc.preprocessing.qasm.io import load_qasm_program
from xdqc.utils import (
    count_two_qubit_pairs,
    create_initial_subcircuit_graph,
    distribute,
    get_windows,
    movement_cost,
    qubit_partition_map,
)
from xdqc.utils.circuit_utils import build_window_interaction_graph


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


def test_load_qasm_program_multi_reg(
    two_reg_circuit_path,
) -> None:
    try:
        load_qasm_program(str(two_reg_circuit_path))
    except NotImplementedError:
        pass
    else:
        raise AssertionError("Expected NotImplementedError was not raised.")


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


def test_count_total_qubits_from_program(
    simple1_circuit_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))

    assert count_total_qubits(program) == 6


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
    result = None
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


def test_extract_two_qubit_gates_from_program(
    bell_circuit_path,
) -> None:
    program = load_qasm_program(str(bell_circuit_path))

    assert extract_two_qubit_gates(program) == {(0, 1): 1}


def _graph_edges(graph) -> dict[tuple[int, int], int]:
    edges: dict[tuple[int, int], int] = {}
    for u, v, data in graph.edges(data=True):
        key = (u, v) if u <= v else (v, u)
        edges[key] = int(data.get("weight", 1))
    return edges


def test_count_two_qubit_pairs() -> None:
    pairs = [(1, 0), (0, 1), (2, 3)]
    counts = count_two_qubit_pairs(pairs)
    assert counts == {(0, 1): 2, (2, 3): 1}


def test_create_initial_subcircuit_graph(
    simple1_circuit_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    circuit = Circuit(program)
    windows = get_windows(circuit, window_length=2)
    graph = create_initial_subcircuit_graph(6, windows[0])

    assert set(graph.nodes()) == set(range(6))
    assert _graph_edges(graph) == {(0, 1): 1, (1, 2): 1}


def test_build_window_interaction_graph_weights(
    simple1_circuit_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    circuit = Circuit(program)
    windows = get_windows(circuit, window_length=2)
    partition_map = {0: 0, 1: 0, 2: 1, 3: 1, 4: 1, 5: 1}

    graph, active_qubits = build_window_interaction_graph(
        windows[0], partition_map
    )

    assert active_qubits == {0, 1, 2}
    assert set(graph.nodes()) == {0, 1, 2}
    assert _graph_edges(graph) == {(0, 1): 2, (1, 2): 1}


def test_build_window_interaction_graph_empty() -> None:
    graph, active_qubits = build_window_interaction_graph([], {})

    assert active_qubits == set()
    assert list(graph.nodes()) == []
    assert list(graph.edges()) == []


def test_movement_cost() -> None:
    old_partition = [{0, 1}, {2, 3}]
    new_partition = [{0, 2}, {1, 3}]

    assert movement_cost(new_partition, old_partition) == 2.0


def test_movement_cost_uses_network_route_cost(simple1_network_path) -> None:
    network = NetworkGraph(str(simple1_network_path))
    old_partition = [{0}, {1}]
    new_partition = [{0, 1}, set()]

    assert (
        movement_cost(
            new_partition,
            old_partition,
            network=network,
            qpu_ids=[1, 2],
        )
        == 0.0
    )


def test_movement_cost_returns_inf_for_unrouteable_swap(
    three_comp_one_comm_x2_network_path,
) -> None:
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    old_partition = [{0}, {1}]
    new_partition = [{0, 1}, set()]

    assert movement_cost(
        new_partition,
        old_partition,
        network=network,
        qpu_ids=[0, 1],
    ) == float("inf")


def test_movement_cost_rejects_qpu_keyed_partitions() -> None:
    old_partition = cast(Any, {QPU(id=1): {0}, QPU(id=3): {1}})
    new_partition = cast(Any, {QPU(id=1): {1}, QPU(id=3): {0}})

    with pytest.raises(TypeError, match="list-based partitions"):
        movement_cost(new_partition, old_partition)


def test_qubit_partition_map() -> None:
    partition = [{0, 2}, {1}]

    assert qubit_partition_map(partition) == {0: 0, 2: 0, 1: 1}


def test_distribute() -> None:
    assert distribute(10, 3) == [4, 3, 3]
    assert distribute(2, 4) == [1, 1, 0, 0]


def test_get_windows(
    simple1_circuit_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    circuit = Circuit(program)

    windows = get_windows(circuit, window_length=3)

    assert [len(window) for window in windows] == [3, 3, 2]
    assert sum(len(window) for window in windows) == 8
