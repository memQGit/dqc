"""Placeholder scheduler for future EPR-minimization work."""

from __future__ import annotations

from memq_dqc.scheduler.schedule import BaseScheduler


class EPRMinimizationScheduler(BaseScheduler):
    """Placeholder scheduler reserved for EPR-minimization heuristics."""

    def run(self) -> None:
        """Raise until the EPR-minimization scheduler is implemented."""
        raise NotImplementedError(
            "EPR-minimization scheduling is not yet implemented."
        )
