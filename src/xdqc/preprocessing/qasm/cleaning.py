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

"""Cleaning utilities for OpenQASM statements."""

from __future__ import annotations

import warnings

from openqasm3 import ast

from xdqc.preprocessing.qasm.analysis import extract_qubit_index
from xdqc.preprocessing.qasm.ast_utils import clone_statement_node
from xdqc.preprocessing.qasm.types import (
    Cbit,
    CircuitQubit,
    CleanedClassicalDeclaration,
    CleanedIncludeStatement,
    CleanedQuantumGate,
    CleanedQuantumGateDefinition,
    CleanedQuantumMeasurementStatement,
    CleanedQubitDeclaration,
    CleanedStatement,
)


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
    """Extract essential information from an OpenQASM statement.

    Stores key attributes in ``CleanedStatement`` subclasses for easier
    access and clones statements without source spans.

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
        qubits = [CircuitQubit(name, index) for name, index in qubits]
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
            qubit=CircuitQubit(q_name, q_idx),
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
