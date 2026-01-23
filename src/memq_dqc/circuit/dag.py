# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""DAG representation for OpenQASM 3 quantum circuits."""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
from openqasm3 import ast

from memq_dqc.utils import extract_qubit_index


@dataclass(frozen=True, slots=True)
class Op:
    """A quantum operation in the DAG extracted from an OpenQASM circuit.

    Attributes:
        op_id: Unique operation index in program order.
        name: Gate or instruction name.
        qubits: Qubit indices the operation applies to.
        node: Original OpenQASM AST node.
    """

    op_id: int
    name: str
    qubits: tuple[int, ...]
    node: ast.QASMNode

    @property
    def is_two_qubit(self) -> bool:
        """Return True when the operation acts on two qubits.

        Args:
            None.

        Returns:
            True if the operation spans two qubits, otherwise False.
        """
        return len(self.qubits) == 2


class DAG:
    """Directed Acyclic Graph (DAG) for an OpenQASM 3 circuit.

    Args:
        program: Parsed OpenQASM 3 program to analyze.
    """

    def __init__(self, program: ast.Program) -> None:
        """Initialize the DAG from a parsed OpenQASM program.

        Args:
            program: Parsed OpenQASM 3 program to analyze.
        """
        self.program = program
        self.ops: list[Op] = self._extract_ops()
        self.graph: nx.DiGraph = self._build_dag()

    # Public Methods

    # Private Methods
    def _build_dag(self) -> nx.DiGraph:
        """Build the dependency graph for the circuit operations.

        Args:
            None.

        Returns:
            Directed acyclic graph of operation dependencies.
        """
        g = nx.DiGraph()

        for op in self.ops:
            g.add_node(op.op_id, op=op, name=op.name, qubits=op.qubits)

        # track last operation on each qubit
        last_op_on_qubit: dict[int, int] = {}
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
            List of extracted operations in program order.
        """
        program = self.program
        ops: list[Op] = []
        num_qubits = 0
        num_bits = 0
        qubits = []
        bits = []

        for statement in program.statements:
            if isinstance(statement, ast.QubitDeclaration):
                name = statement.qubit.name
                size = 1 if statement.size is None else statement.size.value
                for i in range(num_qubits, num_qubits + size):
                    qubits.append(f"{name}[{i}]")
                num_qubits += size
            if isinstance(statement, ast.ClassicalDeclaration):
                name = statement.identifier.name
                size = (
                    1
                    if statement.type.size is None
                    else statement.type.size.value
                )
                for i in range(num_bits, num_bits + size):
                    bits.append(f"{name}[{i}]")
                num_bits += size
            if isinstance(statement, ast.QuantumGate):
                gate_name = statement.name.name
                qubit_indices = [
                    extract_qubit_index(qubit) for qubit in statement.qubits
                ]
                op = Op(
                    op_id=len(ops),
                    name=gate_name,
                    qubits=tuple(qubit_indices),
                    node=statement,
                )
                ops.append(op)
            if isinstance(statement, ast.QuantumMeasurementStatement):
                qubit_index = extract_qubit_index(statement.measure.qubit)
                op = Op(
                    op_id=len(ops),
                    name="measure",
                    qubits=(qubit_index,),
                    node=statement,
                )
                ops.append(op)
        return ops
