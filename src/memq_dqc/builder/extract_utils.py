# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Helpers for extracting distributed circuits from partition results."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memq_dqc.utils.common import qubit_partition_map, window_op_map

if TYPE_CHECKING:
    from memq_dqc.circuit import Circuit
    from memq_dqc.circuit.op import Op
    from memq_dqc.partition import Partitioner
    from memq_dqc.partition.partitioner import QPU


Pos = tuple[int, int]
PartitionAssignment = dict["QPU", set[int]]
GateGroupRange = tuple[int, int]
GatePacket = list[set[int]]

logger = logging.getLogger(__name__)

_DIAGONAL_GATES = frozenset(
    {
        "id",
        "p",
        "phase",
        "z",
        "s",
        "sdg",
        "t",
        "tdg",
        "rz",
        "u1",
    }
)
_ANTIDIAGONAL_GATES = frozenset({"x", "y"})
_COMMUTING_CONTROL_GATES = _DIAGONAL_GATES | _ANTIDIAGONAL_GATES
_REVERSIBLE_TARGET_TWO_QUBIT_GATES = frozenset({"cz"})


@dataclass(frozen=True, slots=True)
class SwapOp:
    """Recording the qubits’ physical positions when the swap is generated."""

    q0: int
    q1: int
    pos0: Pos
    pos1: Pos


def synthesize_state_teleportation_swaps(
    schedule: list[PartitionAssignment],
) -> list[list[SwapOp]]:
    """Synthesize swaps to realize the state teleportation schedule.

    Args:
        schedule: A list of time steps, each mapping QPUs to logical qubits.

    Returns:
        Swap operations per timestep that transform each assignment into the
        next. The returned list has length ``len(schedule) - 1``.

    Raises:
        ValueError: If the schedule changes QPU counts or partition sizes.
        RuntimeError: If swap synthesis fails to reach a target assignment.
    """
    swaps_per_timestep = [
        _synthesize_swaps_for_timestep(prev_assignment, curr_assignment)
        for prev_assignment, curr_assignment in zip(
            schedule,
            schedule[1:],
            strict=False,
        )
    ]

    # Rebase swap positions across timesteps so each swap references the
    # current physical positions resulting from previously emitted swaps.
    current_pos_by_qubit = _assignment_initial_positions(schedule[0])
    rebased_swaps_per_timestep: list[list[SwapOp]] = []
    for timestep_swaps in swaps_per_timestep:
        rebased_timestep_swaps: list[SwapOp] = []
        for swap in timestep_swaps:
            pos0 = current_pos_by_qubit[swap.q0]
            pos1 = current_pos_by_qubit[swap.q1]
            rebased_swap = SwapOp(
                q0=swap.q0,
                q1=swap.q1,
                pos0=pos0,
                pos1=pos1,
            )
            rebased_timestep_swaps.append(rebased_swap)
            current_pos_by_qubit[swap.q0], current_pos_by_qubit[swap.q1] = (
                pos1,
                pos0,
            )
        rebased_swaps_per_timestep.append(rebased_timestep_swaps)

    return rebased_swaps_per_timestep


def _assignment_to_sorted_lists(
    assignment: PartitionAssignment,
) -> tuple[list[int], list[list[int]]]:
    """Return sorted QPU IDs and sorted qubits assigned to each QPU."""
    items = sorted(assignment.items(), key=lambda item: item[0].id)
    qpu_ids = [qpu.id for qpu, _ in items]
    return qpu_ids, [sorted(qubits) for _, qubits in items]


def _assignment_initial_positions(
    assignment: PartitionAssignment,
) -> dict[int, Pos]:
    """Return initial physical positions for one partition assignment."""
    qpu_ids, qubits_by_qpu = _assignment_to_sorted_lists(assignment)
    pos_by_qubit: dict[int, Pos] = {}
    for qpu_id, qubits in zip(qpu_ids, qubits_by_qpu, strict=True):
        for slot_idx, qubit in enumerate(qubits):
            pos_by_qubit[qubit] = (qpu_id, slot_idx)
    return pos_by_qubit


def _assignment_partition_map(
    qpu_ids: list[int],
    qubits_by_qpu: list[list[int]],
) -> dict[int, int]:
    """Return the assigned QPU for each logical qubit."""
    qpu_by_qubit: dict[int, int] = {}
    for qpu_id, qubits in zip(qpu_ids, qubits_by_qpu, strict=True):
        for qubit in qubits:
            qpu_by_qubit[qubit] = qpu_id
    return qpu_by_qubit


def _validate_assignment_shapes(
    prev_qpu_ids: list[int],
    prev_lists: list[list[int]],
    curr_qpu_ids: list[int],
    curr_lists: list[list[int]],
) -> None:
    """Validate that adjacent schedule windows can be connected by swaps."""
    if prev_qpu_ids != curr_qpu_ids:
        raise ValueError("QPU identities changed between timesteps.")

    for prev_qpu_id, prev_qubits, curr_qubits in zip(
        prev_qpu_ids,
        prev_lists,
        curr_lists,
        strict=True,
    ):
        if len(prev_qubits) != len(curr_qubits):
            raise ValueError(
                "Partition size mismatch on QPU "
                f"{prev_qpu_id}: {len(prev_qubits)} -> "
                f"{len(curr_qubits)}"
            )


def _record_swap(
    swaps: list[SwapOp],
    pos_by_qubit: dict[int, Pos],
    q0: int,
    q1: int,
) -> None:
    """Append one swap and update the tracked physical positions."""
    pos0 = pos_by_qubit[q0]
    pos1 = pos_by_qubit[q1]
    swaps.append(SwapOp(q0=q0, q1=q1, pos0=pos0, pos1=pos1))
    pos_by_qubit[q0], pos_by_qubit[q1] = pos1, pos0


def _synthesize_swaps_for_timestep(
    prev_assignment: PartitionAssignment,
    curr_assignment: PartitionAssignment,
) -> list[SwapOp]:
    """Produce swaps that transform prev_assignment to curr_assignment."""
    if len(prev_assignment) != len(curr_assignment):
        raise ValueError("Number of QPUs changed between timesteps.")

    prev_qpu_ids, prev_lists = _assignment_to_sorted_lists(prev_assignment)
    curr_qpu_ids, curr_lists = _assignment_to_sorted_lists(curr_assignment)
    _validate_assignment_shapes(
        prev_qpu_ids,
        prev_lists,
        curr_qpu_ids,
        curr_lists,
    )

    current_qpu = _assignment_partition_map(prev_qpu_ids, prev_lists)
    target_qpu = _assignment_partition_map(curr_qpu_ids, curr_lists)

    moved_qubits = {
        qubit for qubit, qpu in current_qpu.items() if target_qpu[qubit] != qpu
    }
    if not moved_qubits:
        return []

    pos_by_qubit = _assignment_initial_positions(prev_assignment)
    swaps: list[SwapOp] = []
    # Iteratively swap until qubit is in correction position
    moved_remaining = set(moved_qubits)
    while moved_remaining:
        q0 = min(moved_remaining)
        q0_current_qpu, _ = pos_by_qubit[q0]
        q0_target_qpu = target_qpu[q0]
        if q0_current_qpu == q0_target_qpu:
            moved_remaining.remove(q0)
            continue

        # Identify all qubits on other QPU that need to be moved still
        candidates = [
            qubit
            for qubit in moved_remaining
            if pos_by_qubit[qubit][0] == q0_target_qpu
        ]
        if not candidates:
            raise RuntimeError(
                "Swap synthesis failed: no donor qubit found for "
                f"destination QPU {q0_target_qpu}."
            )
        q1 = min(candidates)
        _record_swap(swaps, pos_by_qubit, q0, q1)

        for qubit in (q0, q1):
            if pos_by_qubit[qubit][0] == target_qpu[qubit]:
                moved_remaining.discard(qubit)

    final_assignment: dict[int, set[int]] = {
        qpu_id: set() for qpu_id in prev_qpu_ids
    }
    for qubit, pos in pos_by_qubit.items():
        final_assignment[pos[0]].add(qubit)
    target_assignment = {
        qpu.id: set(qubits) for qpu, qubits in curr_assignment.items()
    }
    if final_assignment != target_assignment:
        raise RuntimeError("Swap synthesis failed to reach target assignment.")
    return swaps


def identify_remote_gates(
    circuit: Circuit,
    partition: Partitioner,
) -> list[tuple[Op, dict[str, int]]]:
    """Identify remote gates in the scheduled circuit.

    Args:
        circuit: The circuit representing the quantum circuit.
        partition: The Partitioner object containing the partitioning schedule.

    Returns:
        Augmented list of operations with two-qubit gates replaced with remote
        variants where applicable.
    """
    ops = circuit.mono.ops
    windows = partition.windows
    schedule = partition.schedule
    if windows is None or schedule is None:
        raise ValueError(
            "partition.run() must be called before identifying remote gates."
        )
    window_op_mapping = window_op_map(windows)

    # Iterate through 2-qubit gates; mark remote if they use distinct QPUs
    remote_gates: list[tuple[Op, dict[str, int]]] = []
    for op in ops:
        num_qubits = len(op.qubits)
        if num_qubits == 1:
            continue
        if num_qubits > 2:
            raise ValueError(
                "Only single- and two-qubit gates are supported currently."
            )
        if num_qubits != 2:
            raise ValueError("Expected a two-qubit operation.")
        q1, q2 = op.qubits
        op_window_idx = window_op_mapping[op.op_id]
        qubit_map = qubit_partition_map(schedule[op_window_idx])
        q1_qpu = qubit_map[q1.index]
        q2_qpu = qubit_map[q2.index]
        if q1_qpu == q2_qpu:
            continue
        remote_gates.append((op, {"q1_qpu": q1_qpu, "q2_qpu": q2_qpu}))

    return remote_gates


def window_final_op_id_map(windows: list[list[Op]]) -> dict[int, int]:
    """Create a map from window index to final operation ID.

    This is useful to determine when we have reached the end of a given window,
    in order to insert swaps to prepare the correct partition for the next
    window. NOTE: does not include the final window, since no swaps need to be
    inserted after it.

    Args:
        windows: List of operation windows.

    Returns:
        A dictionary mapping window indices to the final operation ID.
    """
    return {
        window_idx: window[-1].op_id
        for window_idx, window in enumerate(windows[:-1])
    }


def circuit_qubit_physical_map(
    schedule: list[PartitionAssignment],
    swaps: list[list[SwapOp]],
) -> list[dict[int, tuple[int, int]]]:
    """Create circuit-to-physical qubit maps for each time interval.

    A physical qubit is characterized by an (int, int) tuple, where first
    element represents QPU index, second element represents qubit index for
    that given QPU. A circuit qubit is the qubit index as defined in the
    original input circuit.

    """
    if not schedule:
        raise ValueError("schedule must contain at least one window.")

    current_map = _assignment_initial_positions(schedule[0])
    interval_maps: list[dict[int, tuple[int, int]]] = [current_map.copy()]

    # Each interval snapshot reflects the layout after the swaps for that
    # boundary have been applied.
    for interval in swaps:
        for swap in interval:
            q0 = swap.q0
            q1 = swap.q1
            pos0 = current_map[q0]
            pos1 = current_map[q1]
            current_map[q0] = pos1
            current_map[q1] = pos0
        interval_maps.append(current_map.copy())

    return interval_maps


def identify_gate_groups(
    circuit: Circuit,
    partition: Partitioner,
    *,
    verbose: bool = False,
    max_size: int | None = None,
) -> tuple[list[Op], set[GateGroupRange], list[GatePacket]]:
    """Identify gate groups within a partitioned circuit.

    The grouping logic follows the experimental OpenQASM statement workflow:
    groups start from a two-qubit gate, continue across compatible gates with
    a shared control, and may commute one future two-qubit gate into the group
    when the intervening operations are disjoint. The function only inspects
    the completed partitioner's windows and does not mutate or install the
    groups anywhere.

    Args:
        circuit: Circuit whose operations are partitioned.
        partition: Completed partitioner containing windows and schedule.
        verbose: Whether to emit grouping summary logs.
        max_size: Optional maximum number of two-qubit gates per group.

    Returns:
        Reordered operations, grouped index ranges in the reordered
        operations, and gate packets represented by qubit-index sets.

    Raises:
        ValueError: If partitioning has not produced windows and schedule, or
            if unsupported operations are present.
    """
    windows = partition.windows
    schedule = partition.schedule
    if windows is None or schedule is None:
        raise ValueError(
            "partition.run() must be called before identifying gate groups."
        )
    if len(windows) != len(schedule):
        raise ValueError("partition windows and schedule must have same size.")

    known_op_ids = {op.op_id for op in circuit.mono.ops}
    reordered_ops: list[Op] = []
    group_indices: set[GateGroupRange] = set()
    for window in windows:
        unknown_op_ids = [
            op.op_id for op in window if op.op_id not in known_op_ids
        ]
        if unknown_op_ids:
            raise ValueError(
                "Partition windows contain operations outside the circuit: "
                f"{unknown_op_ids}."
            )

        window_reordered_ops, window_group_indices = (
            _identify_existing_gate_groups(window, verbose, max_size)
        )
        offset = len(reordered_ops)
        group_indices.update(
            (offset + start, offset + end)
            for start, end in window_group_indices
        )
        reordered_ops.extend(window_reordered_ops)

    gate_packets = _build_gate_packets(reordered_ops, group_indices)
    # get the total number of grouped gates and the average group size for logging
    if verbose:
        total_grouped_gates = sum(end - start for start, end in group_indices)
        average_group_size = (
            total_grouped_gates / len(group_indices) if group_indices else 0
        )
        logger.info(
            "Identified %d gate groups with average size %.3f.",
            len(group_indices),
            average_group_size,
        )
    return reordered_ops, group_indices, gate_packets


def _identify_existing_gate_groups(
    gate_ops: list[Op],
    verbose: bool = False,
    max_size: int | None = None,
) -> tuple[list[Op], set[GateGroupRange]]:
    """Identify existing gate groups within one operation window."""
    reordered_ops: list[Op] = []
    group_indices: set[GateGroupRange] = set()
    num_two_qubit_gates = 0
    op_index = 0
    while op_index < len(gate_ops):
        op = gate_ops[op_index]
        _validate_supported_gate_group_op(op)
        if len(op.qubits) == 2:
            num_two_qubit_gates += 1
            control, target = _get_control_and_target(op)
            group_ops, ignored_ops = _search_for_group_gate(
                gate_ops,
                op_index + 1,
                control,
                target,
                verbose,
                max_size,
            )
            group_start = len(reordered_ops)
            group_end = group_start + len(group_ops)
            group_indices.add((group_start, group_end))
            reordered_ops.extend(group_ops)
            reordered_ops.extend(ignored_ops)

            op_index += len(group_ops) + len(ignored_ops)
        else:
            reordered_ops.append(op)
            op_index += 1

    if verbose:
        grouped_gate_count = sum(end - start for start, end in group_indices)
        average_group_size = (
            grouped_gate_count / len(group_indices) if group_indices else 0
        )
        logger.info("Gate grouping reordered length: %d.", len(reordered_ops))
        logger.info("Original window length: %d.", len(gate_ops))
        logger.info("Total 2-qubit gates: %d.", num_two_qubit_gates)
        logger.info("Average group size: %.3f.", average_group_size)
        logger.info("Identified %d gate groups.", len(group_indices))
        logger.info("Total grouped gate operations: %d.", grouped_gate_count)

    return reordered_ops, group_indices


def _search_for_group_gate(
    gate_ops: list[Op],
    start_index: int,
    control: int,
    target: int,
    verbose: bool = False,
    max_size: int | None = None,
) -> tuple[list[Op], list[Op]]:
    """Search forward from one two-qubit gate to build a gate group."""
    group_ops = [gate_ops[start_index - 1]]
    ignored_ops: list[Op] = []
    targets = {target}
    group_two_qubit_count = 1
    pending_one_qubit_gates: list[Op] = []

    for relative_index, op in enumerate(gate_ops[start_index:]):
        _validate_supported_gate_group_op(op)
        if len(op.qubits) == 2:
            op_control, op_target = _get_control_and_target(op)

            if _shares_group_control(op, control, op_control, op_target):
                if max_size is not None and group_two_qubit_count >= max_size:
                    ignored_ops.extend(pending_one_qubit_gates)
                    return group_ops, ignored_ops

                group_ops.extend(pending_one_qubit_gates)
                pending_one_qubit_gates = []
                group_ops.append(op)
                group_two_qubit_count += 1
                targets.add(op_target)
            else:
                return _search_for_commuting_group_gate(
                    gate_ops,
                    start_index,
                    relative_index,
                    op,
                    control,
                    group_ops,
                    ignored_ops,
                    pending_one_qubit_gates,
                    group_two_qubit_count,
                    verbose,
                    max_size,
                )

        elif len(op.qubits) == 1:
            qubit = op.qubits[0].index
            if qubit == control:
                if op.name in _COMMUTING_CONTROL_GATES:
                    pending_one_qubit_gates.append(op)
                else:
                    ignored_ops.extend(pending_one_qubit_gates)
                    return group_ops, ignored_ops
            elif qubit in targets:
                pending_one_qubit_gates.append(op)
            else:
                ignored_ops.append(op)

    ignored_ops.extend(pending_one_qubit_gates)
    return group_ops, ignored_ops


def _search_for_commuting_group_gate(
    gate_ops: list[Op],
    start_index: int,
    relative_index: int,
    terminating_op: Op,
    control: int,
    group_ops: list[Op],
    ignored_ops: list[Op],
    pending_one_qubit_gates: list[Op],
    group_two_qubit_count: int,
    verbose: bool,
    max_size: int | None,
) -> tuple[list[Op], list[Op]]:
    """Try to commute one future two-qubit gate into the active group."""
    single_qubit_gates_in_between: list[Op] = []
    search_start = start_index + relative_index + 1
    for next_op in gate_ops[search_start:]:
        _validate_supported_gate_group_op(next_op)
        if len(next_op.qubits) == 1:
            single_qubit_gates_in_between.append(next_op)
            continue
        if len(next_op.qubits) != 2:
            continue

        next_control, next_target = _get_control_and_target(next_op)
        disjoint = _disjoint_ops(terminating_op, next_op)
        shares_group_control = _shares_group_control(
            next_op,
            control,
            next_control,
            next_target,
        )
        blocking_one_qubit_gates = [
            gate
            for gate in single_qubit_gates_in_between
            if not _disjoint_ops(next_op, gate)
        ]
        size_available = max_size is None or group_two_qubit_count < max_size

        if (
            disjoint
            and shares_group_control
            and not blocking_one_qubit_gates
            and size_available
        ):
            group_ops.extend(pending_one_qubit_gates)
            group_ops.append(next_op)
            ignored_ops.extend(
                [terminating_op, *single_qubit_gates_in_between]
            )
        else:
            ignored_ops.extend(pending_one_qubit_gates)
        return group_ops, ignored_ops

    ignored_ops.extend(pending_one_qubit_gates)
    return group_ops, ignored_ops


def _get_control_and_target(op: Op) -> tuple[int, int]:
    """Return the first and second qubits of a two-qubit operation."""
    if len(op.qubits) != 2:
        raise ValueError("Expected a two-qubit operation.")
    return op.qubits[0].index, op.qubits[1].index


def _get_op_qubits(op: Op) -> set[int]:
    """Return the logical qubit indices touched by an operation."""
    return {qubit.index for qubit in op.qubits}


def _disjoint_ops(op_a: Op, op_b: Op) -> bool:
    """Return whether two operations act on disjoint logical qubits."""
    return _get_op_qubits(op_a).isdisjoint(_get_op_qubits(op_b))


def _format_op(op: Op) -> str:
    """Format an operation for debug logging."""
    qubits = " ".join(f"q[{qubit.index}]" for qubit in op.qubits)
    return f"{op.name} {qubits}"


def _shares_group_control(
    op: Op,
    group_control: int,
    op_control: int,
    op_target: int,
) -> bool:
    """Return whether an operation continues a shared-control group."""
    return op_control == group_control or (
        op_target == group_control
        and op.name in _REVERSIBLE_TARGET_TWO_QUBIT_GATES
    )


def _build_gate_packets(
    gate_ops: list[Op],
    group_indices: set[GateGroupRange],
) -> list[GatePacket]:
    """Build qubit packets for each identified gate group."""
    return [
        [_get_op_qubits(op) for op in gate_ops[start:end]]
        for start, end in sorted(group_indices)
    ]


def _validate_supported_gate_group_op(op: Op) -> None:
    """Validate that an operation can participate in gate grouping."""
    if len(op.qubits) not in {1, 2}:
        raise ValueError(
            "Only single- and two-qubit operations are supported for "
            f"gate grouping. Received {op.name!r} on {len(op.qubits)} qubits."
        )
