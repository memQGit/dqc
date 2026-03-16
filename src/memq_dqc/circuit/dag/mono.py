# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Monolithic DAG representation for circuit operations."""

from __future__ import annotations

import networkx as nx

from memq_dqc.circuit.layer import Layer
from memq_dqc.circuit.op import Op
from memq_dqc.preprocessing.qasm.types import CircuitQubit


class CircuitDAG:
    """Directed acyclic graph for a circuit's operations.

    The DAG captures dependencies between operations and provides layered
    views suitable for scheduling and partitioning. Circuit-level metadata
    such as statements and operation lists live on the higher-level circuit
    model rather than on this DAG.
    """

    def __init__(self, ops: list[Op]) -> None:
        """Initialize the DAG representation for operations in source order.

        Args:
            ops: Operations in source order.
        """
        self._ops = ops
        self.graph: nx.DiGraph = self._build_dag()
        self.layers: list[Layer] = self._extract_layers()
        self.depth = len(self.layers)

    # Private Methods
    def _build_dag(self) -> nx.DiGraph:
        """Build the dependency graph for the circuit operations.

        Returns:
            Directed acyclic graph of operation dependencies.
        """
        graph = nx.DiGraph()

        # Populate nodes of DAG
        for op in self._ops:
            graph.add_node(op.op_id, op=op, name=op.name, qubits=op.qubits)

        # Track the last operation touching each qubit to form directed edges
        last_op_on_qubit: dict[CircuitQubit, int] = {}
        for op in self._ops:
            for qubit in op.qubits:
                # Previous op exists on this qubit, so current op depends on it.
                if qubit in last_op_on_qubit:
                    prev_op_id = last_op_on_qubit[qubit]
                    # If edge already exists, add qubit to dependency edge data.
                    if graph.has_edge(prev_op_id, op.op_id):
                        graph[prev_op_id][op.op_id]["qubits"].add(qubit)
                    # Otherwise, create new edge with set containing this qubit
                    else:
                        graph.add_edge(prev_op_id, op.op_id, qubits={qubit})
                last_op_on_qubit[qubit] = op.op_id

        return graph

    def _extract_layers(self) -> list[Layer]:
        """Extract layers of operations from the DAG.

        Returns:
            Layers of operations that can be executed in parallel.
        """
        in_degree_map = dict(self.graph.in_degree())
        # Initial Nodes have in-degree of 0
        ready_nodes = [
            node_id for node_id, degree in in_degree_map.items() if degree == 0
        ]

        layers: list[Layer] = []

        while ready_nodes:
            current_layer: list[Op] = []
            next_layer_nodes: set[int] = set()

            for node_id in ready_nodes:
                op = self.graph.nodes[node_id]["op"]
                current_layer.append(op)

                # Move to next layer by reducing in-degrees of successor nodes
                for successor in self.graph.successors(node_id):
                    in_degree_map[successor] -= 1
                    if in_degree_map[successor] == 0:
                        next_layer_nodes.add(successor)

            layers.append(Layer(tuple(current_layer)))
            ready_nodes = list(next_layer_nodes)

        return layers
