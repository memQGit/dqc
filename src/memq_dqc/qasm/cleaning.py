# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Cleaned OpenQASM 3 statement representations."""

from __future__ import annotations

import warnings
from dataclasses import dataclass, fields, is_dataclass
from typing import cast

from openqasm3 import ast

from memq_dqc.qasm.extraction import extract_qubit_index
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
    cleaned_statements = []
    for stmt in program.statements:
        if stmt is not None:
            cleaned_statements.append(clean_statement(stmt))
    return cleaned_statements


def clean_statement(s: ast.Statement) -> CleanedStatement:
    """Extract the essential information from an OpenQASM statement.

    Stores key attributes in "CleanedStatement" subclasses for easier access.
    Makes a copy of the original statement with the spans (metadata) removed.

    Args:
        s: The OpenQASM statement.

    Returns:
        A cleaned statement containing the essential information.
    """
    if isinstance(s, ast.Include):
        filename = s.filename
        return CleanedIncludeStatement(
            statement_type=type(s),
            node=clone_statement_node(s),
            is_op=False,
            filename=filename,
        )
    if isinstance(s, ast.QubitDeclaration):
        name = s.qubit.name
        size = 1 if s.size is None else s.size.value
        return CleanedQubitDeclaration(
            statement_type=type(s),
            node=clone_statement_node(s),
            is_op=False,
            name=name,
            size=size,
        )
    if isinstance(s, ast.ClassicalDeclaration):
        name = s.identifier.name
        size = 1 if s.type.size is None else s.type.size.value
        return CleanedClassicalDeclaration(
            statement_type=type(s),
            node=clone_statement_node(s),
            is_op=False,
            name=name,
            size=size,
        )
    if isinstance(s, ast.QuantumGateDefinition):
        qubit_names = [q.name for q in s.qubits]
        body_statements = (
            s.body.statements if hasattr(s.body, "statements") else s.body
        )
        gates = [
            cleaned
            for g in body_statements
            if (cleaned := clean_statement(g)) is not None
            and isinstance(cleaned, CleanedQuantumGate)
        ]

        return CleanedQuantumGateDefinition(
            statement_type=type(s),
            node=clone_statement_node(s),
            is_op=False,
            qubits=qubit_names,
            gates=gates,
        )
    if isinstance(s, ast.QuantumGate):
        gate_name = s.name.name
        qubits = [extract_qubit_index(q, reg_name=True) for q in s.qubits]
        qubits = [Qubit(name, index) for name, index in qubits]
        return CleanedQuantumGate(
            statement_type=type(s),
            node=clone_statement_node(s),
            is_op=True,
            name=gate_name,
            qubits=qubits,
        )
    if isinstance(s, ast.QuantumMeasurementStatement):
        # TODO: currently only handles single qubit measurements - determine
        # if more general handling is needed.
        if s.target.indices is None:
            # TODO: handle full qreg -> creg measurements.
            raise NotImplementedError(
                "Full qubit register to classical register measurements are "
                "not supported yet."
            )
        q_name, q_idx = extract_qubit_index(s.measure.qubit, reg_name=True)
        c_name, c_idx = extract_qubit_index(s.target, reg_name=True)
        return CleanedQuantumMeasurementStatement(
            statement_type=type(s),
            node=clone_statement_node(s),
            is_op=True,
            qubit=Qubit(q_name, q_idx),
            cbit=Cbit(c_name, c_idx),
        )
    if isinstance(s, ast.QuantumBarrier):
        return CleanedStatement(
            statement_type=type(s),
            node=clone_statement_node(s),
            is_op=False,
        )
    warnings.warn(
        (
            "Statement type "
            f"{type(s)} not supported in cleaning. Preserving statement."
        ),
        UserWarning,
        stacklevel=3,
    )
    return CleanedStatement(
        statement_type=type(s),
        node=clone_statement_node(s),
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
