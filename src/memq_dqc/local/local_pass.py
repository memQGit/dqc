# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Local Qiskit transpilation utilities for distributed circuits."""

from __future__ import annotations

import copy
from pathlib import Path

import openqasm3
import qiskit.qasm3
from openqasm3 import ast
from qiskit import QuantumCircuit, transpile

from memq_dqc.preprocessing.qasm.ast_utils import clone_statement_node

# TODO: THIS ENTIRE THING NEEDS TO BE TESTED AND DEBUGGED AND CLEANED (all codex)
_DISTRIBUTED_GATE_NAMES = frozenset({"rcx", "rcp", "rcry", "rcz", "rswap"})
_LOCAL_BASIS_GATES = (
    "id",
    "x",
    "y",
    "z",
    "h",
    "s",
    "sdg",
    "t",
    "tdg",
    "sx",
    "sxdg",
    "p",
    "rx",
    "ry",
    "rz",
    "u",
    "u1",
    "u2",
    "u3",
    "cx",
    "cy",
    "cz",
    "cp",
    "swap",
)


def minimize_local_swaps_in_distributed_qasm(
    distributed_qasm_path: str,
    output_path: str | None = None,
    optimization_level: int = 3,
    seed_transpiler: int | None = 0,
) -> str:
    """Run local transpilation on same-register non-custom gate blocks.

    This function preserves distributed custom gates (for example ``rcx`` and
    ``rswap``) and only transpiles contiguous local gate blocks that:
    1) are not custom distributed gates, and 2) act on a single computation
    register (``q*``).

    Args:
        distributed_qasm_path: Path to an input distributed OpenQASM file.
        output_path: Optional output path to write the optimized OpenQASM text.
        optimization_level: Qiskit transpiler optimization level.
        seed_transpiler: Optional transpiler seed for deterministic routing and
            synthesis decisions.

    Returns:
        The optimized OpenQASM 3 text.

    Raises:
        FileNotFoundError: If ``distributed_qasm_path`` does not exist.
        ValueError: If a qubit declaration has a non-integer literal size.
        RuntimeError: If Qiskit fails to import/transpile a local gate block.
    """
    source_path = Path(distributed_qasm_path)
    if not source_path.is_file():
        raise FileNotFoundError(
            f"Distributed QASM file does not exist: {distributed_qasm_path}"
        )

    program = openqasm3.parser.parse(source_path.read_text(encoding="utf-8"))
    register_sizes = _extract_qubit_register_sizes(program)

    optimized_statements: list[ast.Statement | ast.Pragma] = []
    statements = list(program.statements)
    index = 0

    while index < len(statements):
        statement = statements[index]
        register_name = _local_register_for_transpile(statement)
        if register_name is None:
            optimized_statements.append(_clone_program_node(statement))
            index += 1
            continue

        block: list[ast.QuantumGate] = []
        while index < len(statements):
            candidate = statements[index]
            candidate_register = _local_register_for_transpile(candidate)
            if candidate_register != register_name:
                break
            if not isinstance(candidate, ast.QuantumGate):
                break
            cloned_candidate = clone_statement_node(candidate)
            if not isinstance(cloned_candidate, ast.QuantumGate):
                raise RuntimeError(
                    "Failed to clone a local quantum gate for transpilation."
                )
            block.append(cloned_candidate)
            index += 1

        optimized_statements.extend(
            _transpile_local_gate_block(
                register_name=register_name,
                register_size=register_sizes[register_name],
                block=block,
                optimization_level=optimization_level,
                seed_transpiler=seed_transpiler,
            )
        )

    optimized_program = ast.Program(
        version=program.version,
        statements=optimized_statements,
    )
    optimized_qasm = openqasm3.dumps(optimized_program)

    if output_path is not None:
        Path(output_path).write_text(optimized_qasm, encoding="utf-8")

    return optimized_qasm


# TODO: rename to local COMPILE
def local_transpile(
    distributed_qasm_path: str,
    output_path: str | None = None,
    optimization_level: int = 3,
    seed_transpiler: int | None = 0,
) -> str:
    """Alias for local transpilation with swap minimization behavior."""
    return minimize_local_swaps_in_distributed_qasm(
        distributed_qasm_path=distributed_qasm_path,
        output_path=output_path,
        optimization_level=optimization_level,
        seed_transpiler=seed_transpiler,
    )


def _extract_qubit_register_sizes(program: ast.Program) -> dict[str, int]:
    """Extract declared qubit register sizes from a program."""
    register_sizes: dict[str, int] = {}

    for statement in program.statements:
        if not isinstance(statement, ast.QubitDeclaration):
            continue

        if not isinstance(statement.size, ast.IntegerLiteral):
            raise ValueError(
                "Only integer literal qubit declarations are supported: "
                f"{statement.qubit.name}"
            )
        register_sizes[statement.qubit.name] = statement.size.value

    return register_sizes


def _local_register_for_transpile(
    statement: ast.Statement | ast.Pragma,
) -> str | None:
    """Return register name when statement is a transpilable local gate."""
    if not isinstance(statement, ast.QuantumGate):
        return None

    gate_name = statement.name.name
    if gate_name in _DISTRIBUTED_GATE_NAMES:
        return None

    register_names: set[str] = set()
    for qubit in statement.qubits:
        if not isinstance(qubit, ast.IndexedIdentifier):
            return None
        register_name = qubit.name.name
        if register_name.startswith("c"):
            return None
        register_names.add(register_name)

    if len(register_names) != 1:
        return None

    return next(iter(register_names))


def _transpile_local_gate_block(
    register_name: str,
    register_size: int,
    block: list[ast.QuantumGate],
    optimization_level: int,
    seed_transpiler: int | None,
) -> list[ast.Statement]:
    """Transpile one contiguous same-register block and return new gates.

    Any final layout permutation produced by Qiskit is materialized as local
    ``swap`` gates so the block preserves wire-level semantics.
    """
    if not block:
        return []

    mini_program = ast.Program(
        version="3.0",
        statements=[
            ast.Include(filename="stdgates.inc"),
            ast.QubitDeclaration(
                qubit=ast.Identifier(register_name),
                size=ast.IntegerLiteral(register_size),
            ),
            *block,
        ],
    )

    block_qasm = openqasm3.dumps(mini_program)

    try:
        circuit = qiskit.qasm3.loads(block_qasm)
        transpiled_circuit = transpile(
            circuit,
            basis_gates=list(_LOCAL_BASIS_GATES),
            optimization_level=optimization_level,
            seed_transpiler=seed_transpiler,
        )
        layout_correction_swaps = _layout_correction_swaps(
            transpiled_circuit=transpiled_circuit,
            register_size=register_size,
        )
        transpiled_qasm = qiskit.qasm3.dumps(transpiled_circuit)
    except Exception as exc:  # pragma: no cover - defensive surface wrapper
        raise RuntimeError(
            "Failed to transpile local gate block for register "
            f"{register_name}."
        ) from exc

    transpiled_program = openqasm3.parser.parse(transpiled_qasm)
    remapped_gates: list[ast.Statement] = []
    for statement in transpiled_program.statements:
        if not isinstance(statement, ast.QuantumGate):
            continue
        remapped_gate = clone_statement_node(statement)
        if not isinstance(remapped_gate, ast.QuantumGate):
            raise RuntimeError(
                "Failed to clone transpiled local quantum gate statement."
            )
        remapped_gate.qubits = [
            _remap_qubit_reference(
                qubit=qubit,
                register_name=register_name,
                register_size=register_size,
            )
            for qubit in remapped_gate.qubits
        ]
        remapped_gates.append(remapped_gate)
    for left_index, right_index in layout_correction_swaps:
        remapped_gates.append(
            _swap_gate_statement(
                register_name=register_name,
                left_index=left_index,
                right_index=right_index,
            )
        )
    return remapped_gates


def _layout_correction_swaps(
    transpiled_circuit: QuantumCircuit,
    register_size: int,
) -> list[tuple[int, int]]:
    """Return swaps that materialize a transpiler final-layout permutation."""
    layout = transpiled_circuit.layout
    if layout is None or layout.final_layout is None:
        return []

    final_index_layout = layout.final_index_layout()
    if len(final_index_layout) != register_size:
        raise RuntimeError(
            "Unexpected transpiler final layout width for local register "
            f"(expected {register_size}, got {len(final_index_layout)})."
        )

    inverse_layout = _inverse_permutation(final_index_layout)
    return _permutation_to_swaps(inverse_layout)


def _inverse_permutation(permutation: list[int]) -> list[int]:
    """Return the inverse of an index permutation."""
    permutation_size = len(permutation)
    sorted_values = sorted(permutation)
    expected = list(range(permutation_size))
    if sorted_values != expected:
        raise RuntimeError(
            f"Transpiler produced an invalid qubit permutation: {permutation}."
        )

    inverse = [0] * permutation_size
    for source_index, destination_index in enumerate(permutation):
        inverse[destination_index] = source_index
    return inverse


def _permutation_to_swaps(
    permutation: list[int],
) -> list[tuple[int, int]]:
    """Decompose a permutation into a sequence of in-place swaps."""
    working = permutation.copy()
    swaps: list[tuple[int, int]] = []

    for source_index in range(len(working)):
        while working[source_index] != source_index:
            destination_index = working[source_index]
            swaps.append((source_index, destination_index))
            working[source_index], working[destination_index] = (
                working[destination_index],
                working[source_index],
            )

    return swaps


def _clone_program_node(
    statement: ast.Statement | ast.Pragma,
) -> ast.Statement | ast.Pragma:
    """Clone one OpenQASM program-level node."""
    if isinstance(statement, ast.Statement):
        return clone_statement_node(statement)
    return copy.deepcopy(statement)


def _remap_qubit_reference(
    qubit: ast.IndexedIdentifier | ast.Identifier,
    register_name: str,
    register_size: int,
) -> ast.IndexedIdentifier | ast.Identifier:
    """Map transpiled qubit refs back onto a named local register."""
    if isinstance(qubit, ast.IndexedIdentifier):
        operand_register = qubit.name.name
        if not operand_register.startswith("$"):
            return qubit
        mapped_index = _physical_qubit_index(operand_register)
        _validate_register_bounds(
            register_name=register_name,
            register_size=register_size,
            qubit_index=mapped_index,
        )
        return _indexed_qubit_ref(register_name, mapped_index)

    if not qubit.name.startswith("$"):
        return qubit

    mapped_index = _physical_qubit_index(qubit.name)
    _validate_register_bounds(
        register_name=register_name,
        register_size=register_size,
        qubit_index=mapped_index,
    )
    return _indexed_qubit_ref(register_name, mapped_index)


def _physical_qubit_index(operand: str) -> int:
    """Return the integer index encoded in a ``$<index>`` qubit token."""
    try:
        return int(operand.removeprefix("$"))
    except ValueError as exc:
        raise RuntimeError(
            f"Unexpected transpiled qubit operand: {operand}"
        ) from exc


def _validate_register_bounds(
    register_name: str,
    register_size: int,
    qubit_index: int,
) -> None:
    """Ensure a remapped qubit index is valid for the target register."""
    if 0 <= qubit_index < register_size:
        return
    raise RuntimeError(
        "Transpiler produced an out-of-bounds qubit index for register "
        f"{register_name}: {qubit_index} (size={register_size})."
    )


def _indexed_qubit_ref(
    register_name: str,
    qubit_index: int,
) -> ast.IndexedIdentifier:
    """Build an indexed register qubit reference."""
    return ast.IndexedIdentifier(
        name=ast.Identifier(register_name),
        indices=[[ast.IntegerLiteral(qubit_index)]],
    )


def _swap_gate_statement(
    register_name: str,
    left_index: int,
    right_index: int,
) -> ast.QuantumGate:
    """Build a local ``swap`` statement for one register."""
    return ast.QuantumGate(
        modifiers=[],
        name=ast.Identifier("swap"),
        arguments=[],
        qubits=[
            _indexed_qubit_ref(register_name, left_index),
            _indexed_qubit_ref(register_name, right_index),
        ],
    )
