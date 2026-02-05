# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""OpenQASM 3 extraction helpers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from openqasm3 import ast

from memq_dqc.io.qasm import load_qasm_program


def count_total_qubits(qasm: str | ast.Program) -> int:
    """Count the total number of qubits in an OpenQASM 3 program.

    Args:
        qasm: QASM program or path to a QASM file.

    Returns:
        The total number of qubits in the program.
    """
    qasm_program = (
        qasm if isinstance(qasm, ast.Program) else load_qasm_program(qasm)
    )
    total = 0
    for stmt in qasm_program.statements:
        if isinstance(stmt, ast.QubitDeclaration):
            total += stmt.size.value
    return total


def extract_qubit_index(
    index_statement: ast.IndexedIdentifier, reg_name: bool = False
) -> int | tuple[str, int]:
    """Extract the qubit index from an IndexedIdentifier.

    Args:
        index_statement: Indexed identifier to extract from.
        reg_name: Whether to also return the register name along with index.

    Returns:
        The extracted qubit index.
    """
    if not index_statement.indices:
        raise ValueError("No indices found in the IndexedIdentifier.")
    index = int(index_statement.indices[0][0].value)
    if not reg_name:
        return index
    return (index_statement.name.name, index)


def extract_two_qubit_gates(qasm: str | ast.Program) -> Counter:
    """Extract two-qubit gates from an OpenQASM 3 program.

    Args:
        qasm: QASM program or path to a QASM file.

    Returns:
        Counts of two-qubit gates keyed by qubit index pairs.
    """
    qasm_program = (
        qasm if isinstance(qasm, ast.Program) else load_qasm_program(qasm)
    )
    pairs = (
        (extract_qubit_index(q0), extract_qubit_index(q1))
        for statement in qasm_program.statements
        if isinstance(statement, ast.QuantumGate)
        and len(statement.qubits) == 2
        for q0, q1 in [statement.qubits]
    )
    return _count_two_qubit_pairs(pairs)


def _count_two_qubit_pairs(
    pairs: Iterable[tuple[int, int]],
) -> Counter[tuple[int, int]]:
    """Count unordered two-qubit pairs."""
    counts: Counter[tuple[int, int]] = Counter()
    for i, j in pairs:
        key = (i, j) if i <= j else (j, i)
        counts[key] += 1
    return counts
