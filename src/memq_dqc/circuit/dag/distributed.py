# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Distributed DAG representation and statement-building helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING, cast

from openqasm3 import ast

from memq_dqc.builder.extract_utils import (
    SwapOp,
    circuit_qubit_physical_map,
    window_final_op_id_map,
)
from memq_dqc.circuit.dag.mono import CircuitDAG
from memq_dqc.circuit.dag.remap import (
    _circuit_qubit_to_physical_qubit,
    _ordered_network_qpu_ids,
    _remap_cleaned_qubit,
    _remap_cleaned_qubits,
    _remap_statement_qubits,
    _replace_qubit_declarations,
    _replace_statement_node,
)
from memq_dqc.circuit.dag.routing import (
    _build_remote_gate_statements,
    _build_routed_remote_gate_statements,
    _is_non_routable_direct_remote_gate_error,
)
from memq_dqc.circuit.dag.swap_builders import (
    _build_rswap_statements_for_swap,
)
from memq_dqc.circuit.op import Op
from memq_dqc.preprocessing.qasm import clone_statement_node
from memq_dqc.preprocessing.qasm.types import (
    CircuitQubit,
    CleanedIncludeStatement,
    CleanedQuantumGate,
    CleanedQuantumMeasurementStatement,
    CleanedStatement,
)
from memq_dqc.utils.common import window_op_map

if TYPE_CHECKING:
    from memq_dqc.network import NetworkGraph
    from memq_dqc.partition.partitioner import QPU


class DistributedCircuitDAG(CircuitDAG):
    """DAG representation for distributed circuit operations.

    Inherits methods and attributes from base CircuitDAG, and adds a few
    distributed-specific utilities and attributes.
    """


def _build_remote_or_routed_gate_statements(
    statement: CleanedQuantumGate,
    mapped_node: ast.Statement,
    gate_qubits: list[CircuitQubit],
    circuit_qubit_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
    network: NetworkGraph,
) -> tuple[list[CleanedStatement], int]:
    """Build a direct remote gate, or fall back to routed execution."""
    network_qubit_a = _circuit_qubit_to_physical_qubit(gate_qubits[0])
    network_qubit_b = _circuit_qubit_to_physical_qubit(gate_qubits[1])
    direct_error: ValueError | None = None
    try:
        return _build_remote_gate_statements(
            statement=statement,
            mapped_node=mapped_node,
            network_qubit_a=network_qubit_a,
            network_qubit_b=network_qubit_b,
            gate_qubits=gate_qubits,
            network=network,
        )
    except ValueError as direct_gate_error:
        direct_error = direct_gate_error
        # Some direct-gate failures should surface immediately; the rest get a
        # second pass that tries routing either operand through intermediary
        # QPUs.
        if _is_non_routable_direct_remote_gate_error(direct_gate_error):
            raise direct_gate_error

    routed_error: ValueError | None = None
    for moving_operand_idx in (0, 1):
        try:
            return _build_routed_remote_gate_statements(
                statement=statement,
                mapped_node=mapped_node,
                gate_qubits=gate_qubits,
                circuit_qubit_to_physical_window=(
                    circuit_qubit_to_physical_window
                ),
                comp_capacity_by_schedule_qpu=comp_capacity_by_schedule_qpu,
                network=network,
                moving_operand_idx=moving_operand_idx,
            )
        except ValueError as route_err:
            routed_error = route_err

    if routed_error is not None:
        raise routed_error from direct_error
    if direct_error is not None:
        raise direct_error
    raise RuntimeError("Unreachable remote-gate fallback state.")


def build_distributed_statements(
    statements: list[CleanedStatement],
    remote_statement_ids: set[int],
    windows: list[list[Op]],
    swaps_schedule: list[list[SwapOp]],
    schedule: list[dict[QPU, set[int]]],
    network: NetworkGraph,
    comp_qubits_per_qpu: list[int] | None = None,
    comm_qubits_per_qpu: list[int] | None = None,
) -> tuple[list[CleanedStatement], int]:
    """Build distributed program statements with remote operations.

    Utilizes partition to remap circuit qubits to physical qubits, then
    inserts necessary state teleport and gate teleport operations to build
    the distributed program from the orginal monolithic program.

    Args:
        statements: Cleaned statements from the base circuit.
        remote_statement_ids: Statement indices that should be converted to
            remote gate variants.
        windows: Operation windows used for schedule-aware remapping.
        swaps_schedule: Swap operations inserted between adjacent windows.
        schedule: Per-window mapping from QPU to assigned circuit qubits.
        comp_qubits_per_qpu: Optional computation-qubit capacities by QPU.
        comm_qubits_per_qpu: Optional communication-qubit counts by QPU.
        network: Network graph used to derive communication pairs.

    Returns:
        The updated cleaned statements and the number of inserted local swaps.

    Raises:
        ValueError: If window, schedule, or swap dimensions are invalid.
    """
    if network is None:
        raise ValueError(
            "Network graph is required to build distributed circuits."
        )

    # Confirm logical checks of input dimensions
    if not windows:
        raise ValueError("windows must contain at least one window.")
    if len(schedule) != len(windows):
        raise ValueError(
            "schedule/windows length mismatch: "
            f"len(schedule)={len(schedule)} != len(windows)={len(windows)}."
        )
    expected_swaps_windows = len(windows) - 1
    if len(swaps_schedule) != expected_swaps_windows:
        raise ValueError(
            "swaps_schedule length mismatch: "
            f"len(swaps_schedule)={len(swaps_schedule)} != "
            f"len(windows)-1={expected_swaps_windows}."
        )

    num_swaps = sum(len(swaps) for swaps in swaps_schedule)
    # Get list of all ids to insert swaps (final op of each window except last)
    final_ops_in_windows = set(window_final_op_id_map(windows).values())
    # Create dictionary that maps each operation ID to its window index
    window_map = window_op_map(windows)
    circuit_qubit_to_physical = circuit_qubit_physical_map(
        schedule, swaps_schedule
    )
    # Create sorted list of QPU ID's from the schedule
    schedule_qpu_ids = sorted(qpu.id for qpu in schedule[0].keys())

    # Determine # of computation qubits for each QPU
    comp_capacity_by_schedule_qpu: dict[int, int] | None = None
    if comp_qubits_per_qpu is not None:
        if len(comp_qubits_per_qpu) != len(schedule_qpu_ids):
            raise ValueError(
                "comp_qubits_per_qpu length must match the number of "
                "QPUs in schedule: "
                f"{len(comp_qubits_per_qpu)} != "
                f"{len(schedule_qpu_ids)}."
            )
        comp_capacity_by_schedule_qpu = {
            schedule_qpu_id: comp_qubits_per_qpu[idx]
            for idx, schedule_qpu_id in enumerate(schedule_qpu_ids)
        }

    # Confirm QPU ids in schedule match those in network
    network_qpu_ids = _ordered_network_qpu_ids(network)
    if schedule_qpu_ids != network_qpu_ids:
        raise ValueError(
            "Schedule QPU IDs must match network QPU IDs: "
            f"{schedule_qpu_ids} != {network_qpu_ids}."
        )

    # Build list of statements for distributed program
    distributed_statements: list[CleanedStatement] = []
    local_swaps_added = 0
    op_id = -1
    swap_window_idx = 0
    current_window_idx = 0
    for idx, statement in enumerate(statements):
        # Update statement node with correct physical qubit mapping
        mapped_node = statement.node
        if statement.is_op:
            op_id += 1
            # Determine window of current statement (if it is an operation)
            current_window_idx = window_map.get(op_id, current_window_idx)

        # Update statement node with correct network ('physical') qubit mapping
        mapped_node = _remap_statement_qubits(
            mapped_node,
            circuit_qubit_to_physical[current_window_idx],
        )

        # Rebuild list of statements using appropriate remote gates
        if idx in remote_statement_ids and isinstance(
            statement, CleanedQuantumGate
        ):
            # Remap the logical gate operands into the current window's QPU
            # register space before building remote-gate statements.
            gate_qubits = _remap_cleaned_qubits(
                statement.qubits,
                circuit_qubit_to_physical[current_window_idx],
            )
            remote_gate_statements, added_local_swaps = (
                _build_remote_or_routed_gate_statements(
                    statement=statement,
                    mapped_node=mapped_node,
                    gate_qubits=gate_qubits,
                    circuit_qubit_to_physical_window=(
                        circuit_qubit_to_physical[current_window_idx]
                    ),
                    comp_capacity_by_schedule_qpu=(
                        comp_capacity_by_schedule_qpu
                    ),
                    network=network,
                )
            )
            distributed_statements.extend(remote_gate_statements)
            local_swaps_added += added_local_swaps
        # Insert non-remote gates
        else:
            if isinstance(statement, CleanedQuantumGate):
                distributed_statements.append(
                    CleanedQuantumGate(
                        statement_type=statement.statement_type,
                        node=mapped_node,
                        is_op=statement.is_op,
                        name=statement.name,
                        qubits=_remap_cleaned_qubits(
                            statement.qubits,
                            circuit_qubit_to_physical[current_window_idx],
                        ),
                    )
                )
            elif isinstance(statement, CleanedQuantumMeasurementStatement):
                distributed_statements.append(
                    CleanedQuantumMeasurementStatement(
                        statement_type=statement.statement_type,
                        node=mapped_node,
                        is_op=statement.is_op,
                        qubit=_remap_cleaned_qubit(
                            statement.qubit,
                            circuit_qubit_to_physical[current_window_idx],
                        ),
                        cbit=statement.cbit,
                    )
                )
            else:
                distributed_statements.append(
                    _replace_statement_node(statement, mapped_node)
                )
        # If we find final op in window, insert remote swaps to reach next partition
        if statement.is_op and op_id in final_ops_in_windows:
            swaps = swaps_schedule[swap_window_idx]
            network_graph = network
            if swaps and network_graph is None:
                raise ValueError(
                    "Network graph is required to build remote swaps "
                    "with communication qubits."
                )
            for swap in swaps:
                if network_graph is None:
                    raise ValueError(
                        "Network graph is required to build remote swaps "
                        "with communication qubits."
                    )
                distributed_statements.extend(
                    _build_rswap_statements_for_swap(
                        swap=swap,
                        network=network_graph,
                        circuit_qubit_to_physical_window=(
                            circuit_qubit_to_physical[current_window_idx]
                        ),
                        comp_capacity_by_schedule_qpu=(
                            comp_capacity_by_schedule_qpu
                        ),
                    )
                )
            current_window_idx += 1
            swap_window_idx += 1
    # Add custom distributed gateset if remote gates or swaps are present
    if remote_statement_ids or num_swaps > 0:
        include_node = clone_statement_node(
            ast.Include(filename="builder/distgates.inc")
        )
        dist_include = CleanedIncludeStatement(
            statement_type=ast.Include,
            node=include_node,
            is_op=False,
            filename="builder/distgates.inc",
        )
        distributed_statements.insert(0, cast(CleanedStatement, dist_include))
    distributed_statements = _replace_qubit_declarations(
        distributed_statements,
        schedule,
        comp_qubits_per_qpu,
        comm_qubits_per_qpu,
    )
    return distributed_statements, local_swaps_added


def count_remote_gates(
    ops: list[Op],
) -> int:
    """Count operations marked as remote.

    Args:
        ops: Operations in the distributed circuit.

    Returns:
        The number of operations tagged as remote gates.
    """
    return sum(
        1 for op in ops if op.name.startswith("r") and op.name != "rswap"
    )
