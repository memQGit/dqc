# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Public builders for circuit DAGs."""

from __future__ import annotations

from openqasm3 import ast

from memq_dqc.circuit.dag import CircuitDAG
from memq_dqc.preprocessing.qasm.io import load_qasm_program


def build_dag(program_or_path: str | ast.Program) -> CircuitDAG:
    """Build a CircuitDAG from a program or QASM file path.

    Args:
        program_or_path: OpenQASM 3 program or filesystem path.

    Returns:
        The constructed CircuitDAG.
    """
    if isinstance(program_or_path, ast.Program):
        program = program_or_path
    else:
        program = load_qasm_program(program_or_path)
    return CircuitDAG(program)
