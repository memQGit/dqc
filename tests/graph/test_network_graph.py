# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import json
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


def test_dict_qubits_schema_with_string_ids(
    simple1_network_path: Path,
) -> None:
    network_path = simple1_network_path.parent / "dict_qubits_string_ids.json"
    assert network_path.exists()
    network = NetworkGraph(str(network_path))

    assert network.num_total_qubits == 10
    assert network.num_comp_qubits == 6
    assert network.num_comm_qubits == 4
    assert network.comp_qubits_per_qpu() == [3, 3]
    assert network.comm_qubits_per_qpu() == [2, 2]
    assert "q_0_0" in network.graph.nodes
    assert "c_1_1" in network.graph.nodes
    assert network.graph.has_edge("c_0_0", "c_1_0")
    assert network.graph.has_edge("c_0_1", "c_1_1")
    assert network.graph.number_of_edges() == 2


def test_list_schema_unknown_qubit_id_raises(tmp_path: Path) -> None:
    network_data = {
        "processors": {"1": {"id": 1, "qubits": [1, 99]}},
        "qubits": {
            "1": {
                "id": 1,
                "type": "computation",
                "processorId": 1,
                "localConnections": [],
                "remoteConnections": [],
            }
        },
        "connections": [],
    }
    path = tmp_path / "unknown_qubit.json"
    path.write_text(json.dumps(network_data), encoding="utf-8")

    network = NetworkGraph(str(path))
    with pytest.raises(ValueError, match="unknown qubit ID"):
        network.comp_qubits_per_qpu()


def test_list_schema_invalid_qubit_type_raises(tmp_path: Path) -> None:
    network_data = {
        "processors": {"1": {"id": 1, "qubits": [1]}},
        "qubits": {
            "1": {
                "id": 1,
                "type": "auxiliary",
                "processorId": 1,
                "localConnections": [],
                "remoteConnections": [],
            }
        },
        "connections": [],
    }
    path = tmp_path / "invalid_type.json"
    path.write_text(json.dumps(network_data), encoding="utf-8")

    network = NetworkGraph(str(path))
    with pytest.raises(ValueError, match="Invalid qubit type"):
        network.comp_qubits_per_qpu()
