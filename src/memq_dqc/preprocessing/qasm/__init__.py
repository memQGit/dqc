# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""OpenQASM 3 preprocessing utilities."""

from __future__ import annotations

import warnings
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, fields, is_dataclass
from typing import cast

from openqasm3 import ast

from memq_dqc.io.qasm import load_qasm_program
from memq_dqc.qasm.types import Qubit


# TODO: come up with better naming for all of these instead of "Cleanned (...)"
@dataclass(frozen=True, slots=True)
class Cbit:
    """Represents a classical bit with register name and index."""

    register_name: str
    index: int


@dataclass(frozen=True, slots=True)
class CleanedStatement:
    """Base class for cleaned OpenQASM statements."""

    statement_type: type[ast.Statement]
    node: ast.Statement
    is_op: bool


@dataclass(frozen=True, slots=True)
class CleanedIncludeStatement(CleanedStatement):
    """Cleaned include statement."""

    filename: str


@dataclass(frozen=True, slots=True)
class CleanedQubitDeclaration(CleanedStatement):
    """Cleaned qubit declaration statement."""

    name: str
    size: int


@dataclass(frozen=True, slots=True)
class CleanedClassicalDeclaration(CleanedStatement):
    """Cleaned classical declaration statement."""

    name: str
    size: int


@dataclass(frozen=True, slots=True)
class CleanedQuantumGateDefinition(CleanedStatement):
    """Cleaned quantum gate definition statement."""

    qubits: list[str]
    gates: list[CleanedQuantumGate]


@dataclass(frozen=True, slots=True)
class CleanedQuantumGate(CleanedStatement):
    """Cleaned quantum gate statement."""

    name: str
    qubits: list[Qubit]


@dataclass(frozen=True, slots=True)
class CleanedQuantumMeasurementStatement(CleanedStatement):
    """Cleaned quantum measurement statement."""

    name: str = "measure"
    qubit: Qubit | None = None
    cbit: Cbit | None = None


def extract_cleaned_statements(
    program: ast.Program,
) -> list[CleanedStatement]:
    """Extract cleaned statements from an OpenQASM program.

    Args:
        program: The OpenQASM program.

    Returns:
        A list of cleaned statement objects.
    """
    return [
        clean_statement(statement)
        for statement in program.statements
        if statement is not None
    ]


def clean_statement(statement: ast.Statement) -> CleanedStatement:
    """Extract the essential information from an OpenQASM statement.

    Stores key attributes in "CleanedStatement" subclasses for easier access.
    Makes a copy of the original statement with the spans (metadata) removed.

    Args:
        statement: The OpenQASM statement.

    Returns:
        A cleaned statement containing the essential information.
    """
    if isinstance(statement, ast.Include):
        filename = statement.filename
        return CleanedIncludeStatement(
            statement_type=type(statement),
            node=clone_statement_node(statement),
            is_op=False,
            filename=filename,
        )
    if isinstance(statement, ast.QubitDeclaration):
        name = statement.qubit.name
        size = 1 if statement.size is None else statement.size.value
        return CleanedQubitDeclaration(
            statement_type=type(statement),
            node=clone_statement_node(statement),
            is_op=False,
            name=name,
            size=size,
        )
    if isinstance(statement, ast.ClassicalDeclaration):
        name = statement.identifier.name
        size = 1 if statement.type.size is None else statement.type.size.value
        return CleanedClassicalDeclaration(
            statement_type=type(statement),
            node=clone_statement_node(statement),
            is_op=False,
            name=name,
            size=size,
        )
    if isinstance(statement, ast.QuantumGateDefinition):
        qubit_names = [qubit.name for qubit in statement.qubits]
        body_statements = (
            statement.body.statements
            if hasattr(statement.body, "statements")
            else statement.body
        )
        gates = [
            cleaned
            for gate_statement in body_statements
            if (cleaned := clean_statement(gate_statement)) is not None
            and isinstance(cleaned, CleanedQuantumGate)
        ]

        return CleanedQuantumGateDefinition(
            statement_type=type(statement),
            node=clone_statement_node(statement),
            is_op=False,
            qubits=qubit_names,
            gates=gates,
        )
    if isinstance(statement, ast.QuantumGate):
        gate_name = statement.name.name
        qubits = [
            extract_qubit_index(qubit, reg_name=True)
            for qubit in statement.qubits
        ]
        qubits = [Qubit(name, index) for name, index in qubits]
        return CleanedQuantumGate(
            statement_type=type(statement),
            node=clone_statement_node(statement),
            is_op=True,
            name=gate_name,
            qubits=qubits,
        )
    if isinstance(statement, ast.QuantumMeasurementStatement):
        # TODO: currently only handles single qubit measurements - determine
        # if more general handling is needed.
        if statement.target.indices is None:
            # TODO: handle full qreg -> creg measurements.
            raise NotImplementedError(
                "Full qubit register to classical register measurements are "
                "not supported yet."
            )
        q_name, q_idx = extract_qubit_index(
            statement.measure.qubit, reg_name=True
        )
        c_name, c_idx = extract_qubit_index(statement.target, reg_name=True)
        return CleanedQuantumMeasurementStatement(
            statement_type=type(statement),
            node=clone_statement_node(statement),
            is_op=True,
            qubit=Qubit(q_name, q_idx),
            cbit=Cbit(c_name, c_idx),
        )
    if isinstance(statement, ast.QuantumBarrier):
        return CleanedStatement(
            statement_type=type(statement),
            node=clone_statement_node(statement),
            is_op=False,
        )
    warnings.warn(
        (
            "Statement type "
            f"{type(statement)} not supported in cleaning. Preserving statement."
        ),
        UserWarning,
        stacklevel=3,
    )
    return CleanedStatement(
        statement_type=type(statement),
        node=clone_statement_node(statement),
        is_op=False,
    )


def clone_statement_node(statement: ast.Statement) -> ast.Statement:
    """Clone a statement without source spans. Wraps _clone_ast_node.

    Args:
        statement: Statement to clone.

    Returns:
        A new statement with spans stripped from all nested nodes.
    """
    return cast(ast.Statement, _clone_ast_node(statement))


def rename_quantum_gate(gate: ast.QuantumGate, name: str) -> ast.QuantumGate:
    """Clone a quantum gate statement with a new name.

    Args:
        gate: Original quantum gate statement.
        name: New gate name.

    Returns:
        A cloned quantum gate with the updated name and no spans.
    """
    new_gate = cast(ast.QuantumGate, _clone_ast_node(gate))
    new_gate.name = ast.Identifier(name)
    return new_gate


def _clone_ast_node(node: object) -> object:
    if node is None:
        return None
    if isinstance(node, list):
        return [_clone_ast_node(item) for item in node]
    if isinstance(node, tuple):
        return tuple(_clone_ast_node(item) for item in node)
    if isinstance(node, dict):
        return {key: _clone_ast_node(value) for key, value in node.items()}
    if not isinstance(node, ast.QASMNode):
        return node

    if is_dataclass(node):
        kwargs = {
            field.name: _clone_ast_node(getattr(node, field.name))
            for field in fields(node)
            if field.init
        }
        cloned = type(node)(**kwargs)
    else:
        cloned = node

    if hasattr(cloned, "annotations"):
        cloned.annotations = [
            _clone_ast_node(annotation) for annotation in node.annotations
        ]

    cloned.span = None
    return cloned


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


def _count_two_qubit_pairs(
    pairs: Iterable[tuple[int, int]],
) -> Counter[tuple[int, int]]:
    """Count unordered two-qubit pairs."""
    counts: Counter[tuple[int, int]] = Counter()
    for i, j in pairs:
        key = (i, j) if i <= j else (j, i)
        counts[key] += 1
    return counts


__all__ = [
    "Cbit",
    "CleanedClassicalDeclaration",
    "CleanedIncludeStatement",
    "CleanedQuantumGate",
    "CleanedQuantumGateDefinition",
    "CleanedQuantumMeasurementStatement",
    "CleanedQubitDeclaration",
    "CleanedStatement",
    "Qubit",
    "clean_statement",
    "clone_statement_node",
    "count_total_qubits",
    "extract_cleaned_statements",
    "extract_qubit_index",
    "extract_two_qubit_gates",
    "rename_quantum_gate",
]
