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

"""Swap-construction helpers for distributed DAG transformations."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from openqasm3 import ast

from xdqc.builder.extract_utils import SwapOp
from xdqc.circuit.dag.remap import (
    _circuit_qubit_to_physical_qubit,
    _physical_to_circuit_qubit,
    _qpu_id_from_register_name,
    _to_ast_qubit_ref,
)
from xdqc.network import PhysicalQubit
from xdqc.preprocessing.qasm import clone_statement_node
from xdqc.preprocessing.qasm.types import CircuitQubit, CleanedQuantumGate

if TYPE_CHECKING:
    from xdqc.network import NetworkGraph

PlacementSwap = tuple[tuple[int, int], tuple[int, int]]


def _candidate_comp_slots_for_qpu(
    qpu_id: int,
    circuit_qubit_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
) -> list[int]:
    """Return candidate computation slots on a schedule QPU."""
    mapped_slots = sorted(
        slot
        for mapped_qpu_id, slot in circuit_qubit_to_physical_window.values()
        if mapped_qpu_id == qpu_id
    )
    mapped_slots_set = set(mapped_slots)

    if comp_capacity_by_schedule_qpu is None:
        return mapped_slots

    if qpu_id not in comp_capacity_by_schedule_qpu:
        raise ValueError(
            f"Missing computation capacity for schedule QPU {qpu_id}."
        )
    capacity = comp_capacity_by_schedule_qpu[qpu_id]
    return sorted(
        range(capacity),
        key=lambda slot: (slot not in mapped_slots_set, slot),
    )


def _build_rswap_statement_from_positions(
    pos0: tuple[int, int],
    pos1: tuple[int, int],
    network: NetworkGraph,
) -> CleanedQuantumGate:
    """Build a routed ``rswap`` statement from two schedule-space positions.

    A remote swap is realized by two state teleportations and is emitted
    standalone: unlike remote data gates it is never wrapped by
    ``catent`` / ``catdisent`` operations. Its e-bit pairs are carried
    directly as trailing operands on the ``rswap`` itself.
    """
    swap_node, swap_qubits, _ = _build_swap_gate(
        SwapOp(q0=-1, q1=-1, pos0=pos0, pos1=pos1),
        network,
    )
    return CleanedQuantumGate(
        statement_type=ast.QuantumGate,
        node=swap_node,
        is_op=True,
        name="rswap",
        qubits=swap_qubits,
    )


def _build_rswap_statements_for_swap(
    swap: SwapOp,
    network: NetworkGraph,
    circuit_qubit_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
) -> tuple[list[CleanedQuantumGate], list[PlacementSwap]]:
    """Build one or more ``rswap`` statements for a schedule-space swap.

    For adjacent QPUs, this emits a single ``rswap``. For non-adjacent QPUs,
    this emits a routed chain of adjacent ``rswap`` operations that preserves
    all intermediary placements while swapping only the endpoint positions.

    Args:
        swap: Swap operation to realize.
        network: Network graph used to resolve communication pairs and routes.
        circuit_qubit_to_physical_window: Logical-to-physical map for the current
            window.
        comp_capacity_by_schedule_qpu: Optional computation capacity per
            schedule QPU.

    Returns:
        A non-empty list of ``rswap`` statements implementing ``swap`` and the
        physical position swaps they perform.
    """
    try:
        return (
            [
                _build_rswap_statement_from_positions(
                    pos0=swap.pos0,
                    pos1=swap.pos1,
                    network=network,
                )
            ],
            [(swap.pos0, swap.pos1)],
        )
    except ValueError as direct_swap_error:
        if not (
            hasattr(network, "_remote_comm_pair_counts")
            and hasattr(network, "_shortest_qpu_path_with_min_pairs")
        ):
            raise direct_swap_error
        routed_positions = _routed_swap_positions(
            pos0=swap.pos0,
            pos1=swap.pos1,
            network=network,
            circuit_qubit_to_physical_window=circuit_qubit_to_physical_window,
            comp_capacity_by_schedule_qpu=comp_capacity_by_schedule_qpu,
        )
        if len(routed_positions) < 2:
            raise direct_swap_error

        routed_statements: list[CleanedQuantumGate] = []
        placement_swaps: list[PlacementSwap] = []
        for idx in range(len(routed_positions) - 1):
            pos0 = routed_positions[idx]
            pos1 = routed_positions[idx + 1]
            routed_statements.append(
                _build_rswap_statement_from_positions(
                    pos0=pos0,
                    pos1=pos1,
                    network=network,
                )
            )
            placement_swaps.append((pos0, pos1))

        for idx in range(len(routed_positions) - 3, -1, -1):
            pos0 = routed_positions[idx]
            pos1 = routed_positions[idx + 1]
            routed_statements.append(
                _build_rswap_statement_from_positions(
                    pos0=pos0,
                    pos1=pos1,
                    network=network,
                )
            )
            placement_swaps.append((pos0, pos1))

        return routed_statements, placement_swaps


def _routed_swap_positions(
    pos0: tuple[int, int],
    pos1: tuple[int, int],
    network: NetworkGraph,
    circuit_qubit_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
) -> list[tuple[int, int]]:
    """Resolve intermediary positions for a routed non-adjacent swap.

    Args:
        pos0: First endpoint position in schedule space.
        pos1: Second endpoint position in schedule space.
        network: Network graph used to compute QPU hop routes.
        circuit_qubit_to_physical_window: Logical-to-physical map for the current
            window.
        comp_capacity_by_schedule_qpu: Optional computation capacity per
            schedule QPU.

    Returns:
        Ordered positions from source to target, including intermediaries.
    """
    pair_counts = network._remote_comm_pair_counts()
    route_network_qpu_ids = network._shortest_qpu_path_with_min_pairs(
        source_qpu_id=pos0[0],
        target_qpu_id=pos1[0],
        min_pairs=2,
        pair_counts=pair_counts,
    )
    if len(route_network_qpu_ids) <= 2:
        return [pos0, pos1]

    routed_positions = [pos0]
    for network_qpu_id in route_network_qpu_ids[1:-1]:
        candidate_slots = _candidate_comp_slots_for_qpu(
            qpu_id=network_qpu_id,
            circuit_qubit_to_physical_window=circuit_qubit_to_physical_window,
            comp_capacity_by_schedule_qpu=comp_capacity_by_schedule_qpu,
        )
        if not candidate_slots:
            raise ValueError(
                "No computation slot available on intermediary QPU "
                f"{network_qpu_id} while routing partition swap."
            )
        routed_positions.append((network_qpu_id, candidate_slots[0]))
    routed_positions.append(pos1)
    return routed_positions


def _build_swap_gate(
    swap: SwapOp,
    network: NetworkGraph,
) -> tuple[
    ast.QuantumGate,
    list[CircuitQubit],
    list[tuple[PhysicalQubit, PhysicalQubit]],
]:
    """Build an ``rswap`` gate node and logical-qubit payload.

    Args:
        swap: Swap operation describing two physical positions.
        network: Network graph used to resolve communication pairs.

    Returns:
        AST gate node, cleaned logical qubits for the swap, and selected
        communication pairs.

    Raises:
        ValueError: If fewer than two disjoint communication pairs are
            available for state teleportation.
    """
    q0_qpu, q0_slot = swap.pos0
    q1_qpu, q1_slot = swap.pos1
    data_qubits = [
        CircuitQubit(register_name=f"q{q0_qpu}", index=q0_slot),
        CircuitQubit(register_name=f"q{q1_qpu}", index=q1_slot),
    ]

    network_qubit_a = _circuit_qubit_to_physical_qubit(data_qubits[0])
    network_qubit_b = _circuit_qubit_to_physical_qubit(data_qubits[1])
    pair_options = network.get_comm_pair_options(
        network_qubit_a,
        network_qubit_b,
    )
    selected_pairs: list[tuple[PhysicalQubit, PhysicalQubit]] = []
    used_comm_qubits = set()
    for _, comm_pair, _ in pair_options:
        comm_a, comm_b = comm_pair
        if comm_a in used_comm_qubits or comm_b in used_comm_qubits:
            continue
        selected_pairs.append(comm_pair)
        used_comm_qubits.update({comm_a, comm_b})
        if len(selected_pairs) == 2:
            break
    if len(selected_pairs) < 2:
        raise ValueError(
            "State teleportation not supported - currently requires "
            "2 e-bit pairs."
        )

    comm_qubits = [
        _physical_to_circuit_qubit(comm_qubit)
        for comm_pair in selected_pairs
        for comm_qubit in comm_pair
    ]
    qubits = [*data_qubits, *comm_qubits]
    node = cast(
        ast.QuantumGate,
        clone_statement_node(
            ast.QuantumGate(
                modifiers=[],
                name=ast.Identifier("rswap"),
                arguments=[],
                qubits=[_to_ast_qubit_ref(qubit) for qubit in qubits],
            )
        ),
    )
    return node, qubits, selected_pairs


def _build_local_swap_gate(
    q0: CircuitQubit,
    q1: CircuitQubit,
) -> tuple[ast.QuantumGate, list[CircuitQubit]]:
    """Build a local ``swap`` gate node and cleaned qubit payload."""
    qubits = [q0, q1]
    node = cast(
        ast.QuantumGate,
        clone_statement_node(
            ast.QuantumGate(
                modifiers=[],
                name=ast.Identifier("swap"),
                arguments=[],
                qubits=[
                    _to_ast_qubit_ref(q0),
                    _to_ast_qubit_ref(q1),
                ],
            )
        ),
    )
    return node, qubits


def _validate_local_swap_pair(q0: CircuitQubit, q1: CircuitQubit) -> None:
    """Validate that a local swap pair is on the same QPU."""
    if _qpu_id_from_register_name(
        q0.register_name
    ) != _qpu_id_from_register_name(q1.register_name):
        raise ValueError(
            "Local swap operands must be on the same QPU: "
            f"{q0.register_name!r}, {q1.register_name!r}."
        )
