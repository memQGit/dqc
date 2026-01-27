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
    from memq_dqc.circuit import CircuitDAG, Op


# PUBLIC METHODS


def load_qasm_program(filename: str) -> ast.Program:
    """Load an OpenQASM 3 program from a file.

    Args:
        filename: Path to the OpenQASM 3 file.

    Returns:
        The parsed OpenQASM 3 program.
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
        qasm_filename: Path to the OpenQASM 3 file.

    Returns:
        The total number of qubits in the program.
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
        index_statement: Indexed identifier to extract from.

    Returns:
        The extracted qubit index.
    """
    if not index_statement.indices:
        raise ValueError("No indices found in the IndexedIdentifier.")

    return int(index_statement.indices[0][0].value)


def count_two_qubit_pairs(
    pairs: Iterable[tuple[int, int]],
) -> Counter[tuple[int, int]]:
    """Count unordered two-qubit pairs.

    Args:
        pairs: Qubit index pairs to count.

    Returns:
        Counts keyed by ordered qubit index pairs.
    """
    counts: Counter[tuple[int, int]] = Counter()
    for i, j in pairs:
        key = (i, j) if i <= j else (j, i)
        counts[key] += 1
    return counts


def extract_two_qubit_gates(qasm_filename: str) -> Counter:
    """Extract two-qubit gates from an OpenQASM 3 program.

    Args:
        qasm_filename: Path to the OpenQASM 3 file.

    Returns:
        Counts of two-qubit gates keyed by qubit index pairs.
    """
    qasm_program = load_qasm_program(qasm_filename)
    pairs = (
        (extract_qubit_index(q0), extract_qubit_index(q1))
        for statement in qasm_program.statements
        if isinstance(statement, ast.QuantumGate)
        and len(statement.qubits) == 2
        for q0, q1 in [statement.qubits]
    )
    return count_two_qubit_pairs(pairs)


def create_initial_subcircuit_graph(
    num_qubits: int, window: list[Op]
) -> nx.Graph:
    """Generate the initial interaction graph for first of n subcircuits.

    This graph is used to generate the initial partitioning of qubits, which
    is then used to create the remaining n-1 subcircuit graphs afterwards.

    Args:
        num_qubits: Total number of qubits in the circuit.
        window: Operations in the first subcircuit window.

    Returns:
        The interaction graph for the first subcircuit window.

    """
    # Compute the layer sizes for each subcircuit to determine first layer
    # depth = dag.depth
    # layer_sizes = distribute(depth, num_subcircuits)
    # start_layer = 0
    # end_layer = layer_sizes[0]

    # # Combine layers to form the first subcircuit
    # combined_layers = dag.layers[start_layer:end_layer]
    # ops = [op for layer_ops in combined_layers for op in layer_ops]

    two_qubit_counts = count_two_qubit_pairs(
        op.qubits for op in window if len(op.qubits) == 2
    )

    # Generate the interaction graph for the first subcircuit
    g = nx.Graph()
    # Add all qubit nodes in subcircuit to include single-qubit gate qubits
    for q in range(num_qubits):
        g.add_node(q)
    for (i, j), count in two_qubit_counts.items():
        g.add_edge(i, j, weight=count)
    return g


def build_window_interaction_graph(
    ops: Iterable[Op],
    partition_map: dict[int, int],
) -> tuple[nx.Graph, set[int]]:
    """Build a weighted interaction graph for a window of operations.

    Args:
        ops: Operations in the window.
        partition_map: Mapping from qubit index to partition index.

    Returns:
        The interaction graph for the window and the active qubits.
    """
    two_qubit_counts = count_two_qubit_pairs(
        op.qubits for op in ops if len(op.qubits) == 2
    )
    active_qubits = {q for pair in two_qubit_counts.keys() for q in pair}

    graph = nx.Graph()
    for q in active_qubits:
        graph.add_node(q)

    for (i, j), count in two_qubit_counts.items():
        weight = count
        part_i = partition_map.get(i)
        part_j = partition_map.get(j)
        if part_i == part_j:
            weight *= 2
        graph.add_edge(i, j, weight=weight)

    return graph, active_qubits


def movement_cost(
    new_partition: list[set[int]],
    old_partition: list[set[int]],
) -> float:
    """Calculate the cost of moving qubits between partitions.

    Args:
        new_partition: The updated partitioning of qubits.
        old_partition: The previous partitioning of qubits.

    Returns:
        The movement cost based on the number of qubits moved.
    """
    old_qubit_to_part = qubit_partition_set_to_map(old_partition)
    new_qubit_to_part = qubit_partition_set_to_map(new_partition)

    moved_qubits = sum(
        1
        for qubit, old_part in old_qubit_to_part.items()
        if new_qubit_to_part.get(qubit) != old_part
    )

    # Cost per moved qubit can be adjusted as needed
    cost_per_moved_qubit = 1.0

    return moved_qubits * cost_per_moved_qubit


def qubit_partition_set_to_map(partition: list[set[int]]) -> dict[int, int]:
    """Create a mapping from qubit index to partition index.

    Args:
        partition: Partitioning of qubits by group.

    Returns:
        The partition index for each qubit index.
    """
    qubit_to_partition: dict[int, int] = {}
    for part_idx, qubit_set in enumerate(partition):
        for qubit in qubit_set:
            qubit_to_partition[qubit] = part_idx
    return qubit_to_partition


def distribute(v: int, n: int) -> list[int]:
    """Distribute v items into n buckets as evenly as possible.

    Args:
        v: The number of items to distribute.
        n: The number of buckets.

    Returns:
        Bucket sizes in order.

    """
    q, r = divmod(v, n)
    return [q + 1 if i < r else q for i in range(n)]


def get_windows(
    dag: CircuitDAG,
    window_size: int,
) -> list[list[Op]]:
    """Generate subcircuit windows with a target two-qubit gate count.

    Args:
        dag: Circuit DAG providing operations in program order.
        window_size: Number of two-qubit operations per window.

    Returns:
        Operation windows in circuit order.
    """
    ops = dag.ops
    windows = []
    current_window = []
    num_two_qubit_ops = 0

    for op in ops:
        current_window.append(op)
        if len(op.qubits) == 2:
            num_two_qubit_ops += 1
        if num_two_qubit_ops == window_size:
            windows.append(current_window)
            current_window = []
            num_two_qubit_ops = 0

    # Add any remaining operations as the last window
    if current_window:
        windows.append(current_window)

    return windows
