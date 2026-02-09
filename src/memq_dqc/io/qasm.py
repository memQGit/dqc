# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""OpenQASM 3 IO helpers."""

from __future__ import annotations

import pickle
from pathlib import Path

import openqasm3
from openqasm3 import ast


def load_qasm_program(filename: str, from_cache: bool = False) -> ast.Program:
    """Load an OpenQASM 3 program from a file.

    Args:
        filename: Path to the OpenQASM 3 file.
        from_cache: Whether to load from a cached parsed program (used for
            large circuits within tests).

    Returns:
        The parsed OpenQASM 3 program.

    Notes:
        The qv_100.qasm fixture is cached to disk under .cache/qasm to keep
        repeated test runs fast.
    """
    qasm_path = Path(filename)
    if not qasm_path.is_file():
        raise FileNotFoundError(f"File not found: {filename}")
    if from_cache:
        return _load_program_from_cache(qasm_path)
    program = _parse_qasm_source(qasm_path.read_text(encoding="utf-8"))
    num_qubit_registers = _count_qubit_declarations(program)
    if num_qubit_registers > 1:
        raise NotImplementedError(
            "Multiple qubit registers are not supported yet."
        )
    # TODO: is there a way to verify valid program here? (Recall pyqasm has this)
    return program


def _load_program_from_cache(qasm_path: Path) -> ast.Program:
    """Load the large programs from a cache to minimize parsing time."""
    cache_path = Path(".cache/qasm") / (qasm_path.name + ".program.pkl")
    cache_path.parent.mkdir(parents=True, exist_ok=True)

    if cache_path.exists():
        qasm_mtime = qasm_path.stat().st_mtime
        cache_mtime = cache_path.stat().st_mtime
        if cache_mtime >= qasm_mtime:
            try:
                with cache_path.open("rb") as handle:
                    return pickle.load(handle)
            except (pickle.UnpicklingError, EOFError):
                pass

    program = _parse_qasm_source(qasm_path.read_text(encoding="utf-8"))
    with cache_path.open("wb") as handle:
        pickle.dump(program, handle)
    return program


def _parse_qasm_source(qasm_source: str) -> ast.Program:
    """Parse OpenQASM 3 source text into an AST program."""
    return openqasm3.parser.parse(qasm_source)


def _count_qubit_declarations(program: ast.Program) -> int:
    """Count the total number of qubit registers in an OpenQASM 3 program.

    Args:
        program: The OpenQASM 3 program.

    Returns:
        The total number of qubit register declarations in the program.
    """
    count = 0
    for stmt in program.statements:
        if isinstance(stmt, ast.QubitDeclaration):
            count += 1
    return count
