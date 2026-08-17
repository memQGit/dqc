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

"""NetworkX-based visualization helpers for circuit DAGs."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, TypeAlias

import matplotlib.pyplot as plt
import networkx as nx
from matplotlib.axes import Axes

from memq_dqc.circuit import Circuit, DistributedCircuit
from memq_dqc.circuit.dag import CircuitDAG
from memq_dqc.preprocessing.qasm.types import CircuitQubit

__all__ = [
    "build_dag_networkx_graph",
    "plot_circuit_dag",
    "plot_dag",
    "plot_distributed_dag",
]

_INPUT_NODE_COLOR = "#71f53d"
_OPERATION_NODE_COLOR = "#b2c9ff"
_OUTPUT_NODE_COLOR = "#ff4a4a"
_EDGE_COLOR = "#4b5563"
_VisualNode: TypeAlias = tuple[Any, ...]


def build_dag_networkx_graph(dag: CircuitDAG) -> nx.DiGraph:
    """Build an augmented NetworkX graph for DAG visualization.

    The visualization graph adds synthetic input and output nodes for each
    qubit wire so the rendered layout reads like a circuit-flow graph rather
    than a generic dependency diagram.

    Args:
        dag: Circuit DAG to augment for visualization.

    Returns:
        A directed graph containing qubit input nodes, operation nodes, qubit
        output nodes, and dependency edges annotated by qubit labels.
    """
    graph = nx.DiGraph()
    qubits = _sorted_qubits(dag)

    for qubit_index, qubit in enumerate(qubits):
        label = _format_qubit_label(qubit)
        input_node = _input_node_id(qubit)
        output_node = _output_node_id(qubit)
        graph.add_node(
            input_node,
            kind="input",
            label=label,
            qubits=(qubit,),
            wire_index=qubit_index,
        )
        graph.add_node(
            output_node,
            kind="output",
            label=label,
            qubits=(qubit,),
            wire_index=qubit_index,
        )

    ops_by_qubit: dict[CircuitQubit, list[_VisualNode]] = defaultdict(list)
    for node_id in sorted(dag.graph.nodes):
        op = dag.graph.nodes[node_id]["op"]
        visual_node = ("op", op.op_id)
        graph.add_node(
            visual_node,
            kind="operation",
            label=op.name,
            op=op,
            qubits=op.qubits,
        )
        for qubit in op.qubits:
            ops_by_qubit[qubit].append(visual_node)

    for qubit in qubits:
        previous_node: _VisualNode = _input_node_id(qubit)
        for current_node in ops_by_qubit[qubit]:
            _add_qubit_edge(
                graph,
                previous_node,
                current_node,
                qubit,
            )
            previous_node = current_node
        _add_qubit_edge(
            graph,
            previous_node,
            _output_node_id(qubit),
            qubit,
        )

    return graph


def plot_dag(
    dag: CircuitDAG,
    *,
    ax: Axes | None = None,
    title: str | None = None,
    show_edge_labels: bool = False,
) -> Axes:
    """Render a circuit DAG as a top-to-bottom NetworkX graph.

    Args:
        dag: DAG to visualize.
        ax: Existing axes to draw into. A new figure and axes are created when
            omitted.
        title: Optional plot title.
        show_edge_labels: Whether qubit labels should be shown on edges.

    Returns:
        The Matplotlib axes containing the rendered DAG.
    """
    graph = build_dag_networkx_graph(dag)
    positions = _build_dag_positions(graph)

    if ax is None:
        _, ax = plt.subplots(figsize=_figure_size_for_graph(graph))

    node_kinds = {
        "input": [],
        "operation": [],
        "output": [],
    }
    for node, data in graph.nodes(data=True):
        node_kinds[data["kind"]].append(node)

    nx.draw_networkx_edges(
        graph,
        positions,
        ax=ax,
        edge_color=_EDGE_COLOR,
        arrows=True,
        arrowstyle="-|>",
        arrowsize=14,
        width=1.4,
        min_source_margin=10,
        min_target_margin=10,
    )
    nx.draw_networkx_nodes(
        graph,
        positions,
        nodelist=node_kinds["input"],
        node_color=_INPUT_NODE_COLOR,
        edgecolors="#355e1d",
        linewidths=1.0,
        node_size=760,
        ax=ax,
    )
    nx.draw_networkx_nodes(
        graph,
        positions,
        nodelist=node_kinds["operation"],
        node_color=_OPERATION_NODE_COLOR,
        edgecolors="#466392",
        linewidths=1.0,
        node_size=920,
        ax=ax,
    )
    nx.draw_networkx_nodes(
        graph,
        positions,
        nodelist=node_kinds["output"],
        node_color=_OUTPUT_NODE_COLOR,
        edgecolors="#8f2424",
        linewidths=1.0,
        node_size=760,
        ax=ax,
    )
    nx.draw_networkx_labels(
        graph,
        positions,
        labels={node: data["label"] for node, data in graph.nodes(data=True)},
        font_size=9,
        font_family="sans-serif",
        ax=ax,
    )

    if show_edge_labels:
        nx.draw_networkx_edge_labels(
            graph,
            positions,
            edge_labels={
                (u, v): data["label"] for u, v, data in graph.edges(data=True)
            },
            font_size=7,
            font_color="#374151",
            label_pos=0.55,
            rotate=False,
            bbox={"alpha": 0.0, "pad": 0.0},
            ax=ax,
        )

    if title is not None:
        ax.set_title(title)
    ax.set_axis_off()
    ax.invert_yaxis()
    ax.margins(x=0.16, y=0.08)
    return ax


def plot_circuit_dag(
    circuit_or_dag: Circuit | CircuitDAG,
    *,
    ax: Axes | None = None,
    title: str = "Circuit DAG",
    show_edge_labels: bool = False,
) -> Axes:
    """Render the monolithic circuit DAG.

    Args:
        circuit_or_dag: Circuit or DAG to plot.
        ax: Existing axes to draw into.
        title: Plot title.
        show_edge_labels: Whether qubit labels should be shown on edges.

    Returns:
        The Matplotlib axes containing the rendered DAG.
    """
    return plot_dag(
        _resolve_circuit_dag(circuit_or_dag),
        ax=ax,
        title=title,
        show_edge_labels=show_edge_labels,
    )


def plot_distributed_dag(
    circuit_or_dag: Circuit | DistributedCircuit | CircuitDAG,
    *,
    ax: Axes | None = None,
    title: str = "Distributed DAG",
    show_edge_labels: bool = False,
) -> Axes:
    """Render the distributed circuit DAG.

    Args:
        circuit_or_dag: Circuit, distributed circuit wrapper, or DAG to plot.
        ax: Existing axes to draw into.
        title: Plot title.
        show_edge_labels: Whether qubit labels should be shown on edges.

    Returns:
        The Matplotlib axes containing the rendered DAG.

    Raises:
        ValueError: If the circuit does not yet have a distributed DAG.
    """
    return plot_dag(
        _resolve_distributed_dag(circuit_or_dag),
        ax=ax,
        title=title,
        show_edge_labels=show_edge_labels,
    )


def _resolve_circuit_dag(circuit_or_dag: Circuit | CircuitDAG) -> CircuitDAG:
    """Resolve a monolithic DAG from a circuit wrapper or DAG object."""
    if isinstance(circuit_or_dag, CircuitDAG):
        return circuit_or_dag
    return circuit_or_dag.mono.dag


def _resolve_distributed_dag(
    circuit_or_dag: Circuit | DistributedCircuit | CircuitDAG,
) -> CircuitDAG:
    """Resolve a distributed DAG from supported visualization inputs."""
    if isinstance(circuit_or_dag, CircuitDAG):
        return circuit_or_dag
    if isinstance(circuit_or_dag, DistributedCircuit):
        return circuit_or_dag.dag
    if circuit_or_dag.distributed is None:
        raise ValueError(
            "Circuit.distributed is not populated. Call build_distributed() "
            "before plotting the distributed DAG."
        )
    return circuit_or_dag.distributed.dag


def _build_dag_positions(
    graph: nx.DiGraph,
) -> dict[_VisualNode, tuple[float, float]]:
    """Build deterministic node positions for a vertical DAG layout."""
    qubits = _visual_graph_qubits(graph)
    wire_x = {qubit: float(index) for index, qubit in enumerate(qubits)}
    ranks = _node_ranks(graph)
    base_x: dict[_VisualNode, float] = {}

    for node, data in graph.nodes(data=True):
        node_qubits: tuple[CircuitQubit, ...] = data["qubits"]
        if data["kind"] in {"input", "output"}:
            base_x[node] = wire_x[node_qubits[0]]
            continue
        base_x[node] = sum(wire_x[qubit] for qubit in node_qubits) / len(
            node_qubits
        )

    positions: dict[_VisualNode, tuple[float, float]] = {}
    min_spacing = 0.85
    for rank in sorted(set(ranks.values())):
        rank_nodes = sorted(
            (node for node in graph.nodes if ranks[node] == rank),
            key=lambda node: (
                base_x[node],
                graph.nodes[node]["kind"],
                graph.nodes[node]["label"],
            ),
        )
        previous_x: float | None = None
        for node in rank_nodes:
            current_x = base_x[node]
            if previous_x is not None and current_x - previous_x < min_spacing:
                current_x = previous_x + min_spacing
            positions[node] = (current_x, float(rank))
            previous_x = current_x

    return positions


def _node_ranks(graph: nx.DiGraph) -> dict[_VisualNode, int]:
    """Compute the longest-path rank for every node in a DAG."""
    ranks: dict[_VisualNode, int] = {}
    for node in nx.topological_sort(graph):
        predecessor_ranks = [ranks[pred] for pred in graph.predecessors(node)]
        ranks[node] = (
            0 if not predecessor_ranks else max(predecessor_ranks) + 1
        )
    return ranks


def _figure_size_for_graph(graph: nx.DiGraph) -> tuple[float, float]:
    """Estimate a readable figure size for a DAG plot."""
    qubits = len(_visual_graph_qubits(graph))
    depth = max(_node_ranks(graph).values(), default=1) + 1
    width = max(6.0, qubits * 2.0)
    height = max(6.0, depth * 0.95)
    return (width, height)


def _visual_graph_qubits(graph: nx.DiGraph) -> list[CircuitQubit]:
    """Extract the ordered set of qubits represented in a visual graph."""
    qubits = {
        qubit for _, data in graph.nodes(data=True) for qubit in data["qubits"]
    }
    return sorted(qubits, key=lambda qubit: (qubit.register_name, qubit.index))


def _sorted_qubits(dag: CircuitDAG) -> list[CircuitQubit]:
    """Return all DAG qubits in a stable display order."""
    qubits = {
        qubit
        for _, data in dag.graph.nodes(data=True)
        for qubit in data["qubits"]
    }
    return sorted(qubits, key=lambda qubit: (qubit.register_name, qubit.index))


def _add_qubit_edge(
    graph: nx.DiGraph,
    source: _VisualNode,
    target: _VisualNode,
    qubit: CircuitQubit,
) -> None:
    """Add or merge a qubit dependency edge in the visualization graph."""
    qubit_label = _format_qubit_label(qubit)
    if graph.has_edge(source, target):
        graph[source][target]["qubit_labels"].add(qubit_label)
        graph[source][target]["label"] = ", ".join(
            sorted(graph[source][target]["qubit_labels"])
        )
        return

    graph.add_edge(
        source,
        target,
        qubit_labels={qubit_label},
        label=qubit_label,
    )


def _format_qubit_label(qubit: CircuitQubit) -> str:
    """Format a circuit qubit for display."""
    return f"{qubit.register_name}[{qubit.index}]"


def _input_node_id(qubit: CircuitQubit) -> _VisualNode:
    """Build the stable identifier for a qubit input node."""
    return ("in", qubit.register_name, qubit.index)


def _output_node_id(qubit: CircuitQubit) -> _VisualNode:
    """Build the stable identifier for a qubit output node."""
    return ("out", qubit.register_name, qubit.index)
