# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Utility functions for memq-dqc.

This module provides utility functions for working with quantum circuits,
graph partitioning, and other common operations throughout the library.
"""

# Circuit utilities
from memq_dqc.utils.circuit_utils import (
    count_two_qubit_pairs,
    create_initial_subcircuit_graph,
    distribute,
    get_windows,
    movement_cost,
)

from memq_dqc.utils.common import qubit_partition_map, window_op_map

__all__ = [
    "count_two_qubit_pairs",
    "create_initial_subcircuit_graph",
    "distribute",
    "get_windows",
    "movement_cost",
    "qubit_partition_map",
    "window_op_map",
]
