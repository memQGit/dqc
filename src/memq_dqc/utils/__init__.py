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
    create_subcircuit_graphs,
    extract_qubit_index,
    extract_two_qubit_gates,
    load_qasm_program,
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
    "create_subcircuit_graphs",
    # Partition utilities
    "partition_cost",
    "get_edge_weight",
    "verify_partition_sizes",
    "generate_equal_partitions",
]
