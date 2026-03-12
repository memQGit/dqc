# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Remote-gate routing helpers for distributed DAG construction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openqasm3 import ast

from memq_dqc.circuit.dag.remap import (
    _circuit_qubit_to_physical_qubit,
    _order_comm_pair,
    _physical_to_circuit_qubit,
    _qpu_id_from_register_name,
    _to_ast_qubit_ref,
)
from memq_dqc.circuit.dag.swap_builders import (
    _build_local_swap_gate,
    _build_rswap_statement_from_positions,
    _candidate_comp_slots_for_qpu,
    _validate_local_swap_pair,
)
from memq_dqc.preprocessing.qasm import rename_quantum_gate
from memq_dqc.preprocessing.qasm.types import (
    CircuitQubit,
    CleanedQuantumGate,
    CleanedStatement,
)

if TYPE_CHECKING:
    from memq_dqc.network import NetworkGraph, PhysicalQubit


_REMOTE_TWO_QUBIT_GATE_NAME_MAP = {
    "cx": "rcx",
    "cp": "rcp",
    "cry": "rcry",
    "cz": "rcz",
    "swap": "rswap",
}


def _build_remote_gate_statements(
    statement: CleanedQuantumGate,
    mapped_node: ast.Statement,
    network_qubit_a: PhysicalQubit,
    network_qubit_b: PhysicalQubit,
    gate_qubits: list[CircuitQubit],
    network: NetworkGraph,
) -> tuple[list[CleanedStatement], int]:
    """Build statements for one remote two-qubit gate execution."""
    raw_comm_pair = None
    local_paths = None
    for _, candidate_pair, candidate_paths in network.get_comm_pair_options(
        network_qubit_a, network_qubit_b
    ):
        if _remote_local_paths_are_valid(candidate_paths):
            raw_comm_pair = candidate_pair
            local_paths = candidate_paths
            break
    if raw_comm_pair is None or local_paths is None:
        raise ValueError(
            "No valid direct remote-gate path keeps data operands on "
            "computation qubits."
        )
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
    swap_gate_statements: list[CleanedStatement] = []
    local_swaps_added = 0
    for local_path in local_paths:
        # Already adjecent to comm qubit; no swap needed
        if len(local_path) <= 2:
            continue

        # Move the data qubit along the local path one edge at a time.
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
            swap_gate_statements.append(swap_gate_statement)
            local_swaps_added += 1

    comm_pair = _order_comm_pair(gate_qubits, raw_comm_pair)
    remote_gate_qubits.extend(
        [
            _physical_to_circuit_qubit(comm_pair[0]),
            _physical_to_circuit_qubit(comm_pair[1]),
        ]
    )
    remote_gate_name = _REMOTE_TWO_QUBIT_GATE_NAME_MAP.get(statement.name)
    if remote_gate_name is None:
        raise ValueError(
            "Unsupported remote two-qubit gate "
            f"{statement.name!r}. Supported gates are: "
            f"{sorted(_REMOTE_TWO_QUBIT_GATE_NAME_MAP)}."
        )
    updated_node = rename_quantum_gate(mapped_node, remote_gate_name)
    updated_node.qubits = [
        _to_ast_qubit_ref(qubit) for qubit in remote_gate_qubits
    ]
    gate_statements.append(
        CleanedQuantumGate(
            statement_type=statement.statement_type,
            node=updated_node,
            is_op=statement.is_op,
            name=remote_gate_name,
            qubits=remote_gate_qubits,
        )
    )

    swap_gate_statements.reverse()
    for swap_gate_statement in swap_gate_statements:
        gate_statements.append(swap_gate_statement)
        local_swaps_added += 1

    return gate_statements, local_swaps_added


def _remote_local_paths_are_valid(
    local_paths: tuple[list[PhysicalQubit], list[PhysicalQubit]],
) -> bool:
    """Return whether both local paths keep data qubits on computation nodes."""
    return all(_remote_local_path_is_valid(path) for path in local_paths)


def _remote_local_path_is_valid(local_path: list[PhysicalQubit]) -> bool:
    """Return whether one local path is valid for remote gate execution."""
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
    )


def _build_routed_remote_gate_statements(
    statement: CleanedQuantumGate,
    mapped_node: ast.Statement,
    gate_qubits: list[CircuitQubit],
    circuit_qubit_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
    network: NetworkGraph,
    moving_operand_idx: int,
) -> tuple[list[CleanedStatement], int]:
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

    # Track the moving operand as it is temporarily routed toward the target.
    moved_pos = (
        _qpu_id_from_register_name(moving_gate_qubit.register_name),
        moving_gate_qubit.index,
    )
    static_pos = (
        _qpu_id_from_register_name(static_gate_qubit.register_name),
        static_gate_qubit.index,
    )
    routed_statements: list[CleanedStatement] = []
    forward_hop_positions: list[tuple[tuple[int, int], tuple[int, int]]] = []

    # Stop one QPU before the target. The final interaction is still a
    # remote gate, not another routed hop onto the target QPU.
    for next_qpu_id in route_qpu_ids[1:-1]:
        rswap_statement, next_pos = _build_routed_remote_gate_hop(
            moved_pos=moved_pos,
            static_pos=static_pos,
            next_qpu_id=next_qpu_id,
            circuit_qubit_to_physical_window=circuit_qubit_to_physical_window,
            comp_capacity_by_schedule_qpu=comp_capacity_by_schedule_qpu,
            network=network,
        )
        routed_statements.append(rswap_statement)
        forward_hop_positions.append((moved_pos, next_pos))
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

    routed_gate_statements, added_local_swaps = _build_remote_gate_statements(
        statement=statement,
        mapped_node=mapped_node,
        network_qubit_a=network_gate_qubits[0],
        network_qubit_b=network_gate_qubits[1],
        gate_qubits=ordered_gate_qubits,
        network=network,
    )
    routed_statements.extend(routed_gate_statements)

    # Undo the temporary routed hops to restore the original placement.
    for pos0, pos1 in reversed(forward_hop_positions):
        routed_statements.append(
            _build_rswap_statement_from_positions(
                pos0=pos0,
                pos1=pos1,
                network=network,
            )
        )

    return routed_statements, added_local_swaps


def _build_routed_remote_gate_hop(
    moved_pos: tuple[int, int],
    static_pos: tuple[int, int],
    next_qpu_id: int,
    circuit_qubit_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
    network: NetworkGraph,
) -> tuple[CleanedQuantumGate, tuple[int, int]]:
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
        return rswap_statement, next_pos

    raise ValueError(
        "Unable to build routed remote gate hop from "
        f"position {moved_pos} to QPU {next_qpu_id}."
    )
