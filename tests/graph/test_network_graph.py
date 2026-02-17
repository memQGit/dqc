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


def _node_by_label(network: NetworkGraph, label: str):
    for node in network.graph.nodes:
        if node.label == label:
            return node
    raise AssertionError(f"Node with label {label!r} was not found.")


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
    labels = {node.label for node in network.graph.nodes}
    assert "q_0_0" in labels
    assert "c_1_1" in labels
    edge_labels = {
        tuple(sorted((u.label, v.label))) for u, v in network.graph.edges
    }
    assert tuple(sorted(("c_0_0", "c_1_0"))) in edge_labels
    assert tuple(sorted(("c_0_1", "c_1_1"))) in edge_labels
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

    with pytest.raises(ValueError, match="Invalid qubit type"):
        NetworkGraph(str(path))


def test_get_shortest_path_returns_nearest_comm_path(
    simple1_network_path: Path,
) -> None:
    network = NetworkGraph(str(simple1_network_path))
    source = _node_by_label(network, "q_1_0")
    destination = _node_by_label(network, "c_1_0")

    assert network._get_shortest_path(source) == [source, destination]


def test_local_swap_dict_property(simple1_network_path: Path) -> None:
    network = NetworkGraph(str(simple1_network_path))
    q_1_0 = _node_by_label(network, "q_1_0")
    q_1_1 = _node_by_label(network, "q_1_1")
    c_1_0 = _node_by_label(network, "c_1_0")
    c_1_1 = _node_by_label(network, "c_1_1")

    swap_map = network.local_swap_dict

    assert isinstance(swap_map, dict)
    assert swap_map[q_1_0] == (0, [q_1_0, c_1_0])
    assert swap_map[q_1_1] == (0, [q_1_1, c_1_1])


def test_qubit_type_accessors(simple1_network_path: Path) -> None:
    network = NetworkGraph(str(simple1_network_path))

    comp_qubits = network.computation_qubits()
    comm_qubits = network.communication_qubits()

    assert len(comp_qubits) == network.num_comp_qubits
    assert len(comm_qubits) == network.num_comm_qubits
    assert all(qubit.is_computation for qubit in comp_qubits)
    assert all(qubit.is_communication for qubit in comm_qubits)
    assert [qubit.label for qubit in comp_qubits] == [
        "q_1_0",
        "q_1_1",
        "q_2_0",
        "q_2_1",
    ]


def test_get_comm_pair_paths_are_local_to_source_qpu(
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    qubit_a = _node_by_label(network, "q_1_0")
    qubit_b = _node_by_label(network, "q_0_0")

    _cost, (comm_a, comm_b), (path_a, path_b) = network.get_comm_pair(
        qubit_a, qubit_b
    )

    assert path_a[0] == qubit_a
    assert path_b[0] == qubit_b
    assert path_a[-1] == comm_a
    assert path_b[-1] == comm_b
    assert comm_a.qpu_id == qubit_a.qpu_id
    assert comm_b.qpu_id == qubit_b.qpu_id
    assert sum(node.is_communication for node in path_a) == 1
    assert sum(node.is_communication for node in path_b) == 1
    assert all(node.qpu_id == qubit_a.qpu_id for node in path_a)
    assert all(node.qpu_id == qubit_b.qpu_id for node in path_b)
