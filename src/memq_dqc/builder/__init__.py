# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Circuit builder utilities."""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .circuit_extractor import extract_distributed_circuit
    from .extract_utils import (
        identify_remote_gates,
        logical_physical_map,
        synthesize_state_teleportation_swaps,
        window_final_op_id_map,
    )
    from .formatting import rename_comm_qubits  # TODO: remove

__all__ = [
    "extract_distributed_circuit",
    "identify_remote_gates",
    "logical_physical_map",
    "synthesize_state_teleportation_swaps",
    "window_final_op_id_map",
    "rename_comm_qubits",  # TODO: remove
]


def __getattr__(name: str) -> object:  # pragma: no cover
    if name == "extract_distributed_circuit":
        from .circuit_extractor import extract_distributed_circuit

        return extract_distributed_circuit
    if name in {
        "identify_remote_gates",
        "logical_physical_map",
        "synthesize_state_teleportation_swaps",
        "window_final_op_id_map",
    }:
        from . import extract_utils

        return getattr(extract_utils, name)
    raise AttributeError(name)
