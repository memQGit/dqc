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

"""AST utilities for OpenQASM statement cloning and rewriting."""

from __future__ import annotations

import copy
import re
from dataclasses import fields, is_dataclass
from typing import cast

from openqasm3 import ast


def clone_statement_node(statement: ast.Statement) -> ast.Statement:
    """Clone a statement without source spans.

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


def is_comm_qubit_reference(
    qubit: ast.IndexedIdentifier | ast.Identifier,
) -> bool:
    """Return whether a qubit operand references a communication register.

    Args:
        qubit: Qubit reference in gate operands.

    Returns:
        True when the operand refers to a ``c*`` register.
    """
    if isinstance(qubit, ast.Identifier):
        return qubit.name.startswith("c")
    return qubit.name.name.startswith("c")


def is_comm_qubit_declaration(statement: ast.Statement) -> bool:
    """Return whether a statement declares a communication register.

    Args:
        statement: Program statement.

    Returns:
        True when the statement is a ``qubit c<digits>[...]`` declaration.
    """
    return isinstance(statement, ast.QubitDeclaration) and bool(
        re.fullmatch(r"c\d+", statement.qubit.name)
    )


def non_comm_qubits(
    qubits: list[ast.IndexedIdentifier | ast.Identifier],
) -> list[ast.IndexedIdentifier | ast.Identifier]:
    """Return qubit operands excluding communication-register references.

    Args:
        qubits: Qubit operands to filter.

    Returns:
        Operands whose register names do not start with ``c``.
    """
    return [qubit for qubit in qubits if not is_comm_qubit_reference(qubit)]


def indexed_qubit_reference(
    register_name: str,
    index: int,
) -> ast.IndexedIdentifier:
    """Build an indexed qubit reference for a named register.

    Args:
        register_name: Qubit register name.
        index: Qubit index in the register.

    Returns:
        OpenQASM indexed identifier.
    """
    return ast.IndexedIdentifier(
        name=ast.Identifier(register_name),
        indices=[[ast.IntegerLiteral(index)]],
    )


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
        cloned = copy.copy(node)
        if hasattr(node, "__dict__"):
            for attr, value in vars(node).items():
                if attr in {"annotations", "span"}:
                    continue
                setattr(cloned, attr, _clone_ast_node(value))
        for attr in _slot_names(node):
            if attr in {"annotations", "span"}:
                continue
            if hasattr(node, attr):
                setattr(cloned, attr, _clone_ast_node(getattr(node, attr)))

    if hasattr(cloned, "annotations"):
        annotations = node.annotations
        cloned.annotations = [
            _clone_ast_node(annotation) for annotation in annotations
        ]

    if hasattr(cloned, "span"):
        cloned.span = None
    return cloned


def _slot_names(node: object) -> list[str]:
    slots = getattr(type(node), "__slots__", ())
    if isinstance(slots, str):
        return [slots]
    return [slot for slot in slots if isinstance(slot, str)]
