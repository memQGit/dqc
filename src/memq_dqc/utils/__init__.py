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
    count_total_qubits,
    count_two_qubit_pairs,
    create_initial_subcircuit_graph,
    distribute,
    extract_qubit_index,
    extract_two_qubit_gates,
    get_windows,
    load_qasm_program,
    movement_cost,
    qubit_partition_set_to_map,
)

# Partition utilities
from memq_dqc.utils.partition_utils import (
    generate_equal_partitions,
    get_edge_weight,
    partition_cost,
    verify_partition_sizes,
)

__all__ = [
    # Circuit utilities
    "count_total_qubits",
    "extract_qubit_index",
    "extract_two_qubit_gates",
    "load_qasm_program",
    "create_initial_subcircuit_graph",
    "movement_cost",
    "count_two_qubit_pairs",
    "distribute",
    "qubit_partition_set_to_map",
    "get_windows",
    # Partition utilities
    "partition_cost",
    "get_edge_weight",
    "verify_partition_sizes",
    "generate_equal_partitions",
]
