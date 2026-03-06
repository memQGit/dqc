# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Monolithic DAG representation for OpenQASM 3 quantum circuits."""

from __future__ import annotations

import networkx as nx
from openqasm3 import ast

from memq_dqc.circuit.layers import Layer
from memq_dqc.circuit.ops import Op
from memq_dqc.preprocessing.qasm import extract_cleaned_statements
from memq_dqc.preprocessing.qasm.types import CircuitQubit, CleanedStatement


class CircuitDAG:
    """Directed Acyclic Graph (DAG) for an OpenQASM 3 circuit.

    The DAG captures operation dependencies and provides layered views suitable
    for scheduling and partitioning.
    """

    def __init__(self, program: ast.Program) -> None:
        """Initialize the DAG representation for a quantum program.

        Args:
            program: The OpenQASM 3 program from which to extract operations
                and build the corresponding directed acyclic graph.
        """
        self.program = program
        cleaned_statements = extract_cleaned_statements(program)
        self.num_barrier_statements = sum(
            1
            for statement in cleaned_statements
            if isinstance(statement, CleanedStatement)
            and isinstance(statement.node, ast.QuantumBarrier)
        )
        self.statements = [
            statement
            for statement in cleaned_statements
            if not isinstance(statement.node, ast.QuantumBarrier)
        ]
        self.ops: list[Op] = self._extract_ops()
        self.num_two_qubit_gates = self._count_two_qubit_gates()
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

        for op in self.ops:
            graph.add_node(op.op_id, op=op, name=op.name, qubits=op.qubits)

        # Track the last operation touching each qubit.
        last_op_on_qubit: dict[CircuitQubit, int] = {}
        for op in self.ops:
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

    def _extract_ops(self) -> list[Op]:
        """Extract operations from the program in source order.

        Returns:
            Operations extracted in program order.
        """
        ops: list[Op] = []

        # Extract operations (gates & measurements) from statements
        for statement_id, statement in enumerate(self.statements):
            if not statement.is_op:
                continue
            op_id = len(ops)
            if statement.name == "measure":
                if statement.qubit is None:
                    raise ValueError("Measurement statement missing qubit.")
                qubits: tuple[CircuitQubit, ...] = (
                    CircuitQubit(
                        statement.qubit.register_name,
                        statement.qubit.index,
                    ),
                )
            else:
                qubits = tuple(
                    CircuitQubit(qubit.register_name, qubit.index)
                    for qubit in statement.qubits
                )
            ops.append(
                Op(
                    op_id=op_id,
                    statement_id=statement_id,
                    name=statement.name,
                    qubits=qubits,
                    node=statement.node,
                )
            )
        return ops

    def _count_two_qubit_gates(self) -> int:
        """Count operations that act on exactly two qubits.

        Returns:
            The number of two-qubit operations in the circuit.
        """
        return sum(1 for op in self.ops if op.is_two_qubit)

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

    def extract_layers(self) -> list[Layer]:
        """Return the extracted operation layers for the circuit.

        Returns:
            Operation layers that can be executed in parallel.
        """
        return self.layers
