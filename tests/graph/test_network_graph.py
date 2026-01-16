# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

import networkx as nx

from memq_dqc.graph.network_graph import build_network_graph


def test_build_network_graph_returns_graph(simple1_network_path: Path) -> None:
    graph, qubit_type_map = build_network_graph(str(simple1_network_path))

    assert isinstance(graph, nx.Graph)
    assert isinstance(qubit_type_map, dict)


def test_build_network_graph_structure(
    simple1_network_path: Path,
) -> None:
    graph, _ = build_network_graph(str(simple1_network_path))

    # The simple1.json network has 8 qubits
    assert graph.number_of_nodes() == 8

    # The simple1.json network has 10 connections (edges)
    assert graph.number_of_edges() == 10


def test_display_network_graph(simple1_network_path: Path) -> None:
    graph, _ = build_network_graph(str(simple1_network_path))

    # Just ensure that the function runs without error
    nx_graph = graph
    try:
        from memq_dqc.graph.network_graph import display_network_graph

        display_network_graph(nx_graph)
    except Exception as e:
        raise AssertionError(
            "Displaying network graph raised an exception"
        ) from e
