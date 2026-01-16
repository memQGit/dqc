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


def build_network_graph(
    network_json_filename: str,
) -> tuple[nx.Graph, dict[int, str]]:
    """Generate a NetworkX graph from a network specification JSON file.

    Args:
        network_json_filename: The filename of the network specification JSON file.

    Returns:
        A tuple containing:
            - A NetworkX graph representing the network
            - A mapping of qubit IDs to their types

    """
    # Load network specification JSON file
    with open(network_json_filename) as f:
        network_data = json.load(f)

    graph = nx.Graph()
    qubit_type_map = {}
    qubits = network_data["qubits"]
    for qubit, data in qubits.items():
        # Mark qubit type (computation or communication)
        qubit_type_map[int(qubit)] = data.get("type")
        # Add qubit in graph and unpack its attributes to store as node data
        graph.add_node(int(qubit), **data)
    for qubit, data in qubits.items():
        local_connects = data.get("localConnections", [])
        remote_connects = data.get("remoteConnections", [])
        for local in local_connects:
            graph.add_edge(int(qubit), int(local), connection_type="local")
        for remote in remote_connects:
            graph.add_edge(int(qubit), int(remote), connection_type="remote")

    return (graph, qubit_type_map)


def display_network_graph(graph: nx.Graph) -> None:
    """Display the network graph using Matplotlib.

    Args:
        graph: The NetworkX graph representing the network.

    """
    local_edges = [
        (u, v)
        for u, v, data in graph.edges(data=True)
        if data.get("connection_type") == "local"
    ]

    remote_edges = [
        (u, v)
        for u, v, data in graph.edges(data=True)
        if data.get("connection_type") == "remote"
    ]

    pos = nx.spring_layout(graph)
    nx.draw_networkx_nodes(graph, pos, node_size=700)
    nx.draw_networkx_labels(graph, pos, font_size=12, font_family="sans-serif")
    nx.draw_networkx_edges(
        graph,
        pos,
        edgelist=local_edges,
        width=2,
        edge_color="blue",
        label="Local",
        style="solid",
    )

    nx.draw_networkx_edges(
        graph,
        pos,
        edgelist=remote_edges,
        width=2,
        edge_color="red",
        label="Remote",
        style="dashed",
    )

    plt.show()
