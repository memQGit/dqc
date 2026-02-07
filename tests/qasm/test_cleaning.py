# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from dataclasses import fields, is_dataclass

import openqasm3
from openqasm3 import ast

from memq_dqc.qasm.cleaning import extract_cleaned_statements


def _assert_no_spans(node) -> None:
    if node is None:
        return
    if isinstance(node, list):
        for item in node:
            _assert_no_spans(item)
        return
    if isinstance(node, tuple):
        for item in node:
            _assert_no_spans(item)
        return
    if isinstance(node, dict):
        for item in node.values():
            _assert_no_spans(item)
        return
    if not isinstance(node, ast.QASMNode):
        return

    assert node.span is None

    if hasattr(node, "annotations"):
        for annotation in node.annotations:
            _assert_no_spans(annotation)

    if is_dataclass(node):
        for field in fields(node):
            _assert_no_spans(getattr(node, field.name))


def test_cleaned_statements_clone_nodes_without_spans() -> None:
    qasm_source = (
        "OPENQASM 3.0;\n"
        'include "stdgates.inc";\n'
        "qubit[2] q;\n"
        "bit[2] c;\n"
        "h q[0];\n"
        "cx q[0], q[1];\n"
        "barrier q;\n"
        "c[0] = measure q[0];\n"
    )
    program = openqasm3.parser.parse(qasm_source)
    cleaned = extract_cleaned_statements(program)

    assert len(cleaned) == len(program.statements)
    assert any(
        isinstance(statement.node, ast.QuantumBarrier) for statement in cleaned
    )

    for original, cleaned_statement in zip(
        program.statements,
        cleaned,
        strict=False,
    ):
        assert cleaned_statement.node is not original
        _assert_no_spans(cleaned_statement.node)
