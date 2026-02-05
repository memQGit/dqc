# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Utility functions used commonly throughout different parts of the library."""

from __future__ import annotations

from typing import TYPE_CHECKING


if TYPE_CHECKING:
    from memq_dqc.circuit import CircuitDAG, Op


def qubit_partition_map(partition: list[set[int]]) -> dict[int, int]:
    """Create a mapping from qubit index to partition index.

    Args:
        partition: Partitioning of qubits by group.

    Returns:
        The partition index for each qubit index.
    """
    qubit_to_partition: dict[int, int] = {}
    for part_idx, qubit_set in enumerate(partition):
        for qubit in qubit_set:
            qubit_to_partition[qubit] = part_idx
    return qubit_to_partition


def window_op_map(dag: CircuitDAG, windows: list[list[Op]]) -> dict[int, int]:
    """Create a mapping from operation ID to its window index.

    Args:
        dag: Circuit DAG providing operations.
        windows: List of operation windows.

    Returns:
        A dictionary mapping operation IDs to their corresponding window index.
    """
    op_to_window: dict[int, int] = {}
    for window_idx, window in enumerate(windows):
        for op in window:
            op_to_window[op.op_id] = window_idx
    return op_to_window
