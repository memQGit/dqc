# Copyright 2026 memQ Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Generate network topologies from a few structural parameters.

[generate_network][memq_dqc.network.generation.generate_network] builds the
network JSON that [NetworkGraph][memq_dqc.network.network_graph.NetworkGraph]
loads, following the same conventions as the bundled networks:

- Every QPU has the same number of computation qubits.
- Each pair of linked QPUs is joined by ``links_per_pair`` remote links, and
  every link owns one communication qubit on each side. A QPU therefore has
  ``links_per_pair`` communication qubits per neighbour, numbered in order
  of neighbour id.
- With nearest-neighbour connectivity, computation qubits sit on a row-major
  grid ``ceil(sqrt(n))`` columns wide with 4-way adjacency, and each
  communication qubit attaches to one computation qubit, spaced evenly
  clockwise around the grid's boundary from qubit 0.
- With all-to-all connectivity, every pair of computation qubits is coupled
  and each communication qubit couples to every computation qubit.

Example:
    Generate a four-QPU ring and load it:

    ```python
    import json

    from memq_dqc.network import NetworkGraph, generate_network

    network = generate_network(4, 5, "ring")
    with open("ring.json", "w") as f:
        json.dump(network, f, indent=2)

    graph = NetworkGraph("ring.json")
    ```
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from itertools import combinations
from typing import Any, Literal, TypeAlias

import networkx as nx

QpuArrangement: TypeAlias = Literal["chain", "ring", "hub", "all_to_all"]
IntraQpuConnectivity: TypeAlias = Literal["nearest_neighbor", "all_to_all"]


def generate_network(
    num_qpus: int,
    computation_qubits_per_qpu: int,
    arrangement: QpuArrangement | Sequence[tuple[int, int]] = "chain",
    *,
    intra_qpu: IntraQpuConnectivity = "nearest_neighbor",
    links_per_pair: int = 2,
    coherence_time: float = 100.0,
) -> dict[str, Any]:
    """Generate a network topology with identically sized QPUs.

    Args:
        num_qpus: Number of QPUs, with ids ``0`` to ``num_qpus - 1``.
        computation_qubits_per_qpu: Computation (data) qubits on every QPU.
        arrangement: How the QPUs are linked. ``"chain"`` links QPU ``i`` to
            ``i + 1``; ``"ring"`` also links the last QPU to QPU 0;
            ``"hub"`` links QPU 0 to every other QPU; ``"all_to_all"``
            links every pair. Alternatively, an explicit sequence of
            ``(qpu_a, qpu_b)`` pairs.
        intra_qpu: Coupling between qubits inside each QPU, either
            ``"nearest_neighbor"`` or ``"all_to_all"``.
        links_per_pair: Remote links between each pair of linked QPUs. Use
            at least 2 so qubits can be teleported across a link, which
            routing between QPUs that are not directly linked requires.
        coherence_time: Coherence time recorded on every qubit, in
            microseconds. No current algorithm reads it.

    Returns:
        The network as a JSON-serializable dictionary, in the format
        ``NetworkGraph`` loads.

    Raises:
        ValueError: If a count is below 1, the arrangement is unknown or
            needs more QPUs, or the QPU links reference unknown QPUs,
            contain a self-link, or leave a QPU unreachable.
    """
    if num_qpus < 1:
        raise ValueError("num_qpus must be at least 1.")
    if computation_qubits_per_qpu < 1:
        raise ValueError("computation_qubits_per_qpu must be at least 1.")
    if links_per_pair < 1:
        raise ValueError("links_per_pair must be at least 1.")

    qpu_links = _qpu_links(num_qpus, arrangement)
    neighbors: dict[int, list[int]] = {qpu: [] for qpu in range(num_qpus)}
    for a, b in qpu_links:
        neighbors[a].append(b)
        neighbors[b].append(a)
    for linked in neighbors.values():
        linked.sort()
    n_comp = computation_qubits_per_qpu

    local_edges = _computation_edges(n_comp, intra_qpu)
    boundary = _grid_boundary(n_comp)

    processors: dict[str, Any] = {}
    qubits: dict[str, Any] = {}
    local_connections: list[tuple[str, str]] = []
    for qpu in range(num_qpus):
        n_comm = links_per_pair * len(neighbors[qpu])
        comp_ids = [_qubit_id("q", qpu, i) for i in range(n_comp)]
        comm_ids = [_qubit_id("c", qpu, j) for j in range(n_comm)]
        processors[str(qpu)] = {
            "id": qpu,
            "qubits": {"computation": comp_ids, "communication": comm_ids},
        }

        adjacency: dict[str, list[str]] = {q: [] for q in comp_ids + comm_ids}
        for a, b in local_edges:
            _couple(adjacency, local_connections, comp_ids[a], comp_ids[b])
        for j, comm in enumerate(comm_ids):
            if intra_qpu == "all_to_all":
                attached = comp_ids
            else:
                attached = [comp_ids[boundary[j * len(boundary) // n_comm]]]
            for comp in attached:
                _couple(adjacency, local_connections, comm, comp)

        for index, qubit in enumerate(comp_ids + comm_ids):
            qubits[qubit] = _qubit_entry(
                qubit,
                "computation" if index < n_comp else "communication",
                qpu,
                index,
                sorted(adjacency[qubit], key=_qubit_sort_key),
                coherence_time,
            )

    remote_connections: list[dict[str, Any]] = []
    for a, b in qpu_links:
        for k in range(links_per_pair):
            comm_a = _qubit_id(
                "c", a, neighbors[a].index(b) * links_per_pair + k
            )
            comm_b = _qubit_id(
                "c", b, neighbors[b].index(a) * links_per_pair + k
            )
            qubits[comm_a]["remoteConnections"].append(comm_b)
            qubits[comm_b]["remoteConnections"].append(comm_a)
            remote_connections.append(
                {
                    "qubit1": comm_a,
                    "qubit2": comm_b,
                    "type": "remote",
                    "fidelity": 1,
                }
            )

    connections = [
        {"qubit1": a, "qubit2": b, "type": "local"}
        for a, b in local_connections
    ] + remote_connections
    return {
        "processors": processors,
        "qubits": qubits,
        "connections": connections,
    }


def _qpu_links(
    num_qpus: int,
    arrangement: QpuArrangement | Sequence[tuple[int, int]],
) -> list[tuple[int, int]]:
    """Return the QPU-to-QPU links for an arrangement, without duplicates.

    Named arrangements list their links in walk order, so a ring's closing
    link ``(num_qpus - 1, 0)`` comes last.

    Args:
        num_qpus: Number of QPUs.
        arrangement: Arrangement name or explicit QPU links.

    Returns:
        The QPU links, in order.

    Raises:
        ValueError: If the arrangement is unknown or invalid for
            ``num_qpus``.
    """
    if isinstance(arrangement, str):
        qpus = range(num_qpus)
        if arrangement == "chain":
            return [(qpu, qpu + 1) for qpu in qpus[:-1]]
        if arrangement == "ring":
            if num_qpus < 3:
                raise ValueError("A ring needs at least 3 QPUs.")
            return [(qpu, (qpu + 1) % num_qpus) for qpu in qpus]
        if arrangement == "hub":
            return [(0, qpu) for qpu in qpus[1:]]
        if arrangement == "all_to_all":
            return list(combinations(qpus, 2))
        raise ValueError(
            f"Unknown arrangement {arrangement!r}; expected 'chain', "
            "'ring', 'hub', 'all_to_all', or a list of QPU pairs."
        )

    graph = nx.empty_graph(num_qpus)
    links: list[tuple[int, int]] = []
    for a, b in arrangement:
        if a == b:
            raise ValueError(f"QPU link ({a}, {b}) links a QPU to itself.")
        if not (0 <= a < num_qpus and 0 <= b < num_qpus):
            raise ValueError(
                f"QPU link ({a}, {b}) references a QPU outside "
                f"0..{num_qpus - 1}."
            )
        if not graph.has_edge(a, b):
            graph.add_edge(a, b)
            links.append((a, b))
    if not nx.is_connected(graph):
        raise ValueError(
            "QPU links leave some QPUs unreachable; every QPU must be "
            "connected to the rest of the network."
        )
    return links


def _computation_edges(
    n_comp: int,
    intra_qpu: IntraQpuConnectivity,
) -> list[tuple[int, int]]:
    """Return local couplings between computation qubit indices.

    Args:
        n_comp: Computation qubits per QPU.
        intra_qpu: Intra-QPU connectivity.

    Returns:
        Index pairs ``(a, b)`` with ``a < b``.

    Raises:
        ValueError: If ``intra_qpu`` is unknown.
    """
    if intra_qpu == "all_to_all":
        return list(combinations(range(n_comp), 2))
    if intra_qpu != "nearest_neighbor":
        raise ValueError(
            f"Unknown intra_qpu {intra_qpu!r}; expected 'nearest_neighbor' "
            "or 'all_to_all'."
        )
    columns = math.ceil(math.sqrt(n_comp))
    edges = []
    for index in range(n_comp):
        if (index + 1) % columns and index + 1 < n_comp:
            edges.append((index, index + 1))
        if index + columns < n_comp:
            edges.append((index, index + columns))
    return edges


def _grid_boundary(n_comp: int) -> list[int]:
    """Return the boundary of the computation grid, clockwise from qubit 0.

    The walk covers the top row left to right, the last qubit of each lower
    row, the bottom row right to left, then the first qubit of each middle
    row bottom to top.

    Args:
        n_comp: Computation qubits per QPU.

    Returns:
        Computation qubit indices on the grid boundary, without repeats.
    """
    columns = math.ceil(math.sqrt(n_comp))
    rows = [
        list(range(start, min(start + columns, n_comp)))
        for start in range(0, n_comp, columns)
    ]
    boundary = list(rows[0])
    if len(rows) > 1:
        boundary += [row[-1] for row in rows[1:]]
        boundary += rows[-1][-2::-1]
        boundary += [row[0] for row in rows[-2:0:-1]]
    return boundary


def _couple(
    adjacency: dict[str, list[str]],
    connections: list[tuple[str, str]],
    a: str,
    b: str,
) -> None:
    """Record a local coupling in both directions.

    Args:
        adjacency: Per-qubit local neighbours, updated in place.
        connections: Local couplings in creation order, updated in place.
        a: First qubit id.
        b: Second qubit id.
    """
    adjacency[a].append(b)
    adjacency[b].append(a)
    connections.append((a, b))


def _qubit_id(prefix: str, qpu: int, index: int) -> str:
    """Return a qubit id such as ``q_0_3`` or ``c_1_0``.

    Args:
        prefix: ``"q"`` for computation or ``"c"`` for communication.
        qpu: Owning QPU id.
        index: Index among the QPU's qubits of that type.

    Returns:
        The qubit id.
    """
    return f"{prefix}_{qpu}_{index}"


def _qubit_sort_key(qubit: str) -> tuple[bool, int]:
    """Order computation qubits before communication qubits, then by index.

    Args:
        qubit: A qubit id built by ``_qubit_id``.

    Returns:
        A sort key.
    """
    prefix, _, index = qubit.split("_")
    return prefix == "c", int(index)


def _qubit_entry(
    qubit: str,
    qubit_type: str,
    qpu: int,
    local_index: int,
    local_connections: list[str],
    coherence_time: float,
) -> dict[str, Any]:
    """Return one entry of the ``qubits`` section.

    Args:
        qubit: Qubit id.
        qubit_type: ``"computation"`` or ``"communication"``.
        qpu: Owning QPU id.
        local_index: Position of the qubit within its QPU.
        local_connections: Ids of locally coupled qubits.
        coherence_time: Coherence time in microseconds.

    Returns:
        The qubit entry.
    """
    _, _, index = qubit.split("_")
    return {
        "id": qubit,
        "kind": qubit_type,
        "type": qubit_type,
        "processorId": qpu,
        "localIndex": local_index,
        "label": f"{qubit[0]}({qpu},{index})",
        "localConnections": local_connections,
        "remoteConnections": [],
        "coherenceTime": coherence_time,
        "coherenceTimeUnit": "us",
    }
