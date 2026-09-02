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

"""Distributed DAG representation and statement-building helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, cast

from openqasm3 import ast

from memq_dqc.builder.extract_utils import (
    SwapOp,
    circuit_qubit_physical_map,
    window_final_op_id_map,
)
from memq_dqc.circuit.dag.link_selector import LinkSelector
from memq_dqc.circuit.dag.mono import CircuitDAG
from memq_dqc.circuit.dag.remap import (
    _circuit_qubit_to_physical_qubit,
    _ordered_network_qpu_ids,
    _qpu_id_from_register_name,
    _remap_cleaned_qubit,
    _remap_cleaned_qubits,
    _remap_statement_qubits,
    _replace_qubit_declarations,
    _replace_statement_node,
    _to_ast_qubit_ref,
)
from memq_dqc.circuit.dag.routing import (
    _build_remote_gate_statements,
    _build_routed_remote_gate_statements,
    _is_non_routable_direct_remote_gate_error,
)
from memq_dqc.circuit.dag.swap_builders import (
    PlacementSwap,
    _build_local_swap_gate,
    _build_rswap_statements_for_swap,
    _validate_local_swap_pair,
)
from memq_dqc.circuit.op import Op
from memq_dqc.preprocessing.qasm.ast_utils import clone_statement_node
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

_REMOTE_GATE_NAMES = frozenset({"rcx", "rcp", "rcry", "rcz", "rswap"})
_DEFERRED_EBIT_GATE_NAMES = _REMOTE_GATE_NAMES | {"catent", "catdisent"}


@dataclass(slots=True)
class _ActiveGateGroup:
    """Mutable emission state for one source-order gate group."""

    member_op_ids: frozenset[int]
    end_op_id: int
    enabled: bool = True
    control_qubit: CircuitQubit | None = None
    partner_qpu_id: int | None = None
    comm_qubits: tuple[CircuitQubit, ...] | None = None
    catent: CleanedQuantumGate | None = None
    catdisent: CleanedQuantumGate | None = None


class DistributedCircuitDAG(CircuitDAG):
    """DAG representation for distributed circuit operations.

    Inherits methods and attributes from base CircuitDAG, and adds a few
    distributed-specific utilities and attributes.
    """

    def __init__(
        self,
        ops: list[Op],
        *,
        ignore_remote_ebit_dependencies: bool = False,
    ) -> None:
        """Initialize a distributed DAG.

        Args:
            ops: Distributed operations in source order.
            ignore_remote_ebit_dependencies: Whether remote-operation
                communication operands should be ignored for dependency edges.
        """
        self.ignore_remote_ebit_dependencies = ignore_remote_ebit_dependencies
        super().__init__(ops)

    def _dependency_qubits(self, op: Op) -> tuple[CircuitQubit, ...]:
        """Return qubits that contribute dependencies for a distributed op."""
        if self.ignore_remote_ebit_dependencies and op.is_remote:
            return op.qubits[:2]
        return op.qubits


def _build_remote_or_routed_gate_statements(
    statement: CleanedQuantumGate,
    mapped_node: ast.Statement,
    gate_qubits: list[CircuitQubit],
    circuit_qubit_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
    network: NetworkGraph,
    link_selector: LinkSelector,
) -> tuple[list[CleanedStatement], int, list[PlacementSwap]]:
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
            link_selector=link_selector,
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
                link_selector=link_selector,
            )
        except ValueError as route_err:
            routed_error = route_err

    if routed_error is not None:
        raise routed_error from direct_error
    if direct_error is not None:
        raise direct_error
    raise RuntimeError("Unreachable remote-gate fallback state.")


def _cleaned_qubits_cross_qpus(qubits: list[CircuitQubit]) -> bool:
    """Return whether the first two operands live on different QPUs."""
    if len(qubits) != 2:
        return False
    return _qpu_id_from_register_name(
        qubits[0].register_name
    ) != _qpu_id_from_register_name(qubits[1].register_name)


def _apply_placement_swaps(
    circuit_qubit_to_physical: dict[int, tuple[int, int]],
    placement_swaps: list[PlacementSwap],
) -> None:
    """Apply emitted physical swaps to the live logical placement map."""
    for pos0, pos1 in placement_swaps:
        _apply_placement_swap(circuit_qubit_to_physical, pos0, pos1)


def _apply_placement_swap(
    circuit_qubit_to_physical: dict[int, tuple[int, int]],
    pos0: tuple[int, int],
    pos1: tuple[int, int],
) -> None:
    """Apply one physical swap to the live logical placement map."""
    logical_by_pos = {
        pos: logical_qubit
        for logical_qubit, pos in circuit_qubit_to_physical.items()
    }
    q0 = logical_by_pos.get(pos0)
    q1 = logical_by_pos.get(pos1)
    if q0 is not None:
        circuit_qubit_to_physical[q0] = pos1
    if q1 is not None:
        circuit_qubit_to_physical[q1] = pos0


def build_distributed_statements(
    statements: list[CleanedStatement],
    remote_statement_ids: set[int],
    windows: list[list[Op]],
    swaps_schedule: list[list[SwapOp]],
    schedule: list[dict[QPU, set[int]]],
    network: NetworkGraph,
    comp_qubits_per_qpu: list[int] | None = None,
    comm_qubits_per_qpu: list[int] | None = None,
    ebit_assignment: bool = True,
    gate_group_op_ids: tuple[tuple[int, ...], ...] = (),
) -> tuple[list[CleanedStatement], int]:
    """Build distributed program statements with remote operations.

    Utilizes partition to remap circuit qubits to physical qubits, then
    inserts necessary state teleport and gate teleport operations to build
    the distributed program from the original monolithic program.

    Args:
        statements: Cleaned statements from the base circuit.
        remote_statement_ids: Statement indices identified as remote before
            routing. The builder rechecks live placements while emitting
            statements because inserted swaps can change later placements.
        windows: Operation windows used for schedule-aware remapping.
        swaps_schedule: Swap operations inserted between adjacent windows.
        schedule: Per-window mapping from QPU to assigned circuit qubits.
        comp_qubits_per_qpu: Optional computation-qubit capacities by QPU.
        comm_qubits_per_qpu: Optional communication-qubit counts by QPU.
        network: Network graph used to derive communication pairs.
        ebit_assignment: Whether remote operations should include concrete
            communication-qubit operands and declarations.
        gate_group_op_ids: Operation IDs for detected gate groups that may
            share cat-entanglement in the emitted program.

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
    current_circuit_qubit_to_physical = circuit_qubit_to_physical[0].copy()
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
    distributed_gate_emitted = False
    op_id = -1
    swap_window_idx = 0
    current_window_idx = 0
    gate_group_starts = _gate_group_starts(gate_group_op_ids)
    active_gate_group: _ActiveGateGroup | None = None
    # One selector per build balances equal-cost links across remote gates.
    link_selector = LinkSelector()
    for statement in statements:
        # Update statement node with correct physical qubit mapping
        mapped_node = statement.node
        if statement.is_op:
            op_id += 1
            # Determine window of current statement (if it is an operation)
            current_window_idx = window_map.get(op_id, current_window_idx)
            group_op_ids = gate_group_starts.get(op_id)
            if group_op_ids is not None:
                active_gate_group = _ActiveGateGroup(
                    member_op_ids=group_op_ids,
                    end_op_id=max(group_op_ids),
                )

        # Update statement node with correct network ('physical') qubit mapping
        mapped_node = _remap_statement_qubits(
            mapped_node,
            current_circuit_qubit_to_physical,
        )

        # Rebuild list of statements using appropriate remote gates
        if (
            isinstance(statement, CleanedQuantumGate)
            and len(statement.qubits) == 2
            and _cleaned_qubits_cross_qpus(
                _remap_cleaned_qubits(
                    statement.qubits,
                    current_circuit_qubit_to_physical,
                )
            )
        ):
            if (
                active_gate_group is not None
                and op_id not in active_gate_group.member_op_ids
            ):
                _close_active_gate_group(
                    distributed_statements,
                    active_gate_group,
                )
                active_gate_group = None
                # Group over: resume balancing across equal-cost links.
                link_selector.release()
            # Remap the logical gate operands into the current window's QPU
            # register space before building remote-gate statements.
            gate_qubits = _remap_cleaned_qubits(
                statement.qubits,
                current_circuit_qubit_to_physical,
            )
            (
                remote_gate_statements,
                added_local_swaps,
                placement_swaps,
            ) = _build_remote_or_routed_gate_statements(
                statement=statement,
                mapped_node=mapped_node,
                gate_qubits=gate_qubits,
                circuit_qubit_to_physical_window=(
                    current_circuit_qubit_to_physical
                ),
                comp_capacity_by_schedule_qpu=(comp_capacity_by_schedule_qpu),
                network=network,
                link_selector=link_selector,
            )
            if (
                active_gate_group is not None
                and op_id in active_gate_group.member_op_ids
                and _append_grouped_remote_gate(
                    distributed_statements,
                    active_gate_group,
                    remote_gate_statements,
                    added_local_swaps,
                    placement_swaps,
                )
            ):
                distributed_gate_emitted = True
                # Pin the link this group opened on, so the remaining members
                # land on the same communication qubits and can share one
                # catent/catdisent pair instead of forcing a new one each.
                link_selector.hold()
            else:
                distributed_statements.extend(remote_gate_statements)
                distributed_gate_emitted = True
                local_swaps_added += added_local_swaps
                _apply_placement_swaps(
                    current_circuit_qubit_to_physical,
                    placement_swaps,
                )
                link_selector.release()
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
                            current_circuit_qubit_to_physical,
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
                            current_circuit_qubit_to_physical,
                        ),
                        cbit=statement.cbit,
                    )
                )
            else:
                distributed_statements.append(
                    _replace_statement_node(statement, mapped_node)
                )
        if (
            statement.is_op
            and active_gate_group is not None
            and op_id == active_gate_group.end_op_id
        ):
            _close_active_gate_group(distributed_statements, active_gate_group)
            active_gate_group = None
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
                current_swap = SwapOp(
                    q0=swap.q0,
                    q1=swap.q1,
                    pos0=current_circuit_qubit_to_physical[swap.q0],
                    pos1=current_circuit_qubit_to_physical[swap.q1],
                )
                if current_swap.pos0[0] == current_swap.pos1[0]:
                    distributed_statements.append(
                        _build_local_boundary_swap(current_swap)
                    )
                    local_swaps_added += 1
                    _apply_placement_swap(
                        current_circuit_qubit_to_physical,
                        current_swap.pos0,
                        current_swap.pos1,
                    )
                    continue
                swap_statements, placement_swaps = (
                    _build_rswap_statements_for_swap(
                        swap=current_swap,
                        network=network_graph,
                        circuit_qubit_to_physical_window=(
                            current_circuit_qubit_to_physical
                        ),
                        comp_capacity_by_schedule_qpu=(
                            comp_capacity_by_schedule_qpu
                        ),
                    )
                )
                distributed_statements.extend(swap_statements)
                distributed_gate_emitted = True
                _apply_placement_swaps(
                    current_circuit_qubit_to_physical,
                    placement_swaps,
                )
            current_window_idx += 1
            swap_window_idx += 1
    # Add custom distributed gateset if remote gates or swaps are present
    if distributed_gate_emitted or remote_statement_ids or num_swaps > 0:
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
    if not ebit_assignment:
        distributed_statements = _strip_remote_ebit_operands(
            distributed_statements
        )
    distributed_statements = _replace_qubit_declarations(
        distributed_statements,
        schedule,
        comp_qubits_per_qpu,
        comm_qubits_per_qpu if ebit_assignment else None,
    )
    return distributed_statements, local_swaps_added


def _build_local_boundary_swap(swap: SwapOp) -> CleanedQuantumGate:
    """Build a local slot swap for an already colocated boundary swap."""
    qpu_id, first_slot = swap.pos0
    _, second_slot = swap.pos1
    q0 = CircuitQubit(register_name=f"q{qpu_id}", index=first_slot)
    q1 = CircuitQubit(register_name=f"q{qpu_id}", index=second_slot)
    _validate_local_swap_pair(q0, q1)
    swap_node, swap_qubits = _build_local_swap_gate(q0, q1)
    return CleanedQuantumGate(
        statement_type=ast.QuantumGate,
        node=swap_node,
        is_op=True,
        name="swap",
        qubits=swap_qubits,
    )


def _gate_group_starts(
    gate_group_op_ids: tuple[tuple[int, ...], ...],
) -> dict[int, frozenset[int]]:
    """Return gate groups keyed by first operation ID."""
    group_starts: dict[int, frozenset[int]] = {}
    for group in gate_group_op_ids:
        if len(group) < 2:
            continue
        ordered_group = tuple(sorted(group))
        group_starts[ordered_group[0]] = frozenset(ordered_group)
    return group_starts


def _append_grouped_remote_gate(
    distributed_statements: list[CleanedStatement],
    active_gate_group: _ActiveGateGroup,
    remote_gate_statements: list[CleanedStatement],
    added_local_swaps: int,
    placement_swaps: list[PlacementSwap],
) -> bool:
    """Append one remote gate to an active group when it is compatible."""
    split_statements = _split_groupable_remote_gate(
        remote_gate_statements,
        added_local_swaps,
        placement_swaps,
    )
    if not active_gate_group.enabled or split_statements is None:
        _close_active_gate_group(distributed_statements, active_gate_group)
        active_gate_group.enabled = False
        return False

    catent, remote_gate, catdisent = split_statements
    if active_gate_group.catent is None:
        control_qubit = remote_gate.qubits[0]
        partner_qubit = remote_gate.qubits[1]
        active_gate_group.control_qubit = control_qubit
        active_gate_group.partner_qpu_id = _qpu_id_from_register_name(
            partner_qubit.register_name
        )
        active_gate_group.comm_qubits = tuple(catent.qubits[2:])
        active_gate_group.catent = catent
        active_gate_group.catdisent = catdisent
        distributed_statements.append(catent)
        distributed_statements.append(remote_gate)
        return True

    if not _remote_gate_matches_active_group(
        active_gate_group,
        catent,
        remote_gate,
        catdisent,
    ):
        _close_active_gate_group(distributed_statements, active_gate_group)
        active_gate_group.enabled = False
        return False

    distributed_statements.append(remote_gate)
    return True


def _remote_gate_matches_active_group(
    active_gate_group: _ActiveGateGroup,
    catent: CleanedQuantumGate,
    remote_gate: CleanedQuantumGate,
    catdisent: CleanedQuantumGate,
) -> bool:
    """Return whether a remote gate can reuse the active group resource."""
    control_qubit = active_gate_group.control_qubit
    partner_qpu_id = active_gate_group.partner_qpu_id
    comm_qubits = active_gate_group.comm_qubits
    if (
        control_qubit is None
        or partner_qpu_id is None
        or comm_qubits is None
        or active_gate_group.catdisent is None
    ):
        return False

    other_qubit = _remote_gate_other_group_qubit(remote_gate, control_qubit)
    if other_qubit is None:
        return False
    if _qpu_id_from_register_name(other_qubit.register_name) != partner_qpu_id:
        return False
    if tuple(catent.qubits[2:]) != comm_qubits:
        return False
    return tuple(catdisent.qubits[2:]) == tuple(
        active_gate_group.catdisent.qubits[2:]
    )


def _remote_gate_other_group_qubit(
    remote_gate: CleanedQuantumGate,
    control_qubit: CircuitQubit,
) -> CircuitQubit | None:
    """Return the non-control operand when a remote gate shares the control."""
    if len(remote_gate.qubits) < 2:
        return None
    if remote_gate.qubits[0] == control_qubit:
        return remote_gate.qubits[1]
    if remote_gate.name == "rcz" and remote_gate.qubits[1] == control_qubit:
        return remote_gate.qubits[0]
    return None


def _split_groupable_remote_gate(
    remote_gate_statements: list[CleanedStatement],
    added_local_swaps: int,
    placement_swaps: list[PlacementSwap],
) -> tuple[CleanedQuantumGate, CleanedQuantumGate, CleanedQuantumGate] | None:
    """Return ``catent``, remote gate, and ``catdisent`` when groupable."""
    if (
        added_local_swaps != 0
        or placement_swaps
        or len(remote_gate_statements) != 3
    ):
        return None
    catent, remote_gate, catdisent = remote_gate_statements
    if not (
        isinstance(catent, CleanedQuantumGate)
        and isinstance(remote_gate, CleanedQuantumGate)
        and isinstance(catdisent, CleanedQuantumGate)
    ):
        return None
    if (
        catent.name != "catent"
        or remote_gate.name not in _REMOTE_GATE_NAMES
        or remote_gate.name == "rswap"
        or catdisent.name != "catdisent"
    ):
        return None
    return catent, remote_gate, catdisent


def _close_active_gate_group(
    distributed_statements: list[CleanedStatement],
    active_gate_group: _ActiveGateGroup,
) -> None:
    """Append the deferred ``catdisent`` for an active group, if any."""
    if active_gate_group.enabled and active_gate_group.catdisent is not None:
        distributed_statements.append(active_gate_group.catdisent)
    active_gate_group.catdisent = None


def _strip_remote_ebit_operands(
    statements: list[CleanedStatement],
) -> list[CleanedStatement]:
    """Remove concrete e-bit operands from EPR-backed gate statements.

    Deferred e-bit assignment keeps only data operands on emitted remote,
    catent, and catdisent operations. Scheduler-facing communication options
    are stored separately on ``DistributedCircuit.ebit_candidates_by_op_id``.
    """
    stripped_statements: list[CleanedStatement] = []
    for statement in statements:
        if not (
            isinstance(statement, CleanedQuantumGate)
            and statement.name in _DEFERRED_EBIT_GATE_NAMES
        ):
            stripped_statements.append(statement)
            continue

        data_qubits = statement.qubits[:2]
        node = cast(ast.QuantumGate, clone_statement_node(statement.node))
        node.qubits = [_to_ast_qubit_ref(qubit) for qubit in data_qubits]
        stripped_statements.append(
            CleanedQuantumGate(
                statement_type=statement.statement_type,
                node=node,
                is_op=statement.is_op,
                name=statement.name,
                qubits=data_qubits,
            )
        )

    return stripped_statements


def count_remote_gates(
    ops: list[Op],
) -> int:
    """Count operations marked as remote.

    Args:
        ops: Operations in the distributed circuit.

    Returns:
        The number of operations tagged as remote gates.
    """
    return sum(1 for op in ops if op.name in _REMOTE_GATE_NAMES - {"rswap"})
