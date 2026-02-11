# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Construction of network graphs from JSON specifications.

After describing the network topology using the GUI tool, the resulting
JSON file is used to create a NetworkX graph representation of the network.
The resulting graph reflects local and remote connectivity between qubits.
"""

import json
from collections.abc import Iterable

import matplotlib.pyplot as plt
import networkx as nx


class NetworkGraph:
    """Represents a quantum network constructed from a JSON specification.

    This class parses a network description JSON file and builds a
    :class:`networkx.Graph` instance whose nodes represent qubits and whose
    edges represent local and remote connections between those qubits.

    The resulting graph and associated metadata can be accessed via
    the ``graph`` and ``qubit_type_map`` properties and are used to
    derive summary information such as qubit counts per QPU.
    """

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
        self._qubit_type_map: dict[int | str, str] = {}
        self._build_network_graph()

    def _build_network_graph(self) -> None:
        """Generate a NetworkX graph from the network specification.

        Populates the graph with qubits as nodes and their local/remote
        connections as edges. Also builds the qubit type mapping.
        """
        qubits = self._network_data["qubits"]
        for qubit, data in qubits.items():
            qubit_id = _normalize_qubit_id(qubit)
            # Mark qubit type (computation or communication)
            self._qubit_type_map[qubit_id] = data.get("type")
            # Add qubit in graph and unpack its attributes to store as node data
            self._graph.add_node(qubit_id, **data)
        for qubit, data in qubits.items():
            qubit_id = _normalize_qubit_id(qubit)
            local_connects = data.get("localConnections", [])
            remote_connects = data.get("remoteConnections", [])
            for local in local_connects:
                self._graph.add_edge(
                    qubit_id,
                    _normalize_qubit_id(local),
                    connection_type="local",
                )
            for remote in remote_connects:
                self._graph.add_edge(
                    qubit_id,
                    _normalize_qubit_id(remote),
                    connection_type="remote",
                )

    @property
    def graph(self) -> nx.Graph:
        """Return the underlying NetworkX graph."""
        return self._graph

    @property
    def qubit_type_map(self) -> dict[int | str, str]:
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
            Counts of computation qubits per QPU, ordered by processor ID.
        """
        return [
            len(qubit_groups["computation"])
            for qubit_groups in self._processor_qubit_groups()
        ]

    def comm_qubits_per_qpu(self) -> list[int]:
        """Return the number of communication qubits for each QPU.

        Returns:
            Counts of communication qubits per QPU, ordered by processor ID.
        """
        return [
            len(qubit_groups["communication"])
            for qubit_groups in self._processor_qubit_groups()
        ]

    @property
    def is_homogeneous(self) -> bool:
        """Return True if all QPUs have identical comp and comm qubit counts.

        Returns:
            True when computation and communication qubit counts match across
            all QPUs.
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

    def _get_local_edges(self) -> list[tuple[int | str, int | str]]:
        """Get all local connection edges from the graph.

        Returns:
            Local connection edges.
        """
        return [
            (u, v)
            for u, v, data in self._graph.edges(data=True)
            if data.get("connection_type") == "local"
        ]

    def _get_remote_edges(self) -> list[tuple[int | str, int | str]]:
        """Get all remote connection edges from the graph.

        Returns:
            Remote connection edges.
        """
        return [
            (u, v)
            for u, v, data in self._graph.edges(data=True)
            if data.get("connection_type") == "remote"
        ]

    def _processor_qubit_groups(
        self,
    ) -> list[dict[str, list[int | str]]]:
        """Return computation and communication qubits for each processor."""
        processors = self._network_data["processors"]
        sorted_processor_ids = sorted(
            processors.keys(),
            key=_processor_sort_key,
        )

        grouped: list[dict[str, list[int | str]]] = []
        for proc_id in sorted_processor_ids:
            processor = processors[proc_id]
            qubits = processor.get("qubits", [])
            if isinstance(qubits, dict):
                grouped.append(
                    {
                        "computation": _normalize_qubit_ids(
                            qubits.get("computation", [])
                        ),
                        "communication": _normalize_qubit_ids(
                            qubits.get("communication", [])
                        ),
                    }
                )
                continue

            comp_ids: list[int | str] = []
            comm_ids: list[int | str] = []
            for qubit_id in _normalize_qubit_ids(qubits):
                if qubit_id not in self._qubit_type_map:
                    raise ValueError(
                        f"Processor references unknown qubit ID {qubit_id!r}."
                    )
                qubit_type = self._qubit_type_map[qubit_id]
                if qubit_type == "computation":
                    comp_ids.append(qubit_id)
                elif qubit_type == "communication":
                    comm_ids.append(qubit_id)
                else:
                    raise ValueError(
                        "Invalid qubit type for qubit "
                        f"{qubit_id!r}: {qubit_type!r}. Expected "
                        "'computation' or 'communication'."
                    )
            grouped.append(
                {
                    "computation": comp_ids,
                    "communication": comm_ids,
                }
            )

        return grouped


def _normalize_qubit_ids(
    qubit_ids: Iterable[object],
) -> list[int | str]:
    """Normalize a list of qubit IDs into int-or-string values."""
    return [_normalize_qubit_id(qubit_id) for qubit_id in qubit_ids]


def _normalize_qubit_id(qubit_id: object) -> int | str:
    """Normalize a qubit ID, preserving non-numeric string IDs."""
    if isinstance(qubit_id, int):
        return qubit_id
    if isinstance(qubit_id, str) and qubit_id.isdigit():
        return int(qubit_id)
    return str(qubit_id)


def _processor_sort_key(processor_id: str) -> tuple[int, int | str]:
    """Sort processor IDs numerically when possible, then lexically."""
    if processor_id.isdigit():
        return (0, int(processor_id))
    return (1, processor_id)
