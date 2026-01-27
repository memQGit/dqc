# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Interaction graph construction from quantum circuits.

An interaction graph is a graph where nodes represent logical qubits, and the
edge weight between nodes reflects the number of two-qubit gates between those
qubits.
"""

import matplotlib.pyplot as plt
import networkx as nx

from memq_dqc.utils import count_total_qubits, extract_two_qubit_gates


class InteractionGraph:
    """Represents an interaction graph derived from a QASM circuit file.

    The graph is built once on initialization and can be accessed via the
    ``graph`` property. Additional metadata such as the number of qubits is
    available via properties.
    """

    def __init__(self, qasm_filename: str) -> None:
        """Initialize an InteractionGraph from a QASM circuit file.

        Args:
            qasm_filename: Path to the QASM circuit file.
        """
        self._qasm_filename = qasm_filename
        self._graph = nx.Graph()
        self._num_qubits = 0
        self._build_graph()

    def _build_graph(self) -> None:
        """Build the NetworkX graph from the QASM circuit file."""
        self._num_qubits = count_total_qubits(self._qasm_filename)
        gates_count = extract_two_qubit_gates(self._qasm_filename)

        self._graph.add_nodes_from(range(self._num_qubits))
        for (q1, q2), weight in gates_count.items():
            self._graph.add_edge(q1, q2, weight=weight)

    @property
    def graph(self) -> nx.Graph:
        """Return the underlying NetworkX graph."""
        return self._graph

    @property
    def num_qubits(self) -> int:
        """Return the number of qubits in the circuit."""
        return self._num_qubits

    def display(self) -> None:
        """Display the interaction graph using Matplotlib."""
        pos = nx.spring_layout(self._graph)
        edge_labels = nx.get_edge_attributes(self._graph, "weight")

        nx.draw(
            self._graph,
            pos,
            with_labels=True,
            node_color="lightblue",
            node_size=500,
        )
        nx.draw_networkx_edge_labels(
            self._graph, pos, edge_labels=edge_labels
        )

        plt.title("Interaction Graph")
        plt.show()
