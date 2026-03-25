"""Scheduler interfaces and shared schedule data structures."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any, Literal, TypeAlias, TypeVar

from memq_dqc._logging import StepTimer, workflow_logging
from memq_dqc.circuit import DistributedCircuit, Op
from memq_dqc.network import PhysicalQubit
from memq_dqc.preprocessing.qasm.types import CircuitQubit

logger = logging.getLogger(__name__)


# TODO: must solidify this
_LOCAL_1Q_GATE_TIME = 1.0
_LOCAL_2Q_GATE_TIME = 2.0
_MEASUREMENT_TIME = 3.0
_ENTANGLEMENT_TIME = 10.0
_STATE_TELEPORT_TIME = (
    _LOCAL_2Q_GATE_TIME + (2 * _LOCAL_1Q_GATE_TIME) + _MEASUREMENT_TIME
)
_GATE_TELEPORT_TIME = (
    _LOCAL_2Q_GATE_TIME + _MEASUREMENT_TIME + _LOCAL_1Q_GATE_TIME
)

# TODO: General -> determine which type of r-swap we want to use
# determine if we want to have buffer qubits if we use dual state teleport


@dataclass(frozen=True, slots=True)
class ScheduledOperation:
    """One scheduled operation in physical-qubit coordinates.

    Attributes:
        op_id: Operation identifier from the distributed DAG.
        statement_id: Statement identifier from the distributed program.
        name: Gate or instruction name.
        qubits: Physical qubit labels touched by the operation.
        start_time: Earliest time the operation can begin.
        duration: Operation duration in abstract scheduler time units.
        is_remote: Whether the operation is a remote distributed operation.
    """

    op_id: int
    statement_id: int
    name: str
    qubits: tuple[str, ...]
    start_time: float
    duration: float
    is_remote: bool

    @property
    def end_time(self) -> float:
        """Return the end time of the scheduled operation."""
        return self.start_time + self.duration


@dataclass(frozen=True, slots=True)
class EntanglementGeneration:
    """Schedule entanglement generation between two available qubits."""

    qubits: tuple[str, str]
    start_time: float
    duration: float = _ENTANGLEMENT_TIME

    @property
    def name(self) -> str:
        """Return the schedule label for entanglement generation."""
        return "epr"

    @property
    def is_remote(self) -> bool:
        """Return whether entanglement generation is a remote event."""
        return True

    @property
    def end_time(self) -> float:
        """Return the end time of the entanglement generation."""
        return self.start_time + self.duration


ScheduleEvent: TypeAlias = ScheduledOperation | EntanglementGeneration


@dataclass(frozen=True, slots=True)
class ScheduledQubitTimeline:
    """Ordered operations scheduled on a single physical qubit.

    Attributes:
        qubit: Physical qubit label.
        operations: Operations that execute on this qubit in time order.
    """

    qubit: str
    operations: tuple[ScheduleEvent, ...]


@dataclass(frozen=True, slots=True)
class OperationSchedule:
    """Operation-level schedule with per-qubit execution timelines.

    Attributes:
        operations: Scheduled operations in dispatch order.
        timelines: Per-qubit views derived from ``operations``.
        makespan: Total execution time across all physical qubits.
    """

    operations: tuple[ScheduleEvent, ...]
    timelines: tuple[ScheduledQubitTimeline, ...]
    makespan: float

    @property
    def qubits(self) -> tuple[str, ...]:
        """Return the ordered physical qubits present in the schedule."""
        return tuple(timeline.qubit for timeline in self.timelines)


_Algorithm = TypeVar("_Algorithm", bound="BaseScheduler")


class BaseScheduler(ABC):
    """Base class for distributed scheduling algorithm implementations."""

    def __init__(
        self,
        distributed_circuit: DistributedCircuit,
        *,
        multiplex_entangle: bool = True,
    ) -> None:
        """Initialize the scheduler with a distributed circuit.

        Args:
            distributed_circuit: Distributed circuit DAG to schedule.
            multiplex_entangle: True if we can perform entanglement generation
                for comm qubits on same chip simultaneously
        """
        self.distributed_circuit = distributed_circuit
        self.multiplex_entangle = multiplex_entangle
        self.schedule: OperationSchedule | None = None

    @abstractmethod
    def run(self) -> None:
        """Run the scheduling algorithm and update ``schedule``."""
        raise NotImplementedError


class Scheduler:
    """Orchestrate a scheduling algorithm implementation."""

    def __init__(
        self,
        distributed_circuit: DistributedCircuit,
        *,
        algo: str | type[_Algorithm] | _Algorithm = "fifo",
        algo_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the scheduler and select the algorithm.

        Args:
            distributed_circuit: Distributed circuit DAG to schedule.
            algo: Algorithm name, class, or preconfigured instance.
            algo_kwargs: Keyword arguments forwarded to the algorithm.
        """
        self._algorithm = self._resolve_algorithm(
            distributed_circuit,
            algo,
            algo_kwargs,
        )

    def run(
        self,
        *,
        verbosity: Literal["quiet", "info", "debug"] = "quiet",
    ) -> None:
        """Run the configured scheduling algorithm.

        Args:
            verbosity: Logging verbosity for this workflow call.
        """
        with workflow_logging(verbosity):
            timer = StepTimer()
            logger.info(
                "Starting scheduling with %s.",
                type(self._algorithm).__name__,
            )
            self._algorithm.run()
            schedule = self._algorithm.schedule
            if schedule is None:
                logger.warning(
                    "Scheduling finished without an operation schedule "
                    "after %.3fs.",
                    timer.elapsed_seconds(),
                )
                return

            logger.info(
                "Scheduling completed in %.3fs: operations=%d makespan=%.3f.",
                timer.elapsed_seconds(),
                len(schedule.operations),
                schedule.makespan,
            )
            logger.debug(
                "Scheduled qubit timelines: %s",
                schedule.qubits,
            )

    @property
    def distributed_circuit(self) -> DistributedCircuit:
        """Return the distributed circuit used by the scheduler."""
        return self._algorithm.distributed_circuit

    @property
    def multiplex_entangle(self) -> bool:
        """Return the entanglement multiplexing option."""
        return self._algorithm.multiplex_entangle

    @property
    def schedule(self) -> OperationSchedule | None:
        """Return the latest operation schedule, if available."""
        return self._algorithm.schedule

    def _resolve_algorithm(
        self,
        distributed_circuit: DistributedCircuit,
        algo: str | type[_Algorithm] | _Algorithm,
        algo_kwargs: dict[str, Any] | None,
    ) -> BaseScheduler:
        if isinstance(algo, BaseScheduler):
            if algo_kwargs:
                raise ValueError(
                    "algo_kwargs cannot be provided with an algorithm instance."
                )
            return algo

        algo_kwargs = algo_kwargs or {}
        if isinstance(algo, str):
            algo_class = _get_algorithm_class(algo)
        else:
            algo_class = algo

        return algo_class(distributed_circuit, **algo_kwargs)


def _get_algorithm_class(name: str) -> type[BaseScheduler]:
    """Resolve a scheduler class from a registry name."""
    if name == "fifo":
        from memq_dqc.scheduler.fifo import FIFOScheduler

        return FIFOScheduler
    if name in {"des", "des_epr", "des_entanglement"}:
        from memq_dqc.scheduler.des_epr import DESEntanglementScheduler

        return DESEntanglementScheduler
    if name in {"epr_min", "epr_minimization", "EPRMinimization"}:
        from memq_dqc.scheduler.epr_min import EPRMinimizationScheduler

        return EPRMinimizationScheduler
    raise ValueError(f"Unknown scheduling algorithm: {name}")


def _physical_qubit_label(
    qubit: CircuitQubit | PhysicalQubit,
) -> str:
    """Return a stable physical-qubit label for schedule output."""
    if isinstance(qubit, PhysicalQubit):
        prefix = "c" if qubit.is_communication else "q"
        return f"{prefix}{qubit.qpu_id}[{qubit.qubit_id}]"
    return f"{qubit.register_name}[{qubit.index}]"


def _operation_duration(op: Op) -> float:
    """Return the execution time for an operation."""
    if op.is_remote:
        return (
            _STATE_TELEPORT_TIME if op.name == "rswap" else _GATE_TELEPORT_TIME
        )
    if op.name == "measure":
        return _MEASUREMENT_TIME
    if len(op.qubits) == 1:
        return _LOCAL_1Q_GATE_TIME
    return _LOCAL_2Q_GATE_TIME


def _build_qubit_timelines(
    operations: list[ScheduleEvent],
    qubit_order: tuple[str, ...],
) -> tuple[ScheduledQubitTimeline, ...]:
    """Build per-qubit timeline views from scheduled operations."""
    operations_by_qubit = {qubit: [] for qubit in qubit_order}
    for scheduled_op in operations:
        for qubit in scheduled_op.qubits:
            operations_by_qubit[qubit].append(scheduled_op)

    return tuple(
        ScheduledQubitTimeline(
            qubit=qubit,
            operations=tuple(operations_by_qubit[qubit]),
        )
        for qubit in qubit_order
    )
