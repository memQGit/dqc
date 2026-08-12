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

"""OpenQASM analysis helpers."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable

from openqasm3 import ast

from xdqc.preprocessing.qasm.io import load_qasm_program


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
            total += 1 if stmt.size is None else stmt.size.value
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


def extract_two_qubit_gates(
    qasm: str | ast.Program,
) -> Counter[tuple[int, int]]:
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


def extract_qubit_register_sizes(program: ast.Program) -> dict[str, int]:
    """Extract declared qubit register sizes from a program.

    Args:
        program: OpenQASM 3 program to inspect.

    Returns:
        Mapping from qubit register name to declared size.

    Raises:
        ValueError: If a qubit declaration does not use an integer literal.
    """
    register_sizes: dict[str, int] = {}

    for statement in program.statements:
        if not isinstance(statement, ast.QubitDeclaration):
            continue
        if not isinstance(statement.size, ast.IntegerLiteral):
            raise ValueError(
                "Only integer literal qubit declarations are supported: "
                f"{statement.qubit.name}"
            )
        register_sizes[statement.qubit.name] = statement.size.value

    return register_sizes


def _count_two_qubit_pairs(
    pairs: Iterable[tuple[int, int]],
) -> Counter[tuple[int, int]]:
    """Count unordered two-qubit pairs."""
    counts: Counter[tuple[int, int]] = Counter()
    for i, j in pairs:
        key = (i, j) if i <= j else (j, i)
        counts[key] += 1
    return counts
