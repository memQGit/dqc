# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Helpers for extracting distributed circuits from partition results."""

from __future__ import annotations

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
