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
"""Utility functions used commonly throughout different parts of the library."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from memq_dqc.circuit.op import Op
    from memq_dqc.partition.partitioner import QPU


def qubit_partition_map(
    partition: list[set[int]] | dict[QPU, set[int]],
) -> dict[int, int]:
    """Create a mapping from qubit index to partition index.

    Args:
        partition: Partitioning of qubits by group.

    Returns:
        The partition index for each qubit index.
    """
    qubit_to_partition: dict[int, int] = {}
    if isinstance(partition, dict):
        for qpu, qubit_set in partition.items():
            for qubit in qubit_set:
                qubit_to_partition[qubit] = qpu.id
        return qubit_to_partition
    for part_idx, qubit_set in enumerate(partition):
        for qubit in qubit_set:
            qubit_to_partition[qubit] = part_idx
    return qubit_to_partition


def window_op_map(windows: list[list[Op]]) -> dict[int, int]:
    """Create a mapping from operation ID to its window index.

    Args:
        windows: List of operation windows.

    Returns:
        A dictionary mapping operation IDs to their corresponding window index.
    """
    op_to_window: dict[int, int] = {}
    for window_idx, window in enumerate(windows):
        for op in window:
            op_to_window[op.op_id] = window_idx
    return op_to_window
