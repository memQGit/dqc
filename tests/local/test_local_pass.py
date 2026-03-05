# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

import openqasm3
import qiskit.qasm3
from openqasm3 import ast
from qiskit.quantum_info import Statevector

from memq_dqc.local.local_pass import (
    minimize_local_swaps_in_distributed_qasm,
)
from memq_dqc.verify.verify import dist_to_mono_circuit


def test_local_pass_reduces_local_swaps_and_preserves_custom_gates(
    tmp_path: Path,
) -> None:
    source_qasm = (
        "OPENQASM 3.0;\n"
        'include "builder/distgates.inc";\n'
        'include "stdgates.inc";\n'
        "qubit[3] q0;\n"
        "qubit[2] q1;\n"
        "qubit[1] c0;\n"
        "qubit[1] c1;\n"
        "bit[3] b;\n"
        "swap q0[0], q0[1];\n"
        "swap q0[0], q0[1];\n"
        "h q0[2];\n"
        "rcx q0[2], q1[0], c0[0], c1[0];\n"
        "swap q1[0], q1[1];\n"
        "swap q1[0], q1[1];\n"
        "rswap q1[0], q0[0], c0[0], c1[0], c0[0], c1[0];\n"
        "b[0] = measure q0[0];\n"
        "b[1] = measure q0[1];\n"
        "b[2] = measure q0[2];\n"
    )
    source_path = tmp_path / "dist_input.qasm"
    output_path = tmp_path / "dist_output.qasm"
    source_path.write_text(source_qasm, encoding="utf-8")

    optimized_qasm = minimize_local_swaps_in_distributed_qasm(
        distributed_qasm_path=str(source_path),
        output_path=str(output_path),
    )

    assert output_path.read_text(encoding="utf-8") == optimized_qasm

    original_program = openqasm3.parser.parse(source_qasm)
    optimized_program = openqasm3.parser.parse(optimized_qasm)

    assert _gate_count(optimized_program, "swap") < _gate_count(
        original_program,
        "swap",
    )
    assert _gate_count(optimized_program, "rcx") == _gate_count(
        original_program,
        "rcx",
    )
    assert _gate_count(optimized_program, "rswap") == _gate_count(
        original_program,
        "rswap",
    )
    assert _qubit_declaration_names(optimized_program) == [
        "q0",
        "q1",
        "c0",
        "c1",
    ]

    for statement in optimized_program.statements:
        if not isinstance(statement, ast.QuantumGate):
            continue
        if statement.name.name in {"rcx", "rcp", "rcry", "rcz", "rswap"}:
            continue

        for qubit in statement.qubits:
            if isinstance(qubit, ast.Identifier):
                assert not qubit.name.startswith("$")
            if isinstance(qubit, ast.IndexedIdentifier):
                assert not qubit.name.name.startswith("$")

        registers = {
            qubit.name.name
            for qubit in statement.qubits
            if isinstance(qubit, ast.IndexedIdentifier)
        }
        if len(statement.qubits) >= 2:
            assert len(registers) == 1


def test_local_pass_preserves_semantics_with_level3_permutation(
    tmp_path: Path,
) -> None:
    source_qasm = (
        "OPENQASM 3.0;\n"
        'include "builder/distgates.inc";\n'
        'include "stdgates.inc";\n'
        "qubit[2] q0;\n"
        "qubit[1] q1;\n"
        "qubit[1] c0;\n"
        "qubit[1] c1;\n"
        "x q0[0];\n"
        "swap q0[0], q0[1];\n"
        "rcx q0[1], q1[0], c0[0], c1[0];\n"
    )
    source_path = tmp_path / "dist_input_level3.qasm"
    optimized_path = tmp_path / "dist_output_level3.qasm"
    source_path.write_text(source_qasm, encoding="utf-8")

    optimized_qasm = minimize_local_swaps_in_distributed_qasm(
        distributed_qasm_path=str(source_path),
        output_path=str(optimized_path),
        optimization_level=3,
    )

    original_mono = qiskit.qasm3.loads(dist_to_mono_circuit(str(source_path)))
    optimized_mono = qiskit.qasm3.loads(
        dist_to_mono_circuit(str(optimized_path))
    )

    original_state = Statevector.from_instruction(original_mono)
    optimized_state = Statevector.from_instruction(optimized_mono)
    assert optimized_state.equiv(original_state)

    original_remote = _remote_gate_signatures(
        openqasm3.parser.parse(source_qasm)
    )
    optimized_remote = _remote_gate_signatures(
        openqasm3.parser.parse(optimized_qasm)
    )
    assert optimized_remote == original_remote


def _gate_count(program: ast.Program, gate_name: str) -> int:
    return sum(
        1
        for statement in program.statements
        if isinstance(statement, ast.QuantumGate)
        and statement.name.name == gate_name
    )


def _qubit_declaration_names(program: ast.Program) -> list[str]:
    return [
        statement.qubit.name
        for statement in program.statements
        if isinstance(statement, ast.QubitDeclaration)
    ]


def _remote_gate_signatures(
    program: ast.Program,
) -> list[tuple[str, tuple[str, ...]]]:
    signatures: list[tuple[str, tuple[str, ...]]] = []
    remote_gate_names = {"rcx", "rcp", "rcry", "rcz", "rswap"}

    for statement in program.statements:
        if not isinstance(statement, ast.QuantumGate):
            continue
        gate_name = statement.name.name
        if gate_name not in remote_gate_names:
            continue
        signatures.append(
            (
                gate_name,
                tuple(
                    _qubit_reference_signature(qubit)
                    for qubit in statement.qubits
                ),
            )
        )

    return signatures


def _qubit_reference_signature(
    qubit: ast.IndexedIdentifier | ast.Identifier,
) -> str:
    if isinstance(qubit, ast.Identifier):
        return qubit.name

    if not qubit.indices or not qubit.indices[0]:
        raise AssertionError(
            "Expected an indexed qubit with one integer index."
        )
    index_group = qubit.indices[0]
    if isinstance(index_group, ast.DiscreteSet):
        if len(index_group.values) != 1:
            raise AssertionError(
                "Expected one index value in a discrete qubit index set."
            )
        first_index = index_group.values[0]
    else:
        first_index = index_group[0]
    if not isinstance(first_index, ast.IntegerLiteral):
        raise AssertionError("Expected integer literal qubit indices.")
    return f"{qubit.name.name}[{first_index.value}]"
