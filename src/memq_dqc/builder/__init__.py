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

if TYPE_CHECKING:
    import openqasm3.ast as ast

    from memq_dqc.partition import Partitioner
    from memq_dqc.scheduler.schedule import SchedulerHardwareProfile


def extract_distributed_circuit(
    partitioner: Partitioner,
    *,
    ebit_assignment: bool = True,
    group_gates: bool = True,
    max_group_size: int | None = None,
    group_size_profile: SchedulerHardwareProfile | None = None,
    verbosity: Literal["quiet", "info", "debug"] = "quiet",
) -> ast.Program:
    """Extract a distributed OpenQASM program from a completed partitioner.

    Args:
        partitioner: Partitioner with a completed partitioning run.
        ebit_assignment: Whether the compiler assigns concrete e-bit pairs
            into the scheduler DAG. If false, schedulers choose from viable
            e-bit pair candidates.
        group_gates: Whether compatible remote gate groups should share one
            cat-entanglement region in the emitted program.
        max_group_size: Optional maximum number of two-qubit gates per emitted
            gate group.
        group_size_profile: Scheduler hardware profile whose timing bounds
            each gate group's duration to the EPR lifetime. Defaults to
            ``neutral_atom.polarization`` when omitted.
        verbosity: Logging verbosity for this workflow call.

    Returns:
        Distributed OpenQASM program with communication operations inserted.
    """
    from .circuit_extractor import (
        extract_distributed_circuit as _extract_distributed_circuit,
    )

    return _extract_distributed_circuit(
        partitioner,
        ebit_assignment=ebit_assignment,
        group_gates=group_gates,
        max_group_size=max_group_size,
        group_size_profile=group_size_profile,
        verbosity=verbosity,
    )


__all__ = [
    "extract_distributed_circuit",
    "identify_remote_gates",
    "circuit_qubit_physical_map",
    "synthesize_state_teleportation_swaps",
    "window_final_op_id_map",
]
