# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Add appropriate docstring for class here"""

from __future__ import annotations

from dataclasses import dataclass

import networkx as nx
from openqasm3 import ast

from memq_dqc.utils import extract_qubit_index


@dataclass(frozen=True, slots=True)
class Op:
    """A quantum operation in the DAG, extracted from QASM circuit"""

    op_id: int
    name: str
    qubits: tuple[int, ...]
    node: ast.QASMNode

    @property
    def is_two_qubit(self) -> bool:
        """Check if the operation is a two-qubit gate."""
        return len(self.qubits) == 2


class DAG:
    """TODO: Update class docstring to match expected class docstring style

    Directed Acyclic Graph (DAG) representation of a quantum circuit.

    """

    def __init__(self, program: ast.Program) -> None:
        self.program = program
        self.ops: list[Op] = self._extract_ops()
        self.graph: nx.DiGraph = self._build_dag()

    # Public Methods

    # Private Methods
    def _build_dag(self) -> nx.DiGraph:
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
        """TODO: Add method docstring"""
        program = self.program
        ops: list[Op] = []
        num_qubits = 0
        num_bits = 0
        qubits = []
        bits = []

        for statement in program.statements:
            if isinstance(statement, ast.QubitDeclaration):
                name = statement.qubit.name
                size = statement.qubit.size.value
                for i in range(num_qubits, num_qubits + size):
                    qubits.append(f"{name}[{i}]")
                num_qubits += size
            if isinstance(statement, ast.ClassicalDeclaration):
                name = statement.classical.name
                size = statement.classical.size.value
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
                qubit_index = extract_qubit_index(statement.measurement.qubit)
                op = Op(
                    op_id=len(ops),
                    name="measure",
                    qubits=(qubit_index,),
                    node=statement,
                )
                ops.append(op)
        return ops
