# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Qubit remapping and declaration-rewrite helpers for DAG transforms."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from openqasm3 import ast

from memq_dqc.preprocessing.qasm import (
    clone_statement_node,
    extract_qubit_index,
)
from memq_dqc.preprocessing.qasm.types import (
    CircuitQubit,
    CleanedIncludeStatement,
    CleanedQubitDeclaration,
    CleanedStatement,
)

if TYPE_CHECKING:
    from memq_dqc.network import NetworkGraph, PhysicalQubit
    from memq_dqc.partition.partitioner import QPU


def _replace_statement_node(
    statement: CleanedStatement,
    node: ast.Statement,
) -> CleanedStatement:
    """Return a statement with its AST node replaced.

    Args:
        statement: Original cleaned statement.
        node: Replacement AST statement node.

    Returns:
        The original statement if the node is unchanged, otherwise a copied
        statement with the new node.
    """
    if statement.node is node:
        return statement
    return replace(statement, node=node)


def _remap_cleaned_qubits(
    qubits: list[CircuitQubit],
    circuit_qubit_to_physical: dict[int, tuple[int, int]],
) -> list[CircuitQubit]:
    """Remap a list of logical qubits to QPU-local register coordinates.

    Args:
        qubits: Logical qubits to remap.
        circuit_qubit_to_physical: Mapping from logical index to ``(qpu_id, slot)``.

    Returns:
        Remapped logical qubits using per-QPU register names and indices.
    """
    return [
        _remap_cleaned_qubit(qubit, circuit_qubit_to_physical)
        for qubit in qubits
    ]


def _remap_cleaned_qubit(
    qubit: CircuitQubit | None,
    circuit_qubit_to_physical: dict[int, tuple[int, int]],
) -> CircuitQubit | None:
    """Remap one logical qubit to its current physical placement.

    Args:
        qubit: Logical qubit to remap, if present.
        circuit_qubit_to_physical: Mapping from logical index to ``(qpu_id, slot)``.

    Returns:
        Remapped logical qubit, or ``None`` when the input is ``None``.
    """
    if qubit is None:
        return None
    qpu_id, slot_idx = circuit_qubit_to_physical[qubit.index]
    return CircuitQubit(register_name=f"q{qpu_id}", index=slot_idx)


def _circuit_qubit_to_physical_qubit(
    qubit: CircuitQubit,
) -> PhysicalQubit:
    """Convert a logical qubit reference to a physical network qubit.

    Args:
        qubit: Logical qubit in schedule register space.

    Returns:
        Physical computation qubit reference for network queries.

    Raises:
        ValueError: If the logical register name is not in ``q<int>`` format.
    """
    # TODO: should reconcile the different qubit objects in the program ...
    register = qubit.register_name.removeprefix("q")
    if not register.isdigit():
        raise ValueError(
            "CircuitQubit computation register must be q<int>. "
            f"Received {qubit.register_name!r}."
        )
    from memq_dqc.network import PhysicalQubit

    return PhysicalQubit(
        qpu_id=int(register),
        qubit_id=qubit.index,
        qubit_type="computation",
    )


def _physical_to_circuit_qubit(
    qubit: PhysicalQubit,
) -> CircuitQubit:
    # NOTE: This performs a representational mapping from a PhysicalQubit to
    # a CircuitQubit reference; no additional semantic information is added.
    """Convert a physical network qubit to a logical register reference.

    Args:
        qubit: Physical qubit to convert.

    Returns:
        Logical qubit using ``q`` registers for computation qubits and ``c``
        registers for communication qubits.
    """
    prefix = "c" if qubit.qubit_type == "communication" else "q"
    return CircuitQubit(
        register_name=f"{prefix}{qubit.qpu_id}", index=qubit.qubit_id
    )


def _order_comm_pair(
    mapped_qubits: list[CircuitQubit],
    comm_pair: tuple[PhysicalQubit, PhysicalQubit],
) -> tuple[PhysicalQubit, PhysicalQubit]:
    """Align communication qubit ordering with logical gate operand order.

    Args:
        mapped_qubits: Mapped logical operands for a two-qubit gate.
        comm_pair: Communication qubit pair returned by the network.

    Returns:
        Communication pair ordered to match ``mapped_qubits`` operand order.

    Raises:
        ValueError: If fewer than two operands are provided or the pair cannot
            be aligned to the operand QPU IDs.
    """
    if len(mapped_qubits) < 2:
        raise ValueError(
            "Remote gate must include at least two mapped computation qubits."
        )

    qpu_a = _qpu_id_from_register_name(mapped_qubits[0].register_name)
    qpu_b = _qpu_id_from_register_name(mapped_qubits[1].register_name)
    comm_a, comm_b = comm_pair

    if comm_a.qpu_id == qpu_a and comm_b.qpu_id == qpu_b:
        return comm_a, comm_b

    if comm_a.qpu_id == qpu_b and comm_b.qpu_id == qpu_a:
        return comm_b, comm_a

    raise ValueError(
        "Communication pair QPU IDs do not match mapped qubit QPU IDs: "
        f"mapped=({mapped_qubits[0].register_name}, "
        f"{mapped_qubits[1].register_name}), "
        f"comm=({comm_a.qpu_id}, {comm_b.qpu_id})."
    )


def _qpu_id_from_register_name(register_name: str) -> int:
    """Extract the integer QPU ID from a logical register name.

    Args:
        register_name: Register identifier such as ``q0`` or ``c2``.

    Returns:
        Parsed QPU ID.

    Raises:
        ValueError: If the register name is empty or malformed.
    """
    if not register_name:
        raise ValueError("CircuitQubit register name cannot be empty.")
    prefix = register_name[0]
    if prefix not in {"q", "c"}:
        raise ValueError(
            "CircuitQubit register name must start with 'q' or 'c': "
            f"{register_name!r}."
        )
    suffix = register_name[1:]
    if not suffix.isdigit():
        raise ValueError(
            "CircuitQubit register suffix must be an integer. "
            f"Received {register_name!r}."
        )
    return int(suffix)


def _ordered_network_qpu_ids(network: NetworkGraph) -> list[int]:
    """Return sorted QPU IDs discovered from a network graph.

    Args:
        network: Network graph containing physical qubit mappings.

    Returns:
        Sorted unique QPU IDs present in the network.
    """
    qpu_ids = {qubit.qpu_id for qubit in network.qubit_type_map}
    return sorted(qpu_ids)


def _to_ast_qubit_ref(qubit: CircuitQubit) -> ast.IndexedIdentifier:
    """Build an AST indexed identifier for a logical qubit.

    Args:
        qubit: Logical qubit to convert.

    Returns:
        OpenQASM indexed identifier referencing the qubit.
    """
    return ast.IndexedIdentifier(
        name=ast.Identifier(qubit.register_name),
        indices=[[ast.IntegerLiteral(qubit.index)]],
    )


def _remap_statement_qubits(
    statement: ast.Statement,
    circuit_qubit_to_physical: dict[int, tuple[int, int]],
) -> ast.Statement:
    """Clone and remap qubit references inside a supported AST statement.

    Args:
        statement: Statement to clone and remap.
        circuit_qubit_to_physical: Mapping from logical index to ``(qpu_id, slot)``.

    Returns:
        Remapped statement clone.
    """
    mapped = clone_statement_node(statement)
    if isinstance(mapped, ast.QuantumGate):
        mapped.qubits = [
            _map_qubit_ref(qubit, circuit_qubit_to_physical)
            for qubit in mapped.qubits
        ]
        return mapped
    if isinstance(mapped, ast.QuantumMeasurementStatement):
        mapped.measure = ast.QuantumMeasurement(
            qubit=_map_qubit_ref(
                mapped.measure.qubit, circuit_qubit_to_physical
            )
        )
        return mapped
    if isinstance(mapped, ast.QuantumBarrier):
        mapped.qubits = [
            _map_qubit_ref(qubit, circuit_qubit_to_physical)
            for qubit in mapped.qubits
        ]
        return mapped
    if isinstance(mapped, ast.QuantumReset):
        mapped.qubits = _map_qubit_ref(
            mapped.qubits, circuit_qubit_to_physical
        )
        return mapped
    if isinstance(mapped, ast.QuantumPhase):
        mapped.qubits = [
            _map_qubit_ref(qubit, circuit_qubit_to_physical)
            for qubit in mapped.qubits
        ]
        return mapped
    return mapped


def _map_qubit_ref(
    qubit: ast.IndexedIdentifier | ast.Identifier,
    circuit_qubit_to_physical: dict[int, tuple[int, int]],
) -> ast.IndexedIdentifier:
    """Map one indexed qubit reference to per-QPU register space.

    Args:
        qubit: Qubit AST reference to remap.
        circuit_qubit_to_physical: Mapping from logical index to ``(qpu_id, slot)``.

    Returns:
        Remapped qubit AST reference.

    Raises:
        NotImplementedError: If the input qubit is not indexed.
    """
    # TODO: handle unindexed identifers (eg c = measure q)
    if isinstance(qubit, ast.Identifier):
        raise NotImplementedError("Cannot remap unindexed qubit identifiers.")
    logical_index = extract_qubit_index(qubit)
    qpu_id, slot_idx = circuit_qubit_to_physical[logical_index]
    return ast.IndexedIdentifier(
        name=ast.Identifier(f"q{qpu_id}"),
        indices=[[ast.IntegerLiteral(slot_idx)]],
    )


def _replace_qubit_declarations(
    statements: list[CleanedStatement],
    schedule: list[dict[QPU, set[int]]],
    comp_qubits_per_qpu: list[int] | None = None,
    comm_qubits_per_qpu: list[int] | None = None,
) -> list[CleanedStatement]:
    """Replace original qubit declaration with new declarations for each QPU.

    Args:
        statements: List of cleaned statements to process.
        schedule: Partition schedule; for each window, a mapping of QPUs to sets of logical qubit indices.
        comp_qubits_per_qpu: Number of computation qubits for each QPU
            indexed by QPU ID.
        comm_qubits_per_qpu: Number of communication qubits for each QPU
            indexed by QPU ID.

    Returns:
        Updated list of cleaned statements with new qubit declarations.
    """
    if not schedule:
        raise ValueError("schedule must contain at least one window.")

    qpu_qubits = {qpu: set(qubits) for qpu, qubits in schedule[0].items()}
    qpu_ids = sorted(qpu.id for qpu in qpu_qubits)
    if comp_qubits_per_qpu is None:
        comp_counts_by_qpu = {
            qpu.id: len(qubits) for qpu, qubits in qpu_qubits.items()
        }
    else:
        if len(comp_qubits_per_qpu) != len(qpu_ids):
            raise ValueError(
                "comp_qubits_per_qpu length must match the number of QPUs "
                f"in schedule: {len(comp_qubits_per_qpu)} != {len(qpu_ids)}."
            )
        comp_counts_by_qpu = {
            qpu_id: comp_qubits_per_qpu[idx]
            for idx, qpu_id in enumerate(qpu_ids)
        }

    for qpu, qubits in qpu_qubits.items():
        capacity = comp_counts_by_qpu[qpu.id]
        if len(qubits) > capacity:
            raise ValueError(
                "Schedule assigns more computation qubits than available "
                f"on QPU {qpu.id}: assigned={len(qubits)}, "
                f"capacity={capacity}."
            )

    if comm_qubits_per_qpu is None:
        comm_counts_by_qpu = {qpu_id: 0 for qpu_id in qpu_ids}
    else:
        if len(comm_qubits_per_qpu) != len(qpu_ids):
            raise ValueError(
                "comm_qubits_per_qpu length must match the number of QPUs "
                f"in schedule: {len(comm_qubits_per_qpu)} != {len(qpu_ids)}."
            )
        comm_counts_by_qpu = {
            qpu_id: comm_qubits_per_qpu[idx]
            for idx, qpu_id in enumerate(qpu_ids)
        }

    def _build_declaration(
        register_name: str,
        size: int,
    ) -> CleanedQubitDeclaration:
        """Build a cleaned qubit declaration statement.

        Args:
            register_name: Qubit register name.
            size: Register size.

        Returns:
            Cleaned qubit declaration for the provided register.
        """
        size_expr = ast.IntegerLiteral(size)
        node = clone_statement_node(
            ast.QubitDeclaration(
                qubit=ast.Identifier(register_name),
                size=size_expr,
            )
        )
        return CleanedQubitDeclaration(
            statement_type=ast.QubitDeclaration,
            node=node,
            is_op=False,
            name=register_name,
            size=size,
        )

    new_declarations: list[CleanedStatement] = []
    for qpu, _qubits in sorted(
        qpu_qubits.items(), key=lambda item: item[0].id
    ):
        comp_size = comp_counts_by_qpu[qpu.id]
        new_declarations.append(_build_declaration(f"q{qpu.id}", comp_size))

    for qpu_id in qpu_ids:
        comm_size = comm_counts_by_qpu[qpu_id]
        if comm_size > 0:
            new_declarations.append(
                _build_declaration(f"c{qpu_id}", comm_size)
            )

    filtered = [
        statement
        for statement in statements
        if not isinstance(statement, CleanedQubitDeclaration)
    ]

    insert_idx = 0
    while insert_idx < len(filtered) and isinstance(
        filtered[insert_idx], CleanedIncludeStatement
    ):
        insert_idx += 1
    return filtered[:insert_idx] + new_declarations + filtered[insert_idx:]
