# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Temporary file for output formatting functions for compatibility with sim."""

import re

from openqasm3 import ast


# TODO: this file probably shouldn't exist - move to utils or something
def rename_comm_qubits(qasm_prog: ast.Program) -> ast.Program:
    """Adjust communication qubit names for compatibility with simulator.

    The simulator assumes exactly two communication registers:
    ``c0`` and ``c1``, each with two qubits.

    Remote gate rewrites:
        - ``rcx`` / ``rcp`` / ``rcry`` / ``rcz`` alternate communication
          pairs:
          ``c0[0], c0[1]`` then ``c1[0], c1[1]`` and so on.
        - ``rswap`` always uses
          ``c0[0], c0[1], c1[0], c1[1]`` as its last four qubits.

    Args:
        qasm_prog: OpenQASM 3 AST program to normalize.

    Returns:
        Program with canonical communication declarations and rewired
        communication-qubit uses in remote gate statements.
    """
    statements = list(qasm_prog.statements)
    comm_decl_indices = [
        idx
        for idx, statement in enumerate(statements)
        if _is_comm_qubit_declaration(statement)
    ]
    insertion_index = _comm_declaration_insertion_index(statements)
    statements = [
        statement
        for statement in statements
        if not _is_comm_qubit_declaration(statement)
    ]

    if comm_decl_indices:
        removed_before_insertion = sum(
            idx < insertion_index for idx in comm_decl_indices
        )
        insertion_index -= removed_before_insertion

    canonical_declarations = [
        ast.QubitDeclaration(
            qubit=ast.Identifier("c0"),
            size=ast.IntegerLiteral(2),
        ),
        ast.QubitDeclaration(
            qubit=ast.Identifier("c1"),
            size=ast.IntegerLiteral(2),
        ),
    ]
    statements[insertion_index:insertion_index] = canonical_declarations

    remote_gate_names = {"rcx", "rcp", "rcry", "rcz"}
    remote_gate_count = 0
    for statement in statements:
        if not isinstance(statement, ast.QuantumGate):
            continue
        gate_name = statement.name.name
        if gate_name in remote_gate_names:
            pair_register = "c0" if remote_gate_count % 2 == 0 else "c1"
            statement.qubits = [
                *statement.qubits[:2],
                _comm_qubit_ref(pair_register, 0),
                _comm_qubit_ref(pair_register, 1),
            ]
            remote_gate_count += 1
            continue
        if gate_name == "rswap":
            statement.qubits = [
                *statement.qubits[:2],
                _comm_qubit_ref("c0", 0),
                _comm_qubit_ref("c0", 1),
                _comm_qubit_ref("c1", 0),
                _comm_qubit_ref("c1", 1),
            ]

    qasm_prog.statements = statements
    return qasm_prog


def _is_comm_qubit_declaration(statement: ast.Statement) -> bool:
    """Return whether statement is a communication-register declaration."""
    return isinstance(statement, ast.QubitDeclaration) and bool(
        re.fullmatch(r"c\d+", statement.qubit.name)
    )


def _comm_declaration_insertion_index(
    statements: list[ast.Statement],
) -> int:
    """Compute where canonical communication declarations should be inserted."""
    comm_decl_indices = [
        idx
        for idx, statement in enumerate(statements)
        if _is_comm_qubit_declaration(statement)
    ]
    if comm_decl_indices:
        return comm_decl_indices[0]

    insertion_index = 0
    for idx, statement in enumerate(statements):
        if isinstance(statement, ast.QubitDeclaration):
            insertion_index = idx + 1
            continue
        break
    return insertion_index


def _comm_qubit_ref(register_name: str, index: int) -> ast.IndexedIdentifier:
    """Build a communication-qubit indexed identifier."""
    return ast.IndexedIdentifier(
        name=ast.Identifier(register_name),
        indices=[[ast.IntegerLiteral(index)]],
    )
