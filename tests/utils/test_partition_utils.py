# Copyright 2026 memQ Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import networkx as nx

from xdqc.partition.utils import partition_cost


def test_partition_cost_sums_crossing_edges() -> None:
    graph = nx.Graph()
    graph.add_edge(0, 1, weight=2.5)
    graph.add_edge(1, 2, weight=1.0)
    graph.add_edge(2, 3)
    graph.add_edge(0, 3, weight=4.0)
    partition = [{0, 1}, {2, 3}]

    cost = partition_cost(graph, partition)

    assert cost == 5.0
