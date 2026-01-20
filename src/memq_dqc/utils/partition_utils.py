# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Utility functions for graph partitioning."""

from __future__ import annotations

import networkx as nx


def partition_cost(graph: nx.Graph, partition: dict[int, set]) -> float:
    """Sum edge weights for edges crossing partition boundaries.

    Args:
        graph: The input graph.
        partition: A mapping from partition ID to set of nodes in that partition.

    Returns:
        The total weight of edges that connect nodes in different partitions.
    """
    # Build a node->group lookup for quick checking
    group_assignment = {}
    for group_id, nodes in partition.items():
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
        The weight of the edge.

    Raises:
        ValueError: If no edge exists between ``u`` and ``v``.
    """
    if not graph.has_edge(u, v):
        raise ValueError(f"No edge exists between nodes {u} and {v}")

    return graph[u][v].get("weight", 1.0)
