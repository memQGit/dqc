# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Utility functions used throughout memQ-DQC library."""

from collections import Counter
from pathlib import Path

import openqasm3
from openqasm3 import ast


def load_qasm_program(filename: str) -> ast.Program:
    """Load an OpenQASM 3 program from a file.

    Args:
        filename (str): Path to the OpenQASM 3 file.

    Returns:
        ast.Program: The parsed OpenQASM 3 program.
    """
    qasm_path = Path(filename)
    if not qasm_path.is_file():
        raise FileNotFoundError(f"File not found: {filename}")
    qasm_source = qasm_path.read_text(encoding="utf-8")
    program = openqasm3.parser.parse(qasm_source)
    return program


def count_total_qubits(qasm_filename: str) -> int:
    """Count the total number of qubits in an OpenQASM 3 program.

    Args:
        qasm_filename (str): The path to the OpenQASM 3 file.

    Returns:
        int: The total number of qubits.
    """
    qasm_program = load_qasm_program(qasm_filename)
    total = 0
    for stmt in qasm_program.statements:
        if isinstance(stmt, ast.QubitDeclaration):
            total += stmt.size.value
    return total


def extract_qubit_index(index_statement: ast.IndexedIdentifier) -> int:
    """Extract the qubit index from an IndexedIdentifier.

    Args:
        index_statement (ast.IndexedIdentifier): The IndexedIdentifier.

    Returns:
        int: The qubit index.
    """
    if not index_statement.indices:
        raise ValueError("No indices found in the IndexedIdentifier.")
    return int(index_statement.indices[0][0].value)


def extract_two_qubit_gates(qasm_filename: str) -> Counter:
    """Extract two-qubit gates from an OpenQASM 3 program.

    Args:
        qasm_filename (str): The path to the OpenQASM 3 file.

    Returns:
        Counter: A counter of two-qubit gates in the program in the form
                  {(i, j): count}, where (i, j) are the qubit indices.
    """
    qasm_program = load_qasm_program(qasm_filename)
    multi_qubit_gates = Counter()
    for statement in qasm_program.statements:
        if (
            isinstance(statement, ast.QuantumGate)
            and len(statement.qubits) == 2
        ):
            i, j = sorted(extract_qubit_index(q) for q in statement.qubits)
            multi_qubit_gates[(i, j)] += 1
    return multi_qubit_gates
