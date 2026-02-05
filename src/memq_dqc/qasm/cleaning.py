# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Cleaned OpenQASM 3 statement representations."""

from __future__ import annotations

import warnings
from dataclasses import dataclass
from typing import Type

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

    statement_type: Type[ast.Statement]
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

    Args:
        s: The OpenQASM statement.

    Returns:
        A cleaned statement containing the essential information.
    """
    if isinstance(s, ast.Include):
        filename = s.filename
        return CleanedIncludeStatement(
            statement_type=type(s),
            node=s,
            is_op=False,
            filename=filename,
        )
    if isinstance(s, ast.QubitDeclaration):
        name = s.qubit.name
        size = 1 if s.size is None else s.size.value
        return CleanedQubitDeclaration(
            statement_type=type(s),
            node=s,
            is_op=False,
            name=name,
            size=size,
        )
    if isinstance(s, ast.ClassicalDeclaration):
        name = s.identifier.name
        size = 1 if s.type.size is None else s.type.size.value
        return CleanedClassicalDeclaration(
            statement_type=type(s),
            node=s,
            is_op=False,
            name=name,
            size=size,
        )
    if isinstance(s, ast.QuantumGateDefinition):
        qubit_names = [q.name for q in s.qubits]
        gates = [clean_statement(g) for g in s.body.statements]

        return CleanedQuantumGateDefinition(
            statement_type=type(s),
            node=s,
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
            node=s,
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
            node=s,
            is_op=True,
            qubit=Qubit(q_name, q_idx),
            cbit=Cbit(c_name, c_idx),
        )
    if isinstance(s, ast.QuantumBarrier):
        # Barriers are removed for distributed circuit
        return None
    warnings.warn(
        f"Statement type {type(s)} not supported in cleaning. Returning None.",
        UserWarning,
        stacklevel=3,
    )
    return None
