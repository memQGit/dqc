# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

import networkx as nx
import pytest

from memq_dqc.graph import build_interaction_graph, display_interaction_graph


def test_build_interaction_graph_returns_graph(
    bell_circuit_path: Path,
) -> None:
    graph = build_interaction_graph(str(bell_circuit_path))
    assert isinstance(graph, nx.Graph)


def test_build_interaction_graph_structure_bell(
    bell_circuit_path: Path,
) -> None:
    graph = build_interaction_graph(str(bell_circuit_path))

    # The bell.qasm circuit has 2 qubits
    assert graph.number_of_nodes() == 2

    # The bell.qasm circuit has 1 connection (edge)
    assert graph.number_of_edges() == 1


def test_build_interaction_graph_structure_simple1(
    simple1_circuit_path: Path,
) -> None:
    graph = build_interaction_graph(str(simple1_circuit_path))

    # The simple1.qasm circuit has 6 qubits
    assert graph.number_of_nodes() == 6

    # The simple1.qasm circuit has 6 connections (edges)
    assert graph.number_of_edges() == 6

    # Check all edge weights
    expected_weights = {
        (0, 1): 2,
        (1, 2): 1,
        (2, 3): 1,
        (3, 4): 2,
        (4, 5): 1,
        (0, 5): 1,
    }
    for (u, v), w in expected_weights.items():
        assert graph.has_edge(u, v), f"Missing edge {(u, v)}"
        assert graph[u][v].get("weight") == w, f"Wrong weight for {(u, v)}"


def test_display_interaction_graph(
    simple1_circuit_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    graph = build_interaction_graph(str(simple1_circuit_path))

    # Patch plt.show to prevent actual rendering during tests
    monkeypatch.setattr(
        "memq_dqc.graph.interaction_graph.plt.show",
        lambda: None,
    )

    try:
        display_interaction_graph(graph)
    except Exception as e:
        raise AssertionError(
            "Displaying interaction graph raised an exception"
        ) from e
