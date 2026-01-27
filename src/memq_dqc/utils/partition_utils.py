# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Utility functions for graph partitioning."""

from __future__ import annotations

import networkx as nx


def partition_cost(graph: nx.Graph, partition: list[set[int]]) -> float:
    """Sum edge weights for edges crossing partition boundaries.

    Args:
        graph: The input graph.
        partition: A list of sets, where each set contains the nodes in that partition.

    Returns:
        The total weight of edges that connect nodes in different partitions.
    """
    # Build a node->group lookup for quick checking
    group_assignment = {}
    for group_id, nodes in enumerate(partition):
        for node in nodes:
            group_assignment[node] = group_id

    total = 0.0
    for u, v, weight in graph.edges(data="weight", default=1):
        if group_assignment[u] != group_assignment[v]:
            total += weight

    return total


def get_edge_weight(graph: nx.Graph, u: int, v: int) -> float:
    """Get the weight of an edge, raising if the edge is missing.

    Args:
        graph: The input graph.
        u: The first node of the edge.
        v: The second node of the edge.

    Returns:
        The weight of the edge. If the edge does not exist, returns 0.0.
    """
    if not graph.has_edge(u, v):
        return 0.0
    return graph[u][v].get("weight", 1.0)


def verify_partition_sizes(
    graph: nx.Graph, partition_sizes: list[int]
) -> None:
    """Verify that partition sizes list is valid for the given graph.

    Args:
        graph: The input graph.
        partition_sizes: A list of sizes for each partition.

    Raises:
        ValueError: If the sum of partition sizes does not equal the number of nodes.
    """
    if any(s <= 0 for s in partition_sizes):
        raise ValueError("All partition sizes must be positive.")

    nodes = [int(n) for n in graph.nodes()]
    n_nodes = len(nodes)

    if sum(partition_sizes) < n_nodes:
        raise ValueError(
            f"sum(partition_sizes)={sum(partition_sizes)} must at least equal to"
            f"number of nodes(qubits)={n_nodes}."
        )


def generate_equal_partitions(
    num_partitions: int, num_nodes: int
) -> list[int]:
    """Generate a list of equal partition sizes for the given number of nodes.

    Args:
        num_partitions: The number of partitions to create.
        num_nodes: The total number of nodes to partition.

    Returns:
        A list of partition sizes summing to num_nodes.
    """
    base_size = num_nodes // num_partitions
    remainder = num_nodes % num_partitions
    partition_sizes = [base_size + 1] * remainder + [base_size] * (
        num_partitions - remainder
    )
    return partition_sizes
