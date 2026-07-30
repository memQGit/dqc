# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Remote-gate routing helpers for distributed DAG construction."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from openqasm3 import ast

from xdqc.circuit.dag.entanglement import _build_entanglement_statements
from xdqc.circuit.dag.remap import (
    _circuit_qubit_to_physical_qubit,
    _order_comm_pair,
    _physical_to_circuit_qubit,
    _qpu_id_from_register_name,
    _to_ast_qubit_ref,
)
from xdqc.circuit.dag.swap_builders import (
    PlacementSwap,
    _build_local_swap_gate,
    _build_rswap_statement_from_positions,
    _candidate_comp_slots_for_qpu,
    _validate_local_swap_pair,
)
from xdqc.preprocessing.qasm import rename_quantum_gate
from xdqc.preprocessing.qasm.types import (
    CircuitQubit,
    CleanedQuantumGate,
    CleanedStatement,
)

if TYPE_CHECKING:
    from xdqc.circuit.dag.link_selector import LinkSelector
    from xdqc.network import NetworkGraph, PhysicalQubit


_REMOTE_TWO_QUBIT_GATE_NAME_MAP = {
    "cx": "rcx",
    "cp": "rcp",
    "cry": "rcry",
    "cz": "rcz",
    "swap": "rswap",
}


def _circuit_qubit_position(qubit: CircuitQubit) -> tuple[int, int]:
    """Return the ``(qpu_id, slot)`` schedule-space position of a qubit."""
    return (
        _qpu_id_from_register_name(qubit.register_name),
        qubit.index,
    )


def _build_remote_gate_statements(
    statement: CleanedQuantumGate,
    mapped_node: ast.Statement,
    network_qubit_a: PhysicalQubit,
    network_qubit_b: PhysicalQubit,
    gate_qubits: list[CircuitQubit],
    network: NetworkGraph,
    link_selector: LinkSelector,
) -> tuple[list[CleanedStatement], int, list[PlacementSwap]]:
    """Build statements for one remote two-qubit gate execution."""
    raw_comm_pair, local_paths = _select_direct_remote_gate_option(
        network_qubit_a,
        network_qubit_b,
        network,
        link_selector,
    )

    # The remote gate acts on the last computation qubit before each
    # communication qubit, after any local swaps have been applied.
    updated_gate_qubit_a = (
        local_paths[0][-2] if len(local_paths[0]) > 1 else network_qubit_a
    )
    updated_gate_qubit_b = (
        local_paths[1][-2] if len(local_paths[1]) > 1 else network_qubit_b
    )
    remote_gate_qubits = [
        _physical_to_circuit_qubit(updated_gate_qubit_a),
        _physical_to_circuit_qubit(updated_gate_qubit_b),
    ]

    gate_statements: list[CleanedStatement] = []
    placement_swaps: list[PlacementSwap] = []
    local_swaps_added = 0
    for local_path in local_paths:
        # Already adjacent to the communication qubit; no local swap needed.
        if len(local_path) <= 2:
            continue

        # Move the data qubit toward the communication qubit one local hop
        # at a time.
        for comp_qubit_pos in range(len(local_path) - 2):
            q0 = _physical_to_circuit_qubit(local_path[comp_qubit_pos])
            q1 = _physical_to_circuit_qubit(local_path[comp_qubit_pos + 1])
            _validate_local_swap_pair(q0, q1)
            swap_node, swap_qubits = _build_local_swap_gate(q0, q1)
            swap_gate_statement = CleanedQuantumGate(
                statement_type=ast.QuantumGate,
                node=swap_node,
                is_op=True,
                name="swap",
                qubits=swap_qubits,
            )
            gate_statements.append(swap_gate_statement)
            placement_swaps.append(
                (
                    (_qpu_id_from_register_name(q0.register_name), q0.index),
                    (_qpu_id_from_register_name(q1.register_name), q1.index),
                )
            )
            local_swaps_added += 1

    remote_gate_name = _REMOTE_TWO_QUBIT_GATE_NAME_MAP.get(statement.name)
    if remote_gate_name is None:
        raise ValueError(
            "Unsupported remote two-qubit gate "
            f"{statement.name!r}. Supported gates are: "
            f"{sorted(_REMOTE_TWO_QUBIT_GATE_NAME_MAP)}."
        )

    # A source-level swap across QPUs is a remote swap: two state
    # teleportations over two disjoint e-bit pairs, emitted standalone
    # rather than wrapped in cat-entanglement. Build it through the same
    # helper every other rswap origin uses so the operand payload matches.
    if remote_gate_name == "rswap":
        gate_statements.append(
            _build_rswap_statement_from_positions(
                pos0=_circuit_qubit_position(remote_gate_qubits[0]),
                pos1=_circuit_qubit_position(remote_gate_qubits[1]),
                network=network,
            )
        )
        return gate_statements, local_swaps_added, placement_swaps

    comm_pair = _order_comm_pair(gate_qubits, raw_comm_pair)
    remote_gate_qubits.extend(
        [
            _physical_to_circuit_qubit(comm_pair[0]),
            _physical_to_circuit_qubit(comm_pair[1]),
        ]
    )
    updated_node = rename_quantum_gate(
        cast(ast.QuantumGate, mapped_node),
        remote_gate_name,
    )
    updated_node.qubits = [
        _to_ast_qubit_ref(qubit) for qubit in remote_gate_qubits
    ]
    remote_gate_statement = CleanedQuantumGate(
        statement_type=statement.statement_type,
        node=updated_node,
        is_op=statement.is_op,
        name=remote_gate_name,
        qubits=remote_gate_qubits,
    )

    cat_ent_gate, cat_disent_gate = _build_entanglement_statements(
        remote_gate_qubits[:2],
        (comm_pair,),
    )

    gate_statements.append(cat_ent_gate)
    gate_statements.append(remote_gate_statement)
    gate_statements.append(cat_disent_gate)

    return gate_statements, local_swaps_added, placement_swaps


def _select_direct_remote_gate_option(
    network_qubit_a: PhysicalQubit,
    network_qubit_b: PhysicalQubit,
    network: NetworkGraph,
    link_selector: LinkSelector,
) -> tuple[
    tuple[PhysicalQubit, PhysicalQubit],
    tuple[list[PhysicalQubit], list[PhysicalQubit]],
]:
    """Return a direct remote-gate option, balancing equal-cost links."""
    valid_options = [
        option
        for option in network.get_comm_pair_options(
            network_qubit_a,
            network_qubit_b,
        )
        if _remote_local_paths_are_valid(option[2])
    ]
    if not valid_options:
        raise ValueError(
            "No valid direct remote-gate path keeps data operands on "
            "computation qubits."
        )
    return link_selector.select(valid_options)


def _remote_local_paths_are_valid(
    local_paths: tuple[list[PhysicalQubit], list[PhysicalQubit]],
) -> bool:
    """Return whether both local paths keep data qubits on computation nodes."""
    return all(_remote_local_path_is_valid(path) for path in local_paths)


def _remote_local_path_is_valid(local_path: list[PhysicalQubit]) -> bool:
    """Return whether one local path is valid for remote gate execution."""
    # The path must start on a computation qubit and end on a communication
    # qubit, with only computation qubits in between.
    if len(local_path) < 2:
        return False
    if not local_path[0].is_computation:
        return False
    if not local_path[-1].is_communication:
        return False
    if not local_path[-2].is_computation:
        return False
    return all(qubit.is_computation for qubit in local_path[:-1])


def _is_non_routable_direct_remote_gate_error(error: ValueError) -> bool:
    """Return whether a direct remote-gate error should not trigger routing."""
    return (
        "No valid direct remote-gate path keeps data operands on "
        "computation qubits."
        in str(error)
        or "Unsupported remote two-qubit gate " in str(error)
        # A remote swap needs two disjoint e-bit pairs. Routing the gate
        # through an intermediary QPU cannot supply them, so surface the
        # teleportation error rather than a misleading routing failure.
        or "State teleportation not supported" in str(error)
    )


def _build_routed_remote_gate_statements(
    statement: CleanedQuantumGate,
    mapped_node: ast.Statement,
    gate_qubits: list[CircuitQubit],
    circuit_qubit_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
    network: NetworkGraph,
    moving_operand_idx: int,
    link_selector: LinkSelector,
) -> tuple[list[CleanedStatement], int, list[PlacementSwap]]:
    """Build statements for a routed remote gate via intermediary QPUs."""
    moving_gate_qubit = gate_qubits[moving_operand_idx]
    static_gate_qubit = gate_qubits[1 - moving_operand_idx]
    moving_network_qubit = _circuit_qubit_to_physical_qubit(moving_gate_qubit)
    static_network_qubit = _circuit_qubit_to_physical_qubit(static_gate_qubit)
    route_qpu_ids = network.get_qpu_route(
        moving_network_qubit.qpu_id,
        static_network_qubit.qpu_id,
    )
    if len(route_qpu_ids) <= 2:
        raise ValueError(
            "Routed remote-gate execution requires at least one intermediary "
            f"QPU for directional movement {route_qpu_ids!r}."
        )

    # Track the moving operand as it is routed toward the target.
    moved_pos = (
        _qpu_id_from_register_name(moving_gate_qubit.register_name),
        moving_gate_qubit.index,
    )
    static_pos = (
        _qpu_id_from_register_name(static_gate_qubit.register_name),
        static_gate_qubit.index,
    )
    routed_statements: list[CleanedStatement] = []
    placement_swaps: list[PlacementSwap] = []

    # Stop one QPU before the target. The final interaction is still a
    # remote gate, not another routed hop onto the target QPU.
    for next_qpu_id in route_qpu_ids[1:-1]:
        rswap_statement, next_pos, placement_swap = (
            _build_routed_remote_gate_hop(
                moved_pos=moved_pos,
                static_pos=static_pos,
                next_qpu_id=next_qpu_id,
                circuit_qubit_to_physical_window=(
                    circuit_qubit_to_physical_window
                ),
                comp_capacity_by_schedule_qpu=comp_capacity_by_schedule_qpu,
                network=network,
            )
        )
        routed_statements.append(rswap_statement)
        placement_swaps.append(placement_swap)
        moved_pos = next_pos

    moved_gate_qubit = CircuitQubit(
        register_name=f"q{moved_pos[0]}",
        index=moved_pos[1],
    )
    moved_network_qubit = _circuit_qubit_to_physical_qubit(moved_gate_qubit)

    # Preserve the original gate operand order after routing one operand.
    if moving_operand_idx == 0:
        ordered_gate_qubits = [moved_gate_qubit, static_gate_qubit]
        network_gate_qubits = (moved_network_qubit, static_network_qubit)
    else:
        ordered_gate_qubits = [static_gate_qubit, moved_gate_qubit]
        network_gate_qubits = (static_network_qubit, moved_network_qubit)

    (
        routed_gate_statements,
        added_local_swaps,
        routed_gate_placement_swaps,
    ) = _build_remote_gate_statements(
        statement=statement,
        mapped_node=mapped_node,
        network_qubit_a=network_gate_qubits[0],
        network_qubit_b=network_gate_qubits[1],
        gate_qubits=ordered_gate_qubits,
        network=network,
        link_selector=link_selector,
    )
    routed_statements.extend(routed_gate_statements)
    placement_swaps.extend(routed_gate_placement_swaps)

    return routed_statements, added_local_swaps, placement_swaps


def _build_routed_remote_gate_hop(
    moved_pos: tuple[int, int],
    static_pos: tuple[int, int],
    next_qpu_id: int,
    circuit_qubit_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
    network: NetworkGraph,
) -> tuple[CleanedQuantumGate, tuple[int, int], PlacementSwap]:
    """Build one routed ``rswap`` hop for a moving remote-gate operand."""
    candidate_slots = _candidate_comp_slots_for_qpu(
        qpu_id=next_qpu_id,
        circuit_qubit_to_physical_window=circuit_qubit_to_physical_window,
        comp_capacity_by_schedule_qpu=comp_capacity_by_schedule_qpu,
    )
    if not candidate_slots:
        raise ValueError(
            "No computation slot available on intermediary QPU "
            f"{next_qpu_id} while routing remote gate."
        )

    # Try intermediary slots in preference order until one produces a valid
    # routed swap and does not collide with the static operand.
    for candidate_slot in candidate_slots:
        next_pos = (next_qpu_id, candidate_slot)
        if next_pos == static_pos:
            continue
        try:
            rswap_statement = _build_rswap_statement_from_positions(
                pos0=moved_pos,
                pos1=next_pos,
                network=network,
            )
        except ValueError:
            continue
        return rswap_statement, next_pos, (moved_pos, next_pos)

    raise ValueError(
        "Unable to build routed remote gate hop from "
        f"position {moved_pos} to QPU {next_qpu_id}."
    )
