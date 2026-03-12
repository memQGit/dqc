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
import re
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass

import matplotlib.pyplot as plt
import networkx as nx


@dataclass(frozen=True, slots=True)
class PhysicalQubit:
    """Structured identifier for a qubit in a network graph."""

    qpu_id: int
    qubit_id: int
    qubit_type: str

    @property
    def is_communication(self) -> bool:
        """Return True when this is a communication qubit."""
        return self.qubit_type == "communication"

    @property
    def is_computation(self) -> bool:
        """Return True when this is a computation qubit."""
        return self.qubit_type == "computation"

    @property
    def label(self) -> str:
        """Return display label in q/c_<qpu>_<id> format."""
        prefix = "c" if self.is_communication else "q"
        return f"{prefix}_{self.qpu_id}_{self.qubit_id}"

    def __str__(self) -> str:
        """Return compact display label."""
        return self.label


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
        self._qubit_type_map: dict[PhysicalQubit, str] = {}
        self._raw_id_to_qubit: dict[int | str, PhysicalQubit] = {}
        self._build_network_graph()

    def _build_network_graph(self) -> None:
        """Generate a NetworkX graph from the network specification.

        Populates the graph with qubits as nodes and their local/remote
        connections as edges. Also builds the qubit type mapping.
        """
        qubits = self._network_data["qubits"]
        next_local_idx: dict[tuple[int, str], int] = {}
        for qubit, data in qubits.items():
            raw_id = _normalize_qubit_id(qubit)
            qubit_type = data.get("type")
            if qubit_type not in {"computation", "communication"}:
                raise ValueError(
                    "Invalid qubit type for qubit "
                    f"{raw_id!r}: {qubit_type!r}. Expected "
                    "'computation' or 'communication'."
                )
            if "processorId" not in data:
                raise ValueError(
                    f"Qubit {raw_id!r} is missing required 'processorId'."
                )
            qpu_id = _normalize_processor_id(data["processorId"])
            local_idx = _resolve_local_qubit_index(
                raw_id,
                qpu_id,
                qubit_type,
                data.get("localIndex"),
                next_local_idx,
            )
            network_qubit = PhysicalQubit(
                qpu_id=qpu_id,
                qubit_id=local_idx,
                qubit_type=qubit_type,
            )
            self._raw_id_to_qubit[raw_id] = network_qubit
            self._qubit_type_map[network_qubit] = qubit_type
            node_data = dict(data)
            node_data["id"] = network_qubit
            node_data["processorId"] = qpu_id
            node_data["label"] = network_qubit.label
            self._graph.add_node(network_qubit, **node_data)

        for qubit, data in qubits.items():
            source = self._resolve_qubit_node(qubit)
            local_connects = data.get("localConnections", [])
            remote_connects = data.get("remoteConnections", [])
            for local in local_connects:
                self._graph.add_edge(
                    source,
                    self._resolve_qubit_node(local),
                    connection_type="local",
                )
            for remote in remote_connects:
                self._graph.add_edge(
                    source,
                    self._resolve_qubit_node(remote),
                    connection_type="remote",
                )

    @property
    def graph(self) -> nx.Graph:
        """Return the underlying NetworkX graph."""
        return self._graph

    @property
    def qubit_type_map(self) -> dict[PhysicalQubit, str]:
        """Return the mapping of qubit IDs to their types."""
        return dict(self._qubit_type_map)

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

    def computation_qubits(self) -> list[PhysicalQubit]:
        """Return all computation qubit nodes in deterministic order."""
        return sorted(
            (
                qubit
                for qubit, qubit_type in self._qubit_type_map.items()
                if qubit_type == "computation"
            ),
            key=_network_qubit_sort_key,
        )

    def communication_qubits(self) -> list[PhysicalQubit]:
        """Return all communication qubit nodes in deterministic order."""
        return sorted(
            (
                qubit
                for qubit, qubit_type in self._qubit_type_map.items()
                if qubit_type == "communication"
            ),
            key=_network_qubit_sort_key,
        )

    @property
    def local_swap_dict(
        self,
    ) -> dict[PhysicalQubit, tuple[float, list[PhysicalQubit]]]:
        """Return map from comp qubits to swaps toward nearest comm qubit."""
        swap_mapping: dict[
            PhysicalQubit, tuple[float, list[PhysicalQubit]]
        ] = {}
        for qubit, qubit_type in self._qubit_type_map.items():
            if qubit_type != "computation":
                continue
            try:
                path_to_comm = self._get_shortest_path(qubit)
                num_swaps = max(0, len(path_to_comm) - 2)
                swap_mapping[qubit] = (num_swaps, path_to_comm)
            except ValueError:
                swap_mapping[qubit] = (float("inf"), [])
        return swap_mapping

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

    def get_comm_pair_options(
        self, qubit_a: PhysicalQubit, qubit_b: PhysicalQubit
    ) -> list[
        tuple[
            int,
            tuple[PhysicalQubit, PhysicalQubit],
            tuple[list[PhysicalQubit], list[PhysicalQubit]],
        ]
    ]:
        """Return reachable communication-pair options sorted by cost.

        Args:
            qubit_a: The first computation qubit.
            qubit_b: The second computation qubit.

        Returns:
            Ranked communication-pair options sorted by increasing cost and
            deterministic label tie-breakers.

        Raises:
            ValueError: If no valid communication pairs exist or no pair is
                reachable via local paths.
        """
        potential_pairs = self._valid_comm_pairs(qubit_a, qubit_b)
        if not potential_pairs:
            raise ValueError(
                f"No communication pairs found to connect {qubit_a!r} and "
                f"{qubit_b!r}."
            )

        local_graph = self._local_only_graph()
        paths_a, path_len_a = nx.predecessor(
            local_graph, qubit_a, return_seen=True
        )
        paths_b, path_len_b = nx.predecessor(
            local_graph, qubit_b, return_seen=True
        )
        costs_a = {node: path_len - 1 for node, path_len in path_len_a.items()}
        costs_b = {node: path_len - 1 for node, path_len in path_len_b.items()}

        # Iterate through each set of comm qubit pairs, assemble path options
        pair_options: list[
            tuple[
                int,
                tuple[PhysicalQubit, PhysicalQubit],
                tuple[list[PhysicalQubit], list[PhysicalQubit]],
            ]
        ] = []
        for comm_a, comm_b in potential_pairs:
            if comm_a not in costs_a or comm_b not in costs_b:
                continue
            path_a = self._construct_path(paths_a, qubit_a, comm_a)
            path_b = self._construct_path(paths_b, qubit_b, comm_b)
            if path_a is None or path_b is None:
                continue
            pair_options.append(
                (
                    costs_a[comm_a] + costs_b[comm_b],
                    (comm_a, comm_b),
                    (path_a, path_b),
                )
            )
        if not pair_options:
            raise ValueError(
                f"No reachable communication pairs found to connect {qubit_a!r} "
                f"and {qubit_b!r}."
            )
        # Sort by decreasing cost (then by qpu / qubit labels)
        return sorted(
            pair_options,
            key=lambda item: (
                item[0],
                item[1][0].label,
                item[1][1].label,
            ),
        )

    def get_qpu_route(
        self,
        source_qpu_id: int,
        target_qpu_id: int,
    ) -> list[int]:
        """Return a directional QPU route for a routed remote gate.

        The route moves the source operand through ``rswap`` hops until it is
        on a QPU adjacent to the target operand. Internal hops must support
        ``rswap`` (2 e-bit pairs), while the final hop to the target side
        must support a remote gate (1 e-bit pair).

        Args:
            source_qpu_id: QPU ID of the operand selected to move.
            target_qpu_id: QPU ID of the operand kept in place.

        Returns:
            Ordered QPU IDs from source to target.

        Raises:
            ValueError: If no directional route is available.
        """
        # TODO: right now this is for 'RSWAP' based routing - generalize
        if source_qpu_id == target_qpu_id:
            return [source_qpu_id]

        # Count how many direct remote communication pairs exist between QPUs.
        pair_counts = self._remote_comm_pair_counts()
        direct_key = _ordered_qpu_pair(source_qpu_id, target_qpu_id)
        candidates: list[list[int]] = []

        # A direct remote edge is already a valid route.
        if pair_counts.get(direct_key, 0) >= 1:
            candidates.append([source_qpu_id, target_qpu_id])

        # Otherwise, route to a QPU that can perform the final remote gate
        # into the target, while requiring swap-capable hops beforehand.
        for neighbor_qpu in self._qpu_neighbors_with_min_pairs(
            target_qpu_id,
            min_pairs=1,
            pair_counts=pair_counts,
        ):
            if neighbor_qpu == source_qpu_id:
                continue
            try:
                path_to_neighbor = self._shortest_qpu_path_with_min_pairs(
                    source_qpu_id,
                    neighbor_qpu,
                    min_pairs=2,
                    pair_counts=pair_counts,
                )
            except ValueError:
                continue
            # Reject routes that overshoot through the target before the end.
            if target_qpu_id in path_to_neighbor[:-1]:
                continue
            candidates.append(path_to_neighbor + [target_qpu_id])

        if not candidates:
            raise ValueError(
                "No routed remote-gate path found for directional movement: "
                f"{source_qpu_id} -> {target_qpu_id}."
            )

        # Prefer the shortest routed path, then fall back to deterministic ID
        # ordering if multiple candidates have the same length.
        return min(
            candidates,
            key=lambda path: (
                _route_length(path),
                tuple(path),
            ),
        )

    def remote_gate_ebit_cost(
        self,
        qpu_a: int,
        qpu_b: int,
    ) -> int:
        # TODO: go through this - relied on codex refactor for time crunch
        """Return minimum raw e-bit pairs for a remote gate between two QPUs.

        Args:
            qpu_a: First QPU ID.
            qpu_b: Second QPU ID.

        Returns:
            Minimum required e-bit pairs.

        Raises:
            ValueError: If no routed remote-gate path is available.
        """
        if qpu_a == qpu_b:
            return 0

        route_options: list[list[int]] = []
        for source, target in ((qpu_a, qpu_b), (qpu_b, qpu_a)):
            try:
                route_options.append(self.get_qpu_route(source, target))
            except ValueError:
                continue

        if not route_options:
            raise ValueError(
                "No routed remote-gate path found between QPUs "
                f"{qpu_a} and {qpu_b}."
            )

        return min(1 + (4 * _route_length(path)) for path in route_options)

    def remote_swap_ebit_cost(
        self,
        qpu_a: int,
        qpu_b: int,
    ) -> int:
        """Return routed swap cost between two QPUs.

        Args:
            qpu_a: First QPU ID.
            qpu_b: Second QPU ID.

        Returns:
            Routed swap cost in e-bit pairs.

        Raises:
            ValueError: If no swap-capable QPU route is available.
        """
        if qpu_a == qpu_b:
            return 0

        pair_counts = self._remote_comm_pair_counts()
        path = self._shortest_qpu_path_with_min_pairs(
            source_qpu_id=qpu_a,
            target_qpu_id=qpu_b,
            min_pairs=2,
            pair_counts=pair_counts,
        )
        return 2 * _route_length(path)

    def _remote_comm_pair_counts(self) -> dict[tuple[int, int], int]:
        """Count direct remote communication pairs between QPU pairs."""
        pair_counts: dict[tuple[int, int], int] = {}
        for qubit_a, qubit_b in self._get_remote_edges():
            if not (qubit_a.is_communication and qubit_b.is_communication):
                continue
            key = _ordered_qpu_pair(qubit_a.qpu_id, qubit_b.qpu_id)
            pair_counts[key] = pair_counts.get(key, 0) + 1
        return pair_counts

    def _qpu_neighbors_with_min_pairs(
        # TODO: go through this - relied on codex refactor for time crunch
        self,
        qpu_id: int,
        min_pairs: int,
        pair_counts: dict[tuple[int, int], int],
    ) -> list[int]:
        """Return sorted neighboring QPU IDs meeting pair-count threshold."""
        neighbors = []
        for pair, count in pair_counts.items():
            if count < min_pairs:
                continue
            qpu_left, qpu_right = pair
            if qpu_left == qpu_id:
                neighbors.append(qpu_right)
            elif qpu_right == qpu_id:
                neighbors.append(qpu_left)
        return sorted(set(neighbors))

    def _shortest_qpu_path_with_min_pairs(
        # TODO: go through this - relied on codex refactor for time crunch
        self,
        source_qpu_id: int,
        target_qpu_id: int,
        min_pairs: int,
        pair_counts: dict[tuple[int, int], int],
    ) -> list[int]:
        """Return shortest QPU path where each hop has enough e-bit pairs."""
        if source_qpu_id == target_qpu_id:
            return [source_qpu_id]

        queue: deque[int] = deque([source_qpu_id])
        predecessor: dict[int, int | None] = {source_qpu_id: None}
        while queue:
            current = queue.popleft()
            for neighbor in self._qpu_neighbors_with_min_pairs(
                current, min_pairs, pair_counts
            ):
                if neighbor in predecessor:
                    continue
                predecessor[neighbor] = current
                if neighbor == target_qpu_id:
                    return _reconstruct_qpu_path(predecessor, target_qpu_id)
                queue.append(neighbor)

        raise ValueError(
            "No QPU path found with required e-bit pairs: "
            f"{source_qpu_id} -> {target_qpu_id} "
            f"(min_pairs={min_pairs})."
        )

    def _construct_path(
        self, pred: dict, source: PhysicalQubit, target: PhysicalQubit
    ) -> list[PhysicalQubit] | None:
        """Reconstruct a shortest path from predecessor information.

        Given a predecessor dictionary from NetworkX shortest path algorithms,
        reconstructs the actual path from source to target.

        When multiple shortest predecessor choices exist, this method
        deterministically prefers paths that keep intermediate nodes on
        computation qubits.

        Args:
            pred: Predecessor dictionary mapping each node to a list of
                predecessor nodes on shortest paths, as returned by
                nx.predecessor().
            source: The starting node of the path.
            target: The destination node of the path.

        Returns:
            A list of nodes representing the path from source to target,
            or None if no path exists.
        """
        # TODO: review and cleanup this function
        if target == source:
            return [source]
        if target not in pred:  # unreachable
            return None

        memo: dict[PhysicalQubit, list[PhysicalQubit] | None] = {}

        # TODO: remove nested function
        def _path_key(
            path: list[PhysicalQubit],
        ) -> tuple[int, tuple[str, ...]]:
            nonterminal_comm_count = sum(
                node.is_communication for node in path[:-1]
            )
            return (
                nonterminal_comm_count,
                tuple(node.label for node in path),
            )

        def _build_path(node: PhysicalQubit) -> list[PhysicalQubit] | None:
            if node == source:
                return [source]
            if node in memo:
                return memo[node]

            predecessors = pred.get(node, [])
            candidate_paths: list[list[PhysicalQubit]] = []
            for predecessor in predecessors:
                predecessor_path = _build_path(predecessor)
                if predecessor_path is None:
                    continue
                candidate_paths.append(predecessor_path + [node])

            if not candidate_paths:
                memo[node] = None
                return None

            memo[node] = min(candidate_paths, key=_path_key)
            return memo[node]

        return _build_path(target)

    def _valid_comm_pairs(
        self, qubit_a: PhysicalQubit, qubit_b: PhysicalQubit
    ) -> list[tuple[PhysicalQubit, PhysicalQubit]]:
        """Returns a list of communication qubit pairs to connect 2 qubits.

        Takes two computation qubits on different QPU's, determines the reachable
        communication qubits for each via local swaps, then returns all pairs
        of these reachable comm qubits that are connected via remote edge.

        Args:
            qubit_a: The first qubit ID.
            qubit_b: The second qubit ID.

        Returns:
            A list of tuples, where each tuple contains a pair of communication
            qubit IDs (comm_a, comm_b) that can be used to connect qubit_a and
            qubit_b via remote operations.

        Raises:
            ValueError: If either qubit is unknown, if they are on the same QPU,
                or if no communication pairs can be found to connect them.
        """
        # Ensure qubits are on different QPUs
        if qubit_a.qpu_id == qubit_b.qpu_id:
            raise ValueError(
                "Qubits must be on different QPUs to find communication pairs."
            )

        # Ensure both qubits are computation qubits
        if not qubit_a.is_computation or not qubit_b.is_computation:
            raise ValueError(
                "Both qubits must be computation qubits to find communication "
                "pairs."
            )

        comms_a = self._get_reachable_comm_qubits(qubit_a)
        comms_b = self._get_reachable_comm_qubits(qubit_b)

        comm_pairs: set[tuple[PhysicalQubit, PhysicalQubit]] = set()
        for comm_a in comms_a:
            for comm_b in comms_b:
                if (
                    self._graph.has_edge(comm_a, comm_b)
                    and self._graph.edges[comm_a, comm_b].get(
                        "connection_type"
                    )
                    == "remote"
                ):
                    pair = (comm_a, comm_b)
                    comm_pairs.add(pair)
        return sorted(
            comm_pairs,
            key=lambda pair: (pair[0].label, pair[1].label),
        )

    def _get_shortest_path(self, source: PhysicalQubit) -> list[PhysicalQubit]:
        """Return shortest path from source to nearest local comm qubit."""
        source_qpu = source.qpu_id
        paths_from_source = nx.single_source_shortest_path(self._graph, source)
        reachable_candidates: list[
            tuple[PhysicalQubit, list[PhysicalQubit]]
        ] = [
            (candidate, path)
            for candidate, path in paths_from_source.items()
            if candidate.qpu_id == source_qpu and candidate.is_communication
        ]
        if not reachable_candidates:
            raise ValueError(
                "No path found from source to any communication qubit on "
                f"QPU {source_qpu!r}."
            )
        _, best_path = min(
            reachable_candidates,
            key=lambda item: (len(item[1]), item[0].label),
        )
        return best_path

    def _get_reachable_comm_qubits(
        self, source: PhysicalQubit
    ) -> list[PhysicalQubit]:
        """Return a list of communication qubits reachable from the source qubit.

        Args:
            source: Source qubit ID.

        Returns:
            A list of communication qubit IDs that are reachable from the source
            qubit via local connections.

        Raises:
            ValueError: If source is unknown or no communication qubits are
                reachable from the source.
        """
        local_graph = self._local_only_graph()
        reachable_nodes = nx.single_source_shortest_path_length(
            local_graph, source
        )
        comm_qubits = [
            node_id
            for node_id in reachable_nodes
            if node_id.is_communication and node_id.qpu_id == source.qpu_id
        ]
        if not comm_qubits:
            raise ValueError(
                f"No communication qubits reachable from source {source!r}."
            )
        return sorted(comm_qubits, key=lambda qubit: qubit.label)

    def _local_only_graph(self) -> nx.Graph:
        """Return a view of the network graph that contains only local edges."""
        local_graph = nx.Graph()
        local_graph.add_nodes_from(self._graph.nodes(data=True))
        local_graph.add_edges_from(
            (u, v, data)
            for u, v, data in self._graph.edges(data=True)
            if data.get("connection_type") == "local"
        )
        return local_graph

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
        labels = {node: node.label for node in self._graph.nodes}
        nx.draw_networkx_labels(
            self._graph,
            pos,
            labels=labels,
            font_size=12,
            font_family="sans-serif",
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

    def _get_local_edges(
        self,
    ) -> list[tuple[PhysicalQubit, PhysicalQubit]]:
        """Get all local connection edges from the graph.

        Returns:
            Local connection edges.
        """
        return [
            (u, v)
            for u, v, data in self._graph.edges(data=True)
            if data.get("connection_type") == "local"
        ]

    def _get_remote_edges(
        self,
    ) -> list[tuple[PhysicalQubit, PhysicalQubit]]:
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
    ) -> list[dict[str, list[PhysicalQubit]]]:
        """Return computation and communication qubits for each processor."""
        processors = self._network_data["processors"]
        sorted_processor_ids = sorted(
            processors.keys(),
            key=_processor_sort_key,
        )

        grouped: list[dict[str, list[PhysicalQubit]]] = []
        for proc_id in sorted_processor_ids:
            processor = processors[proc_id]
            qubits = processor.get("qubits", [])
            if isinstance(qubits, dict):
                grouped.append(
                    {
                        "computation": [
                            self._resolve_qubit_node(qubit_id)
                            for qubit_id in qubits.get("computation", [])
                        ],
                        "communication": [
                            self._resolve_qubit_node(qubit_id)
                            for qubit_id in qubits.get("communication", [])
                        ],
                    }
                )
                continue

            comp_ids: list[PhysicalQubit] = []
            comm_ids: list[PhysicalQubit] = []
            for qubit_id in _normalize_qubit_ids(qubits):
                if qubit_id not in self._raw_id_to_qubit:
                    raise ValueError(
                        f"Processor references unknown qubit ID {qubit_id!r}."
                    )
                network_qubit = self._raw_id_to_qubit[qubit_id]
                qubit_type = self._qubit_type_map[network_qubit]
                if qubit_type == "computation":
                    comp_ids.append(network_qubit)
                elif qubit_type == "communication":
                    comm_ids.append(network_qubit)
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

    def _resolve_qubit_node(self, qubit_id: object) -> PhysicalQubit:
        """Resolve raw or structured qubit identifier to a graph node."""
        if isinstance(qubit_id, PhysicalQubit):
            if qubit_id not in self._graph:
                raise ValueError(f"Unknown qubit ID: {qubit_id!r}.")
            return qubit_id
        raw_id = _normalize_qubit_id(qubit_id)
        if raw_id not in self._raw_id_to_qubit:
            raise ValueError(f"Unknown qubit ID: {qubit_id!r}.")
        return self._raw_id_to_qubit[raw_id]


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


def _normalize_processor_id(processor_id: object) -> int:
    """Normalize processor IDs to integers."""
    if isinstance(processor_id, int):
        return processor_id
    if isinstance(processor_id, str) and processor_id.isdigit():
        return int(processor_id)
    raise ValueError(
        "Processor IDs must be integers or numeric strings. "
        f"Received {processor_id!r}."
    )


def _resolve_local_qubit_index(
    qubit_id: int | str,
    qpu_id: int,
    qubit_type: str,
    local_index: object,
    next_local_idx: dict[tuple[int, str], int],
) -> int:
    """Resolve per-QPU per-type local index for a qubit."""
    if isinstance(local_index, int):
        key = (qpu_id, qubit_type)
        next_local_idx[key] = max(next_local_idx.get(key, 0), local_index + 1)
        return local_index
    parsed = _parse_formatted_qubit_id(qubit_id)
    if parsed is not None:
        _, _, parsed_index = parsed
        key = (qpu_id, qubit_type)
        next_local_idx[key] = max(next_local_idx.get(key, 0), parsed_index + 1)
        return parsed_index
    key = (qpu_id, qubit_type)
    resolved = next_local_idx.get(key, 0)
    next_local_idx[key] = resolved + 1
    return resolved


def _parse_formatted_qubit_id(
    qubit_id: int | str,
) -> tuple[str, int, int] | None:
    """Parse q/c_<qpu>_<idx> formatted IDs."""
    if not isinstance(qubit_id, str):
        return None
    match = re.fullmatch(r"([qc])_(\d+)_(\d+)", qubit_id)
    if match is None:
        return None
    prefix = match.group(1)
    qpu_token = _normalize_processor_id(match.group(2))
    local_idx = int(match.group(3))
    return prefix, qpu_token, local_idx


def _processor_sort_key(processor_id: str) -> tuple[int, int]:
    """Sort processor IDs numerically."""
    if not processor_id.isdigit():
        raise ValueError(
            "Processor IDs in network JSON must be numeric strings. "
            f"Received {processor_id!r}."
        )
    return (0, int(processor_id))


def _network_qubit_sort_key(
    qubit: PhysicalQubit,
) -> tuple[tuple[int, int], int]:
    """Sort qubits by QPU ID then local qubit index."""
    qpu_key: tuple[int, int] = (0, qubit.qpu_id)
    return (qpu_key, qubit.qubit_id)


def _ordered_qpu_pair(qpu_a: int, qpu_b: int) -> tuple[int, int]:
    # TODO: go through this - relied on codex refactor for time crunch
    """Return a normalized ordered QPU pair key."""
    if qpu_a <= qpu_b:
        return qpu_a, qpu_b
    return qpu_b, qpu_a


def _reconstruct_qpu_path(
    # TODO: go through this - relied on codex refactor for time crunch
    predecessor: dict[int, int | None],
    target_qpu_id: int,
) -> list[int]:
    """Reconstruct a QPU path from predecessor map."""
    path = [target_qpu_id]
    current = target_qpu_id
    while predecessor[current] is not None:
        prev = predecessor[current]
        path.append(prev)
        current = prev
    path.reverse()
    return path


def _route_length(path: list[int]) -> int:
    # TODO: go through this - relied on codex refactor for time crunch
    """Return the number of intermediary QPUs in a route."""
    if len(path) <= 1:
        return 0
    return max(0, len(path) - 2)
