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
from typing import TYPE_CHECKING

import networkx as nx

from memq_dqc.utils.common import qubit_partition_map as _qubit_partition_map

if TYPE_CHECKING:
    from memq_dqc.circuit import Circuit
    from memq_dqc.circuit.op import Op
    from memq_dqc.network import NetworkGraph
    from memq_dqc.partition.partitioner import QPU


# PUBLIC METHODS


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
    two_qubit_counts = count_two_qubit_pairs(
        (op.qubit_indices[0], op.qubit_indices[1])
        for op in window
        if op.is_two_qubit
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
    # TODO: abstract hardcoded weights to user controls
    two_qubit_counts = count_two_qubit_pairs(
        (op.qubit_indices[0], op.qubit_indices[1])
        for op in ops
        if op.is_two_qubit
    )
    active_qubits = {q for pair in two_qubit_counts.keys() for q in pair}

    graph = nx.Graph()
    for q in active_qubits:
        graph.add_node(q)

    for (i, j), count in two_qubit_counts.items():
        weight = count
        part_i = partition_map.get(i)
        part_j = partition_map.get(j)
        # TODO: figure out why even if this is nearly infinity we still dont get static

        if part_i == part_j:
            weight *= 2.0
        graph.add_edge(i, j, weight=weight)

    return graph, active_qubits


def movement_cost(
    new_partition: list[set[int]],
    old_partition: list[set[int]],
    *,
    network: NetworkGraph | None = None,
    qpu_ids: list[int] | None = None,
) -> float:
    """Calculate the cost of moving qubits between partitions.

    Args:
        new_partition: The updated partitioning of qubits.
        old_partition: The previous partitioning of qubits.
        network: Optional network used to weight inter-QPU movement.
        qpu_ids: Optional QPU IDs ordered by partition index.

    Returns:
        The movement cost.

    Raises:
        TypeError: If either partition is provided as a QPU-keyed mapping.
        ValueError: If only one of ``network`` or ``qpu_ids`` is provided.
    """
    if isinstance(new_partition, dict) or isinstance(old_partition, dict):
        raise TypeError(
            "movement_cost requires list-based partitions; "
            "QPU-keyed schedule mappings are not supported."
        )

    if (network is None) != (qpu_ids is None):
        raise ValueError(
            "movement_cost requires both network and qpu_ids when using "
            "topology-aware costs."
        )

    old_qubit_to_part = qubit_partition_map(old_partition)
    new_qubit_to_part = qubit_partition_map(new_partition)

    total_cost = 0.0
    for qubit, old_part in old_qubit_to_part.items():
        new_part = new_qubit_to_part.get(qubit)
        if new_part is None or new_part == old_part:
            continue
        if network is None or qpu_ids is None:
            total_cost += 1.0
        else:
            try:
                total_cost += float(
                    network.remote_swap_ebit_cost(
                        qpu_ids[old_part],
                        qpu_ids[new_part],
                    )
                )
            except ValueError:
                return float("inf")

    return total_cost


def qubit_partition_map(
    partition: list[set[int]] | dict[QPU, set[int]],
) -> dict[int, int]:
    """Create a mapping from qubit index to partition index.

    Args:
        partition: Partitioning of qubits by group.

    Returns:
        The partition index for each qubit index.
    """
    return _qubit_partition_map(partition)


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
    circuit: Circuit,
    window_length: int,
) -> list[list[Op]]:
    """Generate subcircuit windows with a target two-qubit gate count.

    Args:
        circuit: Circuit providing operations in program order.
        window_length: Number of two-qubit operations per window.

    Returns:
        Operation windows in circuit order.
    """
    ops = circuit.mono.ops
    windows = []
    current_window = []
    num_two_qubit_ops = 0

    for op in ops:
        current_window.append(op)
        if len(op.qubits) == 2:
            num_two_qubit_ops += 1
        if num_two_qubit_ops == window_length:
            windows.append(current_window)
            current_window = []
            num_two_qubit_ops = 0

    # Add any remaining operations as the last window
    if current_window:
        windows.append(current_window)

    return windows


# PRIVATE METHODS


__all__ = [
    "build_window_interaction_graph",
    "count_two_qubit_pairs",
    "create_initial_subcircuit_graph",
    "distribute",
    "get_windows",
    "movement_cost",
    "qubit_partition_map",
]
