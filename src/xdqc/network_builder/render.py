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

"""Off-screen PNG rendering of a network graph for the builder preview.

Unlike :meth:`xdqc.network.NetworkGraph.display`, which opens a blocking
interactive window, :func:`render_png` draws onto an Agg canvas and returns
the encoded image, making it safe to call from a web request handler.
"""

import io

import networkx as nx
from matplotlib.backends.backend_agg import FigureCanvasAgg
from matplotlib.figure import Figure

from ..network import NetworkGraph

#: Layout seed, fixed so a given network always renders identically.
LAYOUT_SEED = 42

# Palette tuned for the builder's dark UI panel.
NODE_COLOR = "#9D4FB8"
NODE_EDGE = "#DEC2E9"
LOCAL_COLOR = "#8A6F96"
REMOTE_COLOR = "#C067D2"
REMOTE_LABEL = "#E7C9F0"
TEXT_COLOR = "#F2EFF7"


def _format_fidelity(value: float) -> str:
    """Render a fidelity as a short label, trimming trailing zeros.

    Args:
        value: Link fidelity between 0 and 1.

    Returns:
        The fidelity formatted for display, e.g. ``"1"`` or ``"0.85"``.
    """
    return f"{value:.2f}".rstrip("0").rstrip(".")


def render_png(network: NetworkGraph) -> bytes:
    """Render a network graph to a transparent PNG.

    Local connections are drawn as solid muted edges and remote
    connections as bold dashed edges. Remote edges carrying a ``fidelity``
    attribute are labelled with its value.

    Args:
        network: The network to draw.

    Returns:
        The encoded PNG image.
    """
    graph = network.graph
    figure = Figure(figsize=(10, 8))
    FigureCanvasAgg(figure)
    axes = figure.add_subplot(111)

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

    pos = nx.spring_layout(graph, seed=LAYOUT_SEED)
    labels = {
        node: graph.nodes[node].get("label", str(node))
        for node in graph.nodes()
    }

    nx.draw_networkx_nodes(
        graph,
        pos,
        ax=axes,
        node_size=700,
        node_color=NODE_COLOR,
        edgecolors=NODE_EDGE,
        linewidths=2,
    )
    nx.draw_networkx_labels(
        graph,
        pos,
        ax=axes,
        labels=labels,
        # Labels are five characters wide (``q_0_0``), which overflows a
        # 700pt node at the matplotlib default size.
        font_size=7,
        font_weight="bold",
        font_color=TEXT_COLOR,
    )

    if local_edges:
        nx.draw_networkx_edges(
            graph,
            pos,
            ax=axes,
            edgelist=local_edges,
            width=3,
            edge_color=LOCAL_COLOR,
            style="solid",
        )

    if remote_edges:
        nx.draw_networkx_edges(
            graph,
            pos,
            ax=axes,
            edgelist=remote_edges,
            width=3,
            edge_color=REMOTE_COLOR,
            style="dashed",
        )
        fidelity_labels = {
            (u, v): _format_fidelity(graph.edges[u, v]["fidelity"])
            for u, v in remote_edges
            if graph.edges[u, v].get("fidelity") is not None
        }
        if fidelity_labels:
            nx.draw_networkx_edge_labels(
                graph,
                pos,
                ax=axes,
                edge_labels=fidelity_labels,
                font_size=9,
                font_color=REMOTE_LABEL,
            )

    axes.set_title(
        "Quantum Network Graph",
        fontsize=16,
        fontweight="bold",
        color=TEXT_COLOR,
    )
    axes.axis("off")

    buffer = io.BytesIO()
    figure.savefig(
        buffer,
        format="png",
        dpi=150,
        bbox_inches="tight",
        transparent=True,
    )
    return buffer.getvalue()
