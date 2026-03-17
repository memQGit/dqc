# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import matplotlib.pyplot as plt
import networkx as nx
import pytest
from matplotlib.figure import Figure

from memq_dqc.builder.circuit_extractor import extract_distributed_circuit
from memq_dqc.circuit import Circuit
from memq_dqc.network import NetworkGraph
from memq_dqc.partition import Partitioner
from memq_dqc.preprocessing.qasm.io import load_qasm_program
from memq_dqc.visualization import (
    build_dag_networkx_graph,
    plot_circuit_dag,
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


def test_plot_circuit_dag_uses_top_to_bottom_layout(
    bell_circuit_path,
) -> None:
    circuit = Circuit(str(bell_circuit_path))

    ax = plot_circuit_dag(
        circuit,
        title="Bell DAG",
        show_edge_labels=True,
    )

    labels = {text.get_text() for text in ax.texts}
    assert "Bell DAG" == ax.get_title()
    assert ax.yaxis_inverted()
    assert {"q[0]", "q[1]", "h", "cx"} <= labels
    assert isinstance(ax.figure, Figure)
    plt.close(ax.figure)


def test_plot_distributed_dag_requires_distributed_circuit(
    bell_circuit_path,
) -> None:
    circuit = Circuit(str(bell_circuit_path))

    with pytest.raises(ValueError, match="build_distributed"):
        plot_distributed_dag(circuit)


def test_plot_distributed_dag_renders_remote_operations(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo_kwargs={"window_length": 3},
    )
    partitioner.run()
    extract_distributed_circuit(partitioner)
    assert partitioner.circuit.distributed is not None

    graph = build_dag_networkx_graph(partitioner.circuit.distributed.dag)
    operation_labels = {
        data["label"]
        for _, data in graph.nodes(data=True)
        if data["kind"] == "operation"
    }
    ax = plot_distributed_dag(partitioner.circuit.distributed)

    assert ax.yaxis_inverted()
    assert any(label.startswith("r") for label in operation_labels)
    assert isinstance(ax.figure, Figure)
    plt.close(ax.figure)
