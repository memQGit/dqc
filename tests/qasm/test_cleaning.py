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

from dataclasses import fields, is_dataclass

import openqasm3
from openqasm3 import ast

from memq_dqc.preprocessing.qasm import ast_utils
from memq_dqc.preprocessing.qasm.cleaning import extract_cleaned_statements


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


def test_clone_ast_node_non_dataclass_does_not_mutate_original(
    monkeypatch,
) -> None:
    qasm_source = (
        'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[1] q;\nh q[0];\n'
    )
    program = openqasm3.parser.parse(qasm_source)
    original = program.statements[-1]
    original_span_before = original.span
    original_qubit_span_before = original.qubits[0].span

    monkeypatch.setattr(ast_utils, "is_dataclass", lambda _: False)
    cloned = ast_utils._clone_ast_node(original)

    assert isinstance(cloned, ast.QuantumGate)
    assert cloned is not original
    assert cloned.span is None
    assert cloned.qubits[0].span is None

    assert original.span is original_span_before
    assert original.qubits[0].span is original_qubit_span_before
