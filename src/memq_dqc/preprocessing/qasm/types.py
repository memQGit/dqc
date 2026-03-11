# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Preprocessing statement data types."""

from __future__ import annotations

from dataclasses import dataclass

from openqasm3 import ast


@dataclass(frozen=True, slots=True)
class CircuitQubit:
    """Represents a circuit-level qubit with register name and index."""

    register_name: str
    index: int


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
class CleanedQuantumGate(CleanedStatement):
    """Cleaned quantum gate statement."""

    name: str
    qubits: list[CircuitQubit]


@dataclass(frozen=True, slots=True)
class CleanedQuantumGateDefinition(CleanedStatement):
    """Cleaned quantum gate definition statement."""

    qubits: list[str]
    gates: list[CleanedQuantumGate]


@dataclass(frozen=True, slots=True)
class CleanedQuantumMeasurementStatement(CleanedStatement):
    """Cleaned quantum measurement statement."""

    name: str = "measure"
    qubit: CircuitQubit | None = None
    cbit: Cbit | None = None


__all__ = [
    "Cbit",
    "CircuitQubit",
    "CleanedClassicalDeclaration",
    "CleanedIncludeStatement",
    "CleanedQuantumGate",
    "CleanedQuantumGateDefinition",
    "CleanedQuantumMeasurementStatement",
    "CleanedQubitDeclaration",
    "CleanedStatement",
]
