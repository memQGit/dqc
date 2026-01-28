# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

import networkx as nx
import pytest

from memq_dqc.graph.network_graph import NetworkGraph


def test_build_network_graph_returns_graph(simple1_network_path: Path) -> None:
    network = NetworkGraph(str(simple1_network_path))

    assert isinstance(network.graph, nx.Graph)
    assert isinstance(network.qubit_type_map, dict)


def test_build_network_graph_structure(
    simple1_network_path: Path,
) -> None:
    network = NetworkGraph(str(simple1_network_path))

    # The simple1.json network has 8 qubits
    assert network.num_total_qubits == 8

    # The simple1.json network has 10 connections (edges)
    assert network.graph.number_of_edges() == 10


def test_display_network_graph(
    simple1_network_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    network = NetworkGraph(str(simple1_network_path))

    # Patch plt.show to prevent actual rendering during tests
    monkeypatch.setattr(
        "memq_dqc.graph.network_graph.plt.show",
        lambda: None,
    )

    # Just ensure that the function runs without error
    try:
        network.display()
    except Exception as e:
        raise AssertionError(
            "Displaying network graph raised an exception"
        ) from e


def test_num_total_qubits_simple1(simple1_network_path: Path) -> None:
    network = NetworkGraph(str(simple1_network_path))
    assert network.num_total_qubits == 8


def test_num_total_qubits_nonuniform_1(
    simple1_network_path: Path,
) -> None:
    # Use the conftest fixture or path construction
    network_path = simple1_network_path.parent / "nonuniform_1.json"
    assert network_path.exists()
    network = NetworkGraph(str(network_path))
    assert network.num_total_qubits == 15


def test_num_qpus_simple1(simple1_network_path: Path) -> None:
    network = NetworkGraph(str(simple1_network_path))
    assert network.num_qpus == 2


def test_num_qpus_nonuniform_1(simple1_network_path: Path) -> None:
    network_path = simple1_network_path.parent / "nonuniform_1.json"
    assert network_path.exists()
    network = NetworkGraph(str(network_path))
    assert network.num_qpus == 3


def test_num_comp_qubits_simple1(simple1_network_path: Path) -> None:
    network = NetworkGraph(str(simple1_network_path))
    assert network.num_comp_qubits == 4


def test_num_comp_qubits_8comp_4comm(simple1_network_path: Path) -> None:
    network_path = simple1_network_path.parent / "simple_8comp_4comm.json"
    assert network_path.exists()
    network = NetworkGraph(str(network_path))
    assert network.num_comp_qubits == 8


def test_num_comm_qubits_simple1(simple1_network_path: Path) -> None:
    network = NetworkGraph(str(simple1_network_path))
    assert network.num_comm_qubits == 4


def test_num_comm_qubits_nonuniform_1(simple1_network_path: Path) -> None:
    network_path = simple1_network_path.parent / "nonuniform_1.json"
    assert network_path.exists()
    network = NetworkGraph(str(network_path))
    assert network.num_comm_qubits == 6


def test_comp_qubits_per_qpu_simple1(
    simple1_network_path: Path,
) -> None:
    network = NetworkGraph(str(simple1_network_path))
    assert network.comp_qubits_per_qpu() == [2, 2]


def test_comp_qubits_per_qpu_nonuniform_1(
    simple1_network_path: Path,
) -> None:
    network_path = simple1_network_path.parent / "nonuniform_1.json"
    assert network_path.exists()
    network = NetworkGraph(str(network_path))
    assert network.comp_qubits_per_qpu() == [4, 3, 2]


def test_comm_qubits_per_qpu_simple1(
    simple1_network_path: Path,
) -> None:
    network = NetworkGraph(str(simple1_network_path))
    assert network.comm_qubits_per_qpu() == [2, 2]


def test_comm_qubits_per_qpu_nonuniform_1(
    simple1_network_path: Path,
) -> None:
    network_path = simple1_network_path.parent / "nonuniform_1.json"
    assert network_path.exists()
    network = NetworkGraph(str(network_path))
    assert network.comm_qubits_per_qpu() == [2, 3, 1]


def test_is_homogeneous_simple1(simple1_network_path: Path) -> None:
    network = NetworkGraph(str(simple1_network_path))
    assert network.is_homogeneous is True


def test_is_homogeneous_nonuniform_1(simple1_network_path: Path) -> None:
    network_path = simple1_network_path.parent / "nonuniform_1.json"
    assert network_path.exists()
    network = NetworkGraph(str(network_path))
    assert network.is_homogeneous is False
