# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Utility functions for circuit extraction."""



def identify_state_tele_ops(schedule: list[list[set[int]]]) -> list[dict[int, tuple[int, int]]]:
    """Identify state teleportation operations in the schedule.

    Args:
        schedule: A list of time steps, each containing a list of sets of logical
            qubits assigned to each QPU.

    Returns:
        A list of dictionaries mapping logical qubits to a tuple of (source QPU,
        destination QPU) for each state teleportation operation in each time step,
        starting with the 2nd time step.