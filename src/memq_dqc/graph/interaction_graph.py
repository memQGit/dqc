# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Module for the construction of simple interaction graphs from a quantum circuit.

Here, an interaction graph is a graph where nodes represent logical qubits,
and the weight of edges between nodes represents the number of two-qubit gates
between those qubits.

"""

import matplotlib.pyplot as plt
import networkx as nx

from memq_dqc.utils import (
    count_total_qubits,
    extract_two_qubit_gates,
)


def build_interaction_graph(qasm_filename: str) -> nx.Graph:
    """Builds an interaction graph from a QASM circuit file.

    Args:
        qasm_filename: Path to the QASM circuit file.

    Returns:
        An interaction graph as a NetworkX Graph object.
    """
    # TODO: performance can be improved by avoiding re-parsing the file
    num_qubits = count_total_qubits(qasm_filename)
    gates_count = extract_two_qubit_gates(qasm_filename)

    graph = nx.Graph()
    for qubit_index in range(num_qubits):
        graph.add_node(qubit_index)

    for (q1, q2), weight in gates_count.items():
        graph.add_edge(q1, q2, weight=weight)

    return graph


def display_interaction_graph(graph: nx.Graph) -> None:
    """Displays the interaction graph using Matplotlib.

    Args:
        graph: The interaction graph as a NetworkX Graph object.
    """
    pos = nx.spring_layout(graph)
    edge_labels = nx.get_edge_attributes(graph, "weight")

    nx.draw(
        graph, pos, with_labels=True, node_color="lightblue", node_size=500
    )
    nx.draw_networkx_edge_labels(graph, pos, edge_labels=edge_labels)

    plt.title("Interaction Graph")
    plt.show()
