"""Discrete-event scheduler with FIFO arbitration on each link."""

from __future__ import annotations

from memq_dqc.circuit import DistributedCircuit
from memq_dqc.scheduler.des_link_scheduler import BaseDESLinkScheduler
from memq_dqc.scheduler.schedule import (
    DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE,
    DEFAULT_SCHEDULER_MODALITY,
    OperationSchedule,
    SchedulerEntanglementProfile,
    SchedulerHardwareProfile,
    SchedulerModality,
)


class DESLinkFIFOScheduler(BaseDESLinkScheduler):
    """DES scheduler that serves contended links in FIFO order."""


def des_link_fifo_schedule(
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
    """Build a FIFO-arbitrated DES schedule for a distributed circuit DAG.

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
        FIFO link arbitration.
    """
    scheduler = DESLinkFIFOScheduler(
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
            "DES link-FIFO scheduler did not produce a schedule."
        )
    return scheduler.schedule
