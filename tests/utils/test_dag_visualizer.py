# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import networkx as nx
import pytest

from memq_dqc.circuit import Circuit
from memq_dqc.visualization import (
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
