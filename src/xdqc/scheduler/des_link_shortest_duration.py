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

"""Discrete-event scheduler prioritizing shorter remote operations."""

from __future__ import annotations

from xdqc.circuit import DistributedCircuit
from xdqc.scheduler.des_link_fifo import DESLinkFIFOScheduler
from xdqc.scheduler.des_link_scheduler import _PendingLinkRequest
from xdqc.scheduler.schedule import (
    DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE,
    DEFAULT_SCHEDULER_MODALITY,
    OperationSchedule,
    SchedulerEntanglementProfile,
    SchedulerHardwareProfile,
    SchedulerModality,
)


class DESLinkShortestDurationScheduler(DESLinkFIFOScheduler):
    """DES scheduler that prefers the shortest blocked remote request."""

    def _pending_request_sort_key(
        self,
        pending_request: _PendingLinkRequest,
        *,
        link_key: tuple[str, str],
        time: float,
    ) -> tuple[float, ...]:
        """Return a shortest-duration-first arbitration key."""
        del link_key
        del time
        return (
            self._remote_duration(pending_request.op_id),
            float(pending_request.enqueue_sequence),
        )


def des_link_shortest_duration_schedule(
    distributed_circuit: DistributedCircuit,
    *,
    profile: SchedulerHardwareProfile | None = None,
    modality: SchedulerModality = DEFAULT_SCHEDULER_MODALITY,
    entanglement_profile: SchedulerEntanglementProfile = (
        DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
    ),
    multiplex_entangle: bool = True,
    seed: int | None = None,
) -> OperationSchedule:
    """Build a shortest-duration-first DES schedule.

    Args:
        distributed_circuit: Distributed circuit to schedule.
        profile: Optional convenience object selecting both modality and
            entanglement profile. When provided, ``modality`` and
            ``entanglement_profile`` must be left at their defaults.
        modality: Hardware timing profile used for local 1Q/2Q gate
            durations. Defaults to ``"trapped_ion.ba"``.
        entanglement_profile: Entanglement-generation profile used for
            entanglement timing. Defaults to ``"ion.time_bin"``.
        multiplex_entangle: Whether entanglement generation for multi-pair
            remote requests may overlap. The current DES link model still
            enforces one active entanglement process per link.
        seed: Optional random seed for deterministic simulations.

    Returns:
        An operation-level schedule with stochastic entanglement timing and
        shortest-duration link arbitration.
    """
    scheduler = DESLinkShortestDurationScheduler(
        distributed_circuit,
        profile=profile,
        modality=modality,
        entanglement_profile=entanglement_profile,
        multiplex_entangle=multiplex_entangle,
        seed=seed,
    )
    scheduler.run()
    if scheduler.schedule is None:
        raise RuntimeError(
            "DES shortest-duration scheduler did not produce a schedule."
        )
    return scheduler.schedule
