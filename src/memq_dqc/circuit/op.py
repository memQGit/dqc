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

from memq_dqc.network import PhysicalQubit
from memq_dqc.preprocessing.qasm.types import CircuitQubit


@dataclass(frozen=True, slots=True)
class Op:
    """A quantum operation in the DAG extracted from an OpenQASM circuit.

    Attributes:
        op_id: Unique index of the operation in the extracted ops list.
        statement_id: Index of the statement in the original program.
        name: Gate or instruction name.
        is_remote: Whether the operation is a remote distributed operation.
        qubits: Qubits the operation applies to.
        node: Original OpenQASM AST node.
    """

    op_id: int
    statement_id: int
    name: str
    is_remote: bool
    qubits: tuple[CircuitQubit, ...]
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
            CircuitQubit indices in operation order.
        """
        return tuple(q.index for q in self.qubits)

    @property
    def ebit_pairs(
        self,
    ) -> tuple[tuple[PhysicalQubit, PhysicalQubit], ...] | None:
        """Return the physical communication-qubit e-bit pairs for a remote op.

        Returns:
            ``None`` for non-remote operations. For remote two-qubit gates,
            returns one pair of physical communication qubits. For ``rswap``,
            returns two physical communication-qubit pairs.

        Raises:
            ValueError: If a remote operation does not contain the expected
                communication-qubit payload.
        """
        if not self.is_remote:
            return None

        expected_pairs = 2 if self.name == "rswap" else 1
        expected_qubits = 2 + (2 * expected_pairs)
        if len(self.qubits) != expected_qubits:
            raise ValueError(
                "Remote operation does not contain the expected number of "
                f"qubits for e-bit extraction: {self.name!r} requires "
                f"{expected_qubits} qubits, received {len(self.qubits)}."
            )

        comm_qubits = self.qubits[2:]
        if any(
            not qubit.register_name.startswith("c") for qubit in comm_qubits
        ):
            raise ValueError(
                "Remote operation e-bit qubits must use communication "
                f"registers. Received {comm_qubits!r}."
            )

        return tuple(
            (
                _physical_comm_qubit(comm_qubits[index]),
                _physical_comm_qubit(comm_qubits[index + 1]),
            )
            for index in range(0, len(comm_qubits), 2)
        )


def _physical_comm_qubit(qubit: CircuitQubit) -> PhysicalQubit:
    """Convert a communication register reference to a physical qubit."""
    register = qubit.register_name.removeprefix("c")
    if not register.isdigit():
        raise ValueError(
            "Communication qubit register must be c<int>. "
            f"Received {qubit.register_name!r}."
        )

    return PhysicalQubit(
        qpu_id=int(register),
        qubit_id=qubit.index,
        qubit_type="communication",
    )
