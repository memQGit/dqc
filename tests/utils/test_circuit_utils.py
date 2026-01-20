# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
from pathlib import Path

from openqasm3 import ast

from memq_dqc.utils import (
    count_total_qubits,
    extract_qubit_index,
    extract_two_qubit_gates,
    load_qasm_program,
)


def test_load_qasm_program(bell_circuit_path: Path) -> None:
    program = load_qasm_program(str(bell_circuit_path))
    assert program is not None
    assert hasattr(program, "statements")


def test_load_qasm_program_file_not_found() -> None:
    try:
        load_qasm_program("non_existent_file.qasm")
    except FileNotFoundError:
        pass
    else:
        raise AssertionError("Expected FileNotFoundError was not raised.")


def test_count_total_qubits(simple1_circuit_path: Path) -> None:
    total_qubits = count_total_qubits(str(simple1_circuit_path))
    assert total_qubits == 6


def test_extract_qubit_index(bell_circuit_path: Path) -> None:
    program = load_qasm_program(str(bell_circuit_path))
    for statement in program.statements:
        if (
            isinstance(statement, ast.QuantumGate)
            and len(statement.qubits) == 2
        ):
            i, j = sorted(extract_qubit_index(q) for q in statement.qubits)
            result = sorted((i, j))
    if result is None:
        raise AssertionError("No QuantumGate statement found in the program.")
    assert result == [0, 1]


def test_extract_two_qubit_gates_bell(bell_circuit_path: Path) -> None:
    gate_counts = extract_two_qubit_gates(str(bell_circuit_path))
    assert gate_counts == {(0, 1): 1}


def test_extract_two_qubit_gates_simple1(
    simple1_circuit_path: Path,
) -> None:
    gate_counts = extract_two_qubit_gates(str(simple1_circuit_path))
    expected_counts = {
        (0, 1): 2,
        (1, 2): 1,
        (2, 3): 1,
        (3, 4): 2,
        (4, 5): 1,
        (0, 5): 1,
    }
    assert gate_counts == expected_counts
