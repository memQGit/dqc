# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Utility functions for circuit extraction."""

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


# TODO: this whole file, particular function below, needs review + cleanup
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
    swaps_per_timestep: list[list[SwapOp]] = []
    for step_idx in range(1, len(schedule)):
        swaps_per_timestep.append(
            _synthesize_swaps_for_timestep(
                schedule[step_idx - 1],
                schedule[step_idx],
            )
        )

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


def _synthesize_swaps_for_timestep(
    prev_assignment: PartitionAssignment,
    curr_assignment: PartitionAssignment,
) -> list[SwapOp]:
    """Produce swaps that transform prev_assignment to curr_assignment.

    Only cross-QPU swaps are emitted.
    """
    # TODO (important): must have a list of possible swaps, and ensure partition doesnt move between unreachable qpus'
    # TODO: clarify / clean this
    if len(prev_assignment) != len(curr_assignment):
        raise ValueError("Number of QPUs changed between timesteps.")

    prev_qpu_ids, prev_lists = _assignment_to_sorted_lists(prev_assignment)
    curr_qpu_ids, curr_lists = _assignment_to_sorted_lists(curr_assignment)
    if prev_qpu_ids != curr_qpu_ids:
        raise ValueError("QPU identities changed between timesteps.")

    for qpu_idx in range(len(prev_lists)):
        if len(prev_lists[qpu_idx]) != len(curr_lists[qpu_idx]):
            raise ValueError(
                "Partition size mismatch on QPU "
                f"{qpu_idx}: {len(prev_lists[qpu_idx])} -> "
                f"{len(curr_lists[qpu_idx])}"
            )

    current_qpu: dict[int, int] = {}
    target_qpu: dict[int, int] = {}
    for qpu_id, qubits in zip(prev_qpu_ids, prev_lists, strict=True):
        for qubit in qubits:
            current_qpu[qubit] = qpu_id
    for qpu_id, qubits in zip(curr_qpu_ids, curr_lists, strict=True):
        for qubit in qubits:
            target_qpu[qubit] = qpu_id

    moved_qubits = {
        qubit for qubit, qpu in current_qpu.items() if target_qpu[qubit] != qpu
    }
    if not moved_qubits:
        return []

    pos_by_qubit: dict[int, Pos] = {}
    for qpu_id, qubits in zip(prev_qpu_ids, prev_lists, strict=True):
        for slot_idx, qubit in enumerate(qubits):
            pos = (qpu_id, slot_idx)
            pos_by_qubit[qubit] = pos

    swaps: list[SwapOp] = []

    # TODO: no nested functions
    def emit_swap(q0: int, q1: int) -> None:
        pos0 = pos_by_qubit[q0]
        pos1 = pos_by_qubit[q1]
        swaps.append(SwapOp(q0=q0, q1=q1, pos0=pos0, pos1=pos1))
        pos_by_qubit[q0], pos_by_qubit[q1] = pos1, pos0

    moved_remaining = set(moved_qubits)
    while moved_remaining:
        q0 = min(moved_remaining)
        q0_current_qpu, _ = pos_by_qubit[q0]
        q0_target_qpu = target_qpu[q0]
        if q0_current_qpu == q0_target_qpu:
            moved_remaining.remove(q0)
            continue

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
        emit_swap(q0, q1)

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

    remote_gates: list[tuple[Op, dict[str, int]]] = []
    for op in ops:
        if len(op.qubits) == 1:
            continue
        if len(op.qubits) > 2:
            raise ValueError(
                "Only single- and two-qubit gates are supported currently."
            )
        if len(op.qubits) != 2:
            raise ValueError("Expected a two-qubit operation.")
        q1, q2 = op.qubits
        op_window_idx = window_op_mapping[op.op_id]
        qubit_map = qubit_partition_map(schedule[op_window_idx])
        q1_qpu = qubit_map[q1.index]
        q2_qpu = qubit_map[q2.index]
        if q1_qpu == q2_qpu:
            continue
        # TODO: theres probably a cleaner, more efficient way to do this
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
    window_final_op_id: dict[int, int] = {}
    for window_idx, window in enumerate(windows[:-1]):
        final_op = window[-1]
        window_final_op_id[window_idx] = final_op.op_id
    return window_final_op_id


# TODO: determine if this should be placed somewhere else - perhaps in DAG
def circuit_qubit_physical_map(
    # TODO: this is not clean
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

    initial_partition = schedule[0]
    current_map: dict[int, tuple[int, int]] = {}

    # Sort intitial partition by QPU ID, iterate through the qubits
    for qpu, qubit_set in sorted(
        initial_partition.items(), key=lambda item: item[0].id
    ):
        # Qubit set is list of circuit qubits assigned to that QPU
        for pos_idx, circuit_qubit in enumerate(sorted(qubit_set)):
            # Map the circuit qubit to a physical position
            current_map[circuit_qubit] = (qpu.id, pos_idx)

    interval_maps: list[dict[int, tuple[int, int]]] = [current_map.copy()]

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
