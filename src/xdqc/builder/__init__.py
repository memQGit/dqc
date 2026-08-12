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

    from xdqc.partition import Partitioner
    from xdqc.scheduler.schedule import SchedulerHardwareProfile


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
            each gate group's duration to the EPR lifetime. When omitted the
            EPR-lifetime cap is disabled.
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
