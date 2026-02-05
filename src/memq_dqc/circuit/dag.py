# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""DAG representation for OpenQASM 3 quantum circuits."""

from __future__ import annotations

import networkx as nx
from openqasm3 import ast

from memq_dqc.circuit.layers import Layer
from memq_dqc.circuit.ops import Op
from memq_dqc.qasm.cleaning import CleanedQuantumGate, CleanedStatement
from memq_dqc.qasm.types import Qubit
from memq_dqc.qasm.types import Qubit
from memq_dqc.qasm import extract_cleaned_statements


class CircuitDAG:
    """Directed Acyclic Graph (DAG) for an OpenQASM 3 circuit.

    The DAG captures operation dependencies and provstatement_ides layered views
    suitable f.or scheduling and partitioning.
    """

    def __init__(self, program: ast.Program) -> None:
        """Initialize the DAG representation for a quantum program.

        Args:
            program: The OpenQASM 3 program from which to extract operations
                and build the corresponding directed acyclic graph.
        """
        self.program = program
        self.statements = extract_cleaned_statements(program)
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
        g = nx.DiGraph()

        for op in self.ops:
            g.add_node(op.op_id, op=op, name=op.name, qubits=op.qubits)

        # track last operation on each qubit
        last_op_on_qubit: dict[Qubit, int] = {}
        for op in self.ops:
            for q in op.qubits:
                # Previous op exists on this qubit, so current op depends on it
                if q in last_op_on_qubit:
                    prev_op_id = last_op_on_qubit[q]
                    # Check if edge already exists, add qubit to set of qubits
                    if g.has_edge(prev_op_id, op.op_id):
                        g[prev_op_id][op.op_id]["qubits"].add(q)
                    # Otherwise, create new edge with set containing this qubit
                    else:
                        g.add_edge(prev_op_id, op.op_id, qubits={q})
                last_op_on_qubit[q] = op.op_id

        return g

    def _extract_ops(self) -> list[Op]:
        """Extract operations from the program in source order.

        Returns:
            Operations extracted in program order.
        """
        program = self.program
        ops: list[Op] = []
        num_qubits = 0
        qubits = []
        statements = self.statements

        # Extract operations (gates & measurements) from statements
        for statement_id, statement in enumerate(statements):
            if statement is None:
                continue
            if statement.is_op:
                op_id = len(ops)
                if statement.name == "measure":
                    ops.append(
                        Op(
                            op_id=op_id,
                            statement_id=statement_id,
                            name=statement.name,
                            qubits=(
                                Qubit(
                                    statement.qubit.register_name,
                                    statement.qubit.index,
                                ),
                            ),
                            node=statement.node,
                        )
                    )
                else:
                    ops.append(
                        Op(
                            op_id=op_id,
                            statement_id=statement_id,
                            name=statement.name,
                            qubits=tuple(
                                Qubit(q.register_name, q.index)
                                for q in statement.qubits
                            ),
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
        degree_zero_nodes = [
            node for node, degree in in_degree_map.items() if degree == 0
        ]

        layers: list[Layer] = []

        while degree_zero_nodes:
            current_layer: list[Op] = []
            next_layer_nodes: set[int] = set()

            for node in degree_zero_nodes:
                op = self.graph.nodes[node]["op"]
                current_layer.append(op)

                # Move to next layer by reducing in-degrees of successor nodes
                for _, succ in self.graph.edges(node):
                    in_degree_map[succ] -= 1
                    if in_degree_map[succ] == 0:
                        next_layer_nodes.add(succ)

            layers.append(Layer(tuple(current_layer)))
            degree_zero_nodes = list(next_layer_nodes)

        return layers

    def extract_layers(self) -> list[Layer]:
        """Return the extracted operation layers for the circuit.

        Returns:
            Operation layers that can be executed in parallel.
        """
        return self.layers


class DistributedCircuitDAG(CircuitDAG):
    """DAG representation with remote gate names applied.

    Attributes:
        num_remote_gates: Number of operations tagged as remote gates.
    """

    def __init__(
        self,
        base_dag: CircuitDAG,
        remote_statement_ids: set[int],
    ) -> None:
        """Initialize a distributed DAG from an existing DAG.

        Args:
            base_dag: Original circuit DAG.
            remote_statement_ids: Statement indices to rename as remote gates.
        """
        self.program = base_dag.program
        self.statements = self._build_statements(
            base_dag.statements,
            remote_statement_ids,
        )
        self.ops = self._build_ops(base_dag.ops, remote_statement_ids)
        self.num_remote_gates = self._count_remote_gates(
            remote_statement_ids
        )
        self.num_two_qubit_gates = self._count_two_qubit_gates()
        self.graph = self._build_dag()
        self.layers = self._extract_layers()
        self.depth = len(self.layers)

    @staticmethod
    def _build_statements(
        statements: list[CleanedStatement],
        remote_statement_ids: set[int],
    ) -> list[CleanedStatement]:
        distributed_statements = []
        for idx, statement in enumerate(statements):
            if idx in remote_statement_ids and isinstance(
                statement, CleanedQuantumGate
            ):
                distributed_statements.append(
                    CleanedQuantumGate(
                        statement_type=statement.statement_type,
                        node=statement.node,
                        is_op=statement.is_op,
                        name=f"r{statement.name}",
                        qubits=statement.qubits,
                    )
                )
            else:
                distributed_statements.append(statement)
        return distributed_statements

    @staticmethod
    def _build_ops(
        ops: list[Op],
        remote_statement_ids: set[int],
    ) -> list[Op]:
        distributed_ops = []
        for op in ops:
            name = op.name
            if op.statement_id in remote_statement_ids:
                name = f"r{name}"
            distributed_ops.append(
                Op(
                    op_id=op.op_id,
                    statement_id=op.statement_id,
                    name=name,
                    qubits=op.qubits,
                    node=op.node,
                )
            )
        return distributed_ops

    def _count_remote_gates(
        self,
        remote_statement_ids: set[int],
    ) -> int:
        """Count operations marked as remote.

        Args:
            remote_statement_ids: Statement indices corresponding to remote
                operations.

        Returns:
            The number of operations tagged as remote gates.
        """
        return sum(
            1 for op in self.ops if op.statement_id in remote_statement_ids
        )
