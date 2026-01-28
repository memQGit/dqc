# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Utility functions for circuit extraction."""


def identify_state_tele_ops(
    schedule: list[list[set[int]]],
) -> list[dict[int, tuple[int, int]]]:
    """Identify state teleportation operations in the schedule.

    Args:
        schedule: A list of time steps, each containing a list of sets of logical
            qubits assigned to each QPU.

    Returns:
        A list of dictionaries mapping logical qubits to a tuple of (source QPU,
        destination QPU) for each state teleportation operation in each time step,
        starting with the 2nd time step.
    """
    tele_ops_per_timestep: list[dict[int, tuple[int, int]]] = []
    for t in range(1, len(schedule)):
        tele_ops: dict[int, tuple[int, int]] = {}
        prev_assignment = schedule[t - 1]
        curr_assignment = schedule[t]
        for qpu_idx_src, src_qubits in enumerate(prev_assignment):
            for qpu_idx_dst, dst_qubits in enumerate(curr_assignment):
                if qpu_idx_src == qpu_idx_dst:
                    continue
                teleported_qubits = src_qubits.intersection(dst_qubits)
                for logical_qubit in teleported_qubits:
                    tele_ops[logical_qubit] = (qpu_idx_src, qpu_idx_dst)
        tele_ops_per_timestep.append(tele_ops)
    return tele_ops_per_timestep
