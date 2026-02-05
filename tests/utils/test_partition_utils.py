# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import networkx as nx

from memq_dqc.partition.utils import partition_cost


def test_partition_cost_sums_crossing_edges() -> None:
    graph = nx.Graph()
    graph.add_edge(0, 1, weight=2.5)
    graph.add_edge(1, 2, weight=1.0)
    graph.add_edge(2, 3)
    graph.add_edge(0, 3, weight=4.0)
    partition = [{0, 1}, {2, 3}]

    cost = partition_cost(graph, partition)

    assert cost == 5.0
