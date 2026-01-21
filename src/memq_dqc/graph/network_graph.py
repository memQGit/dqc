# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Module for construction of network graphs from JSON specifications.

After describing the network topology using the GUI tool, the resulting
JSON file is used to create a NetworkX graph representation of the network.
The resulting graph accurately reflects local and remote connectivity.
"""

import json

import matplotlib.pyplot as plt
import networkx as nx


class NetworkGraph:
    """Represents a quantum network as a NetworkX graph with metadata."""

    def __init__(self, network_json_filename: str) -> None:
        """Initialize a NetworkGraph from a JSON specification file.

        Args:
            network_json_filename: The filename of the network specification
                JSON file.
        """
        # Load network specification JSON file
        with open(network_json_filename) as f:
            self._network_data = json.load(f)

        self._graph = nx.Graph()
        self._qubit_type_map: dict[int, str] = {}
        self._build_network_graph()

    def _build_network_graph(self) -> None:
        """Generate a NetworkX graph from the network specification.

        Populates the graph with qubits as nodes and their local/remote
        connections as edges. Also builds the qubit type mapping.
        """
        qubits = self._network_data["qubits"]
        for qubit, data in qubits.items():
            # Mark qubit type (computation or communication)
            self._qubit_type_map[int(qubit)] = data.get("type")
            # Add qubit in graph and unpack its attributes to store as node data
            self._graph.add_node(int(qubit), **data)
        for qubit, data in qubits.items():
            local_connects = data.get("localConnections", [])
            remote_connects = data.get("remoteConnections", [])
            for local in local_connects:
                self._graph.add_edge(
                    int(qubit), int(local), connection_type="local"
                )
            for remote in remote_connects:
                self._graph.add_edge(
                    int(qubit), int(remote), connection_type="remote"
                )

    @property
    def graph(self) -> nx.Graph:
        """Return the underlying NetworkX graph."""
        return self._graph

    @property
    def qubit_type_map(self) -> dict[int, str]:
        """Return the mapping of qubit IDs to their types."""
        return self._qubit_type_map

    @property
    def num_qpus(self) -> int:
        """Return the number of QPUs in the network."""
        return len(self._network_data["processors"])

    @property
    def num_total_qubits(self) -> int:
        """Return the total number of qubits in the network."""
        return self._graph.number_of_nodes()

    @property
    def num_comp_qubits(self) -> int:
        """Return the number of computation qubits in the network."""
        return sum(
            1
            for qubit_type in self._qubit_type_map.values()
            if qubit_type == "computation"
        )

    @property
    def num_comm_qubits(self) -> int:
        """Return the number of communication qubits in the network."""
        return sum(
            1
            for qubit_type in self._qubit_type_map.values()
            if qubit_type == "communication"
        )

    def comp_qubits_per_qpu(self) -> list[int]:
        """Return the number of computation qubits for each QPU.

        Returns:
            A list where index i contains the number of computation qubits
            in QPU i. For example, [3, 7, 2, 3] means QPU 0 has 3 comp
            qubits, QPU 1 has 7, etc.
        """
        processors = self._network_data["processors"]
        # Sort by processor ID to ensure consistent ordering
        sorted_processor_ids = sorted(int(pid) for pid in processors.keys())

        comp_qubits_count = []
        for proc_id in sorted_processor_ids:
            processor = processors[str(proc_id)]
            qubit_ids = processor["qubits"]
            comp_count = sum(
                1
                for qid in qubit_ids
                if self._qubit_type_map[qid] == "computation"
            )
            comp_qubits_count.append(comp_count)

        return comp_qubits_count

    def comm_qubits_per_qpu(self) -> list[int]:
        """Return the number of communication qubits for each QPU.

        Returns:
            A list where index i contains the number of communication qubits
            in QPU i. For example, [2, 1, 3, 2] means QPU 0 has 2 comm
            qubits, QPU 1 has 1, etc.
        """
        processors = self._network_data["processors"]
        # Sort by processor ID to ensure consistent ordering
        sorted_processor_ids = sorted(int(pid) for pid in processors.keys())

        comm_qubits_count = []
        for proc_id in sorted_processor_ids:
            processor = processors[str(proc_id)]
            qubit_ids = processor["qubits"]
            comm_count = sum(
                1
                for qid in qubit_ids
                if self._qubit_type_map[qid] == "communication"
            )
            comm_qubits_count.append(comm_count)

        return comm_qubits_count

    @property
    def is_homogeneous(self) -> bool:
        """Return True if all QPUs have identical comp and comm qubit counts.

        Returns:
            True if all QPUs have the same number of computation qubits
            AND the same number of communication qubits. False otherwise.
        """
        comp_counts = self.comp_qubits_per_qpu()
        comm_counts = self.comm_qubits_per_qpu()

        # All comp counts are equal and all comm counts are equal
        return len(set(comp_counts)) <= 1 and len(set(comm_counts)) <= 1

    def display(self) -> None:
        """Display the network graph using Matplotlib."""
        local_edges = self._get_local_edges()
        remote_edges = self._get_remote_edges()

        pos = nx.spring_layout(self._graph)
        nx.draw_networkx_nodes(self._graph, pos, node_size=700)
        nx.draw_networkx_labels(
            self._graph, pos, font_size=12, font_family="sans-serif"
        )
        nx.draw_networkx_edges(
            self._graph,
            pos,
            edgelist=local_edges,
            width=2,
            edge_color="blue",
            label="Local",
            style="solid",
        )

        nx.draw_networkx_edges(
            self._graph,
            pos,
            edgelist=remote_edges,
            width=2,
            edge_color="red",
            label="Remote",
            style="dashed",
        )

        plt.show()

    def _get_local_edges(self) -> list[tuple[int, int]]:
        """Get all local connection edges from the graph.

        Returns:
            A list of edge tuples representing local connections.
        """
        return [
            (u, v)
            for u, v, data in self._graph.edges(data=True)
            if data.get("connection_type") == "local"
        ]

    def _get_remote_edges(self) -> list[tuple[int, int]]:
        """Get all remote connection edges from the graph.

        Returns:
            A list of edge tuples representing remote connections.
        """
        return [
            (u, v)
            for u, v, data in self._graph.edges(data=True)
            if data.get("connection_type") == "remote"
        ]
