# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Circuit builder utilities."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from .extract_utils import (
    circuit_qubit_physical_map,
    identify_remote_gates,
    synthesize_state_teleportation_swaps,
    window_final_op_id_map,
)
from .formatting import rename_comm_qubits

if TYPE_CHECKING:
    import openqasm3.ast as ast

    from memq_dqc.partition import Partitioner


def extract_distributed_circuit(
    partitioner: Partitioner,
    *,
    verbosity: Literal["quiet", "info", "debug"] = "quiet",
) -> ast.Program:
    """Extract a distributed OpenQASM program from a completed partitioner.

    Args:
        partitioner: Partitioner with a completed partitioning run.
        verbosity: Logging verbosity for this workflow call.

    Returns:
        Distributed OpenQASM program with communication operations inserted.
    """
    from .circuit_extractor import (
        extract_distributed_circuit as _extract_distributed_circuit,
    )

    return _extract_distributed_circuit(
        partitioner,
        verbosity=verbosity,
    )


__all__ = [
    "extract_distributed_circuit",
    "identify_remote_gates",
    "circuit_qubit_physical_map",
    "synthesize_state_teleportation_swaps",
    "window_final_op_id_map",
    "rename_comm_qubits",
]
