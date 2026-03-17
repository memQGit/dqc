"""EPR-minimization distributed scheduler skeleton."""

from __future__ import annotations

from memq_dqc.scheduler.schedule import BaseScheduler


class EPRMinimizationScheduler(BaseScheduler):
    """Skeleton scheduler for future EPR-minimization strategies."""

    def run(self) -> None:
        """Run the EPR-minimization scheduling algorithm."""
        raise NotImplementedError(
            "EPR-minimization scheduling is not yet implemented."
        )
