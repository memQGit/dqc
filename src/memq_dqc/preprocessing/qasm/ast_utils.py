# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""AST utilities for OpenQASM statement cloning and rewriting."""

from __future__ import annotations

import copy
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
