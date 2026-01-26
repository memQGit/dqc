# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Utility functions used for OpenQASM circuits throughout the library."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from pathlib import Path
from typing import TYPE_CHECKING

import networkx as nx
import openqasm3
from openqasm3 import ast

if TYPE_CHECKING:
    from memq_dqc.circuit import CircuitDAG


def load_qasm_program(filename: str) -> ast.Program:
    """Load an OpenQASM 3 program from a file.

    Args:
        filename (str): Path to the OpenQASM 3 file.

    Returns:
        ast.Program: The parsed OpenQASM 3 program.
    """
    qasm_path = Path(filename)
    if not qasm_path.is_file():
        raise FileNotFoundError(f"File not found: {filename}")
    qasm_source = qasm_path.read_text(encoding="utf-8")
    program = openqasm3.parser.parse(qasm_source)

    return program


def count_total_qubits(qasm_filename: str) -> int:
    """Count the total number of qubits in an OpenQASM 3 program.

    Args:
        qasm_filename (str): The path to the OpenQASM 3 file.

    Returns:
        int: The total number of qubits.
    """
    qasm_program = load_qasm_program(qasm_filename)
    total = 0
    for stmt in qasm_program.statements:
        if isinstance(stmt, ast.QubitDeclaration):
            total += stmt.size.value

    return total


def extract_qubit_index(index_statement: ast.IndexedIdentifier) -> int:
    """Extract the qubit index from an IndexedIdentifier.

    Args:
        index_statement (ast.IndexedIdentifier): The IndexedIdentifier.

    Returns:
        int: The qubit index.
    """
    if not index_statement.indices:
        raise ValueError("No indices found in the IndexedIdentifier.")

    return int(index_statement.indices[0][0].value)


def _count_two_qubit_pairs(
    pairs: Iterable[tuple[int, int]],
) -> Counter[tuple[int, int]]:
    counts: Counter[tuple[int, int]] = Counter()
    for i, j in pairs:
        key = (i, j) if i <= j else (j, i)
        counts[key] += 1
    return counts


def extract_two_qubit_gates(qasm_filename: str) -> Counter:
    """Extract two-qubit gates from an OpenQASM 3 program.

    Args:
        qasm_filename (str): The path to the OpenQASM 3 file.

    Returns:
        Counter: A counter of two-qubit gates in the program in the form
                  {(i, j): count}, where (i, j) are the qubit indices.
    """
    qasm_program = load_qasm_program(qasm_filename)
    pairs = (
        (extract_qubit_index(q0), extract_qubit_index(q1))
        for statement in qasm_program.statements
        if isinstance(statement, ast.QuantumGate)
        and len(statement.qubits) == 2
        for q0, q1 in [statement.qubits]
    )
    return _count_two_qubit_pairs(pairs)


def create_subcircuit_graphs(
    dag: CircuitDAG,
    num_subcircuits: int,
    partition: list[set[int]],
) -> list[nx.Graph] | tuple[list[nx.Graph], list[Counter[tuple[int, int]]]]:
    """Create graphs representing subcircuits of a larger circuit.

    These graphs have nodes representing qubits, with edge weights being either
    the number of CNOT gates if both qubits are in the same partition, or twice
    this number if the qubits are in different partitions.

    Args:
        dag (CircuitDAG): The DAG representation of the full circuit.
        num_subcircuits (int): The number of subcircuits to create.
        partition (list[set[int]]): The partitioning of qubits.

    Returns:
        list[nx.Graph]: A list of NetworkX graphs representing the subcircuits.
    """
    depth = dag.depth
    layer_sizes = _distribute(depth, num_subcircuits)
    print(f"Layer sizes for subcircuits: {layer_sizes}")

    partition_map = _qubit_partition_set_to_map(partition)

    subcircuit_graphs: list[nx.Graph] = []

    layer = 0
    for num_layers in layer_sizes:
        end_layer = min(layer + num_layers, depth)
        combined_layers = dag.layers[layer:end_layer]
        ops = [op for layer_ops in combined_layers for op in layer_ops]
        two_qubit_counts = _count_two_qubit_pairs(
            op.qubits for op in ops if len(op.qubits) == 2
        )
        g = nx.Graph()
        for (i, j), count in two_qubit_counts.items():
            weight = count
            part_i = partition_map.get(i)
            part_j = partition_map.get(j)
            if part_i == part_j:
                # Double weight to prefer non-remote gates
                g.add_edge(i, j, weight=(weight * 2))
            else:
                g.add_edge(i, j, weight=weight)
        subcircuit_graphs.append(g)
        layer = end_layer

    return subcircuit_graphs


def _qubit_partition_set_to_map(partition: list[set[int]]) -> dict[int, int]:
    """Given a partitioning of qubits in the form of a list of sets, create a map from qubit index to partition index.

    Args:
        partition (list[set[int]]): The partitioning of qubits.

    Returns:
        dict[int, int]: A mapping from qubit index to partition index.
    """
    qubit_to_partition: dict[int, int] = {}
    for part_idx, qubit_set in enumerate(partition):
        for qubit in qubit_set:
            qubit_to_partition[qubit] = part_idx
    return qubit_to_partition


def _distribute(v: int, n: int) -> list[int]:
    """Distribute v items into n buckets as evenly as possible.

    Args:
        v (int): The number of items to distribute.
        n (int): The number of buckets.

    Returns:
        list[int]: A list of size n, where the i-th element is the number of
            items in the i-th bucket.

    """
    q, r = divmod(v, n)
    return [q + 1 if i < r else q for i in range(n)]
