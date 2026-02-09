# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Operation data structures for circuit DAGs."""

from __future__ import annotations

from dataclasses import dataclass

from openqasm3 import ast

from memq_dqc.qasm.types import Qubit


@dataclass(frozen=True, slots=True)
class Op:
    """A quantum operation in the DAG extracted from an OpenQASM circuit.

    Attributes:
        op_id: Unique index of the operation in the extracted ops list.
        statement_id: Index of the statement in the original program.
        name: Gate or instruction name.
        qubits: Qubits the operation applies to.
        node: Original OpenQASM AST node.
    """

    op_id: int
    statement_id: int
    name: str
    qubits: tuple[Qubit, ...]
    node: ast.QASMNode

    @property
    def is_two_qubit(self) -> bool:
        """Return True when the operation acts on two qubits.

        Returns:
            True if the operation spans two qubits, otherwise False.
        """
        return len(self.qubits) == 2

    @property
    def qubit_indices(self) -> tuple[int, ...]:
        """Return the integer indices of the operation's qubits.

        Returns:
            Qubit indices in operation order.
        """
        return tuple(q.index for q in self.qubits)
