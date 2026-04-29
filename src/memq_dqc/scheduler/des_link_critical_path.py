"""Discrete-event scheduler prioritizing critical-path-heavy requests."""

from __future__ import annotations

from memq_dqc.circuit import DistributedCircuit
from memq_dqc.scheduler.des_link_fifo import DESLinkFIFOScheduler
from memq_dqc.scheduler.des_link_scheduler import _PendingLinkRequest
from memq_dqc.scheduler.schedule import (
    DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE,
    DEFAULT_SCHEDULER_MODALITY,
    OperationSchedule,
    SchedulerEntanglementProfile,
    SchedulerHardwareProfile,
    SchedulerModality,
)


class DESLinkCriticalPathScheduler(DESLinkFIFOScheduler):
    """DES scheduler that prefers requests with larger remaining path cost."""

    def _pending_request_sort_key(
        self,
        pending_request: _PendingLinkRequest,
        *,
        link_key: tuple[str, str],
        time: float,
    ) -> tuple[float, ...]:
        """Return a critical-path-first arbitration key."""
        del link_key
        del time
        return (
            -self._remaining_path_cost(pending_request.op_id),
            float(pending_request.enqueue_sequence),
        )


def des_link_critical_path_schedule(
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
    """Build a critical-path-first DES schedule.

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
        critical-path-first link arbitration.
    """
    scheduler = DESLinkCriticalPathScheduler(
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
            "DES critical-path scheduler did not produce a schedule."
        )
    return scheduler.schedule
