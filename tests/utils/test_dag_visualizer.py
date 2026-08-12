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
import pytest

from xdqc.circuit import Circuit
from xdqc.visualization import (
    build_dag_networkx_graph,
    plot_distributed_dag,
)


def test_build_dag_networkx_graph_adds_wire_endpoints(
    bell_circuit_path,
) -> None:
    circuit = Circuit(str(bell_circuit_path))

    graph = build_dag_networkx_graph(circuit.mono.dag)

    assert isinstance(graph, nx.DiGraph)
    labels_by_kind = {
        (data["kind"], data["label"]) for _, data in graph.nodes(data=True)
    }
    assert ("input", "q[0]") in labels_by_kind
    assert ("input", "q[1]") in labels_by_kind
    assert ("output", "q[0]") in labels_by_kind
    assert ("output", "q[1]") in labels_by_kind
    assert ("operation", "h") in labels_by_kind
    assert ("operation", "cx") in labels_by_kind
    assert all(data["label"] for _, _, data in graph.edges(data=True))


def test_plot_distributed_dag_requires_distributed_circuit(
    bell_circuit_path,
) -> None:
    circuit = Circuit(str(bell_circuit_path))

    with pytest.raises(ValueError, match="build_distributed"):
        plot_distributed_dag(circuit)
