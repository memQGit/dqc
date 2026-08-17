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

"""Scheduler interfaces and shared schedule data structures."""

from __future__ import annotations

import logging
import math
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from functools import cache
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypeVar

from memq_dqc._logging import StepTimer, workflow_logging
from memq_dqc.circuit import DistributedCircuit, Op
from memq_dqc.network import PhysicalQubit
from memq_dqc.preprocessing.qasm.types import CircuitQubit
from memq_dqc.settings import load_settings

if TYPE_CHECKING:
    from os import PathLike

    from matplotlib.axes import Axes

    from memq_dqc.compiler import Compiler
    from memq_dqc.partition import Partitioner

logger = logging.getLogger(__name__)

_MEASUREMENT_TIME = 3.0
SchedulerModality: TypeAlias = Literal[
    "trapped_ion.ba",
    "trapped_ion.sr",
    "neutral_atom",
]
SchedulerEntanglementProfile: TypeAlias = Literal[
    "ion.time_bin",
    "ion.polarization",
    "neutral_atom.polarization",
]
DEFAULT_SCHEDULER_MODALITY: SchedulerModality = "trapped_ion.ba"
DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE: SchedulerEntanglementProfile = (
    "ion.time_bin"
)
# TODO: temporarily effectively-infinite so generated pairs never expire while
# scheduling. Real hardware is ~50 us, but that is far below the time needed to
# generate a pair, which makes any two-pair operation (e.g. a remote swap)
# impossible to assemble. See the epr_lifetime note in settings.toml for what
# restoring a realistic value requires.
_DEFAULT_EPR_LIFETIME = 1e9
_CATENT_OP_NAME = "catent"
_HARDWARE_OVERRIDE_FIELDS: tuple[str, ...] = (
    "one_qubit_gate_time",
    "two_qubit_gate_time",
    "measurement_time",
    "entanglement_rate",
    "epr_lifetime",
)


def _validate_hardware_override(name: str, value: float | None) -> None:
    """Validate one optional hardware-parameter override.

    Args:
        name: Field name, used in the error message.
        value: The override value, or ``None`` when unset.

    Raises:
        ValueError: If the value is not a finite positive number.
    """
    if value is None:
        return
    if not math.isfinite(value) or value <= 0:
        raise ValueError(
            f"SchedulerHardwareProfile.{name} must be a positive number, "
            f"got {value!r}."
        )


@dataclass(frozen=True, slots=True)
class SchedulerHardwareProfile:
    """User-facing hardware selection for scheduler timing.

    The two selector fields pick a named profile from ``settings.toml``. The
    remaining fields are optional per-instance overrides of the individual
    hardware parameters that profile resolves to: ``None`` keeps the profile's
    value, and any other value replaces it. Derived timings (cat-entangling,
    cat-disentangling, state teleport, entanglement duration, DES success
    probability) always recompute from the effective values, so they cannot
    contradict the parameters they are built from.

    Example:
        A Sr+ trapped-ion device with a faster two-qubit gate and a longer EPR
        lifetime than the packaged profile assumes:

        ```python
        profile = SchedulerHardwareProfile.sr_trapped_ion(
            two_qubit_gate_time=120.0,
            epr_lifetime=80.0,
        )
        ```

    Attributes:
        modality: Modality profile used for local gate times.
        entanglement_profile: Entanglement-generation profile used for
            entanglement timing.
        one_qubit_gate_time: Optional override for the local single-qubit gate
            duration.
        two_qubit_gate_time: Optional override for the local two-qubit gate
            duration.
        measurement_time: Optional override for the measurement duration.
        entanglement_rate: Optional override for the entanglement-generation
            rate.
        epr_lifetime: Optional override for the maximum EPR-pair lifetime.
    """

    modality: SchedulerModality = DEFAULT_SCHEDULER_MODALITY
    entanglement_profile: SchedulerEntanglementProfile = (
        DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
    )
    one_qubit_gate_time: float | None = None
    two_qubit_gate_time: float | None = None
    measurement_time: float | None = None
    entanglement_rate: float | None = None
    epr_lifetime: float | None = None

    def __post_init__(self) -> None:
        """Validate that every supplied override is a positive number.

        Raises:
            ValueError: If any override is not a finite positive number.
        """
        for name in _HARDWARE_OVERRIDE_FIELDS:
            _validate_hardware_override(name, getattr(self, name))

    @property
    def overrides(self) -> dict[str, float]:
        """Return the supplied overrides, keyed by field name."""
        return {
            name: value
            for name in _HARDWARE_OVERRIDE_FIELDS
            if (value := getattr(self, name)) is not None
        }

    @classmethod
    def ba_trapped_ion(
        cls,
        *,
        entanglement_profile: SchedulerEntanglementProfile = (
            DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
        ),
        one_qubit_gate_time: float | None = None,
        two_qubit_gate_time: float | None = None,
        measurement_time: float | None = None,
        entanglement_rate: float | None = None,
        epr_lifetime: float | None = None,
    ) -> SchedulerHardwareProfile:
        """Return the Ba+ trapped-ion hardware selection.

        Args:
            entanglement_profile: Entanglement-generation profile to pair with
                the modality.
            one_qubit_gate_time: Optional single-qubit gate duration override.
            two_qubit_gate_time: Optional two-qubit gate duration override.
            measurement_time: Optional measurement duration override.
            entanglement_rate: Optional entanglement-generation rate override.
            epr_lifetime: Optional EPR-pair lifetime override.

        Returns:
            The hardware profile.
        """
        return cls(
            modality="trapped_ion.ba",
            entanglement_profile=entanglement_profile,
            one_qubit_gate_time=one_qubit_gate_time,
            two_qubit_gate_time=two_qubit_gate_time,
            measurement_time=measurement_time,
            entanglement_rate=entanglement_rate,
            epr_lifetime=epr_lifetime,
        )

    @classmethod
    def sr_trapped_ion(
        cls,
        *,
        entanglement_profile: SchedulerEntanglementProfile = (
            DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
        ),
        one_qubit_gate_time: float | None = None,
        two_qubit_gate_time: float | None = None,
        measurement_time: float | None = None,
        entanglement_rate: float | None = None,
        epr_lifetime: float | None = None,
    ) -> SchedulerHardwareProfile:
        """Return the Sr+ trapped-ion hardware selection.

        Args:
            entanglement_profile: Entanglement-generation profile to pair with
                the modality.
            one_qubit_gate_time: Optional single-qubit gate duration override.
            two_qubit_gate_time: Optional two-qubit gate duration override.
            measurement_time: Optional measurement duration override.
            entanglement_rate: Optional entanglement-generation rate override.
            epr_lifetime: Optional EPR-pair lifetime override.

        Returns:
            The hardware profile.
        """
        return cls(
            modality="trapped_ion.sr",
            entanglement_profile=entanglement_profile,
            one_qubit_gate_time=one_qubit_gate_time,
            two_qubit_gate_time=two_qubit_gate_time,
            measurement_time=measurement_time,
            entanglement_rate=entanglement_rate,
            epr_lifetime=epr_lifetime,
        )

    @classmethod
    def neutral_atom(
        cls,
        *,
        entanglement_profile: SchedulerEntanglementProfile = (
            DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
        ),
        one_qubit_gate_time: float | None = None,
        two_qubit_gate_time: float | None = None,
        measurement_time: float | None = None,
        entanglement_rate: float | None = None,
        epr_lifetime: float | None = None,
    ) -> SchedulerHardwareProfile:
        """Return the neutral-atom hardware selection.

        Args:
            entanglement_profile: Entanglement-generation profile to pair with
                the modality.
            one_qubit_gate_time: Optional single-qubit gate duration override.
            two_qubit_gate_time: Optional two-qubit gate duration override.
            measurement_time: Optional measurement duration override.
            entanglement_rate: Optional entanglement-generation rate override.
            epr_lifetime: Optional EPR-pair lifetime override.

        Returns:
            The hardware profile.
        """
        return cls(
            modality="neutral_atom",
            entanglement_profile=entanglement_profile,
            one_qubit_gate_time=one_qubit_gate_time,
            two_qubit_gate_time=two_qubit_gate_time,
            measurement_time=measurement_time,
            entanglement_rate=entanglement_rate,
            epr_lifetime=epr_lifetime,
        )


def _default_entanglement_duration() -> float:
    """Return the default entanglement duration for manual event creation."""
    return _load_scheduler_timing_model(
        SchedulerHardwareProfile()
    ).entanglement_time


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
    """Schedule entanglement generation between two available qubits.

    Attributes:
        qubits: Communication qubits used for entanglement generation.
        start_time: Time at which generation begins.
        duration: Total time the EPR pair occupies the link.
        was_used: Whether the generated pair was consumed before expiration.
    """

    qubits: tuple[str, str]
    start_time: float
    duration: float = field(default_factory=_default_entanglement_duration)
    was_used: bool = True

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


@dataclass(frozen=True, slots=True)
class SchedulerTimingModel:
    """Timing values used to schedule local and derived remote operations.

    Attributes:
        hardware_profile: Selected scheduler hardware profile.
        local_one_qubit_gate_time: Duration of a local single-qubit gate.
        local_two_qubit_gate_time: Duration of a local two-qubit gate.
        entanglement_generation_rate: Entanglement-generation rate.
        des_entanglement_time_step: Duration of one DES entanglement-attempt
            cycle.
        epr_lifetime: Maximum lifetime of a generated EPR pair.
        measurement_time: Duration of a measurement operation.
    """

    hardware_profile: SchedulerHardwareProfile
    local_one_qubit_gate_time: float
    local_two_qubit_gate_time: float
    entanglement_generation_rate: float
    des_entanglement_time_step: float
    epr_lifetime: float = _DEFAULT_EPR_LIFETIME
    measurement_time: float = _MEASUREMENT_TIME

    @property
    def state_teleport_time(self) -> float:
        """Return the derived state-teleport duration.

        One teleportation costs a two-qubit gate, three single-qubit gates,
        and two measurements.
        """
        return (
            self.local_two_qubit_gate_time
            + (3 * self.local_one_qubit_gate_time)
            + (2 * self.measurement_time)
        )

    @property
    def entanglement_time(self) -> float:
        """Return the expected FIFO entanglement duration in microseconds."""
        return 1.0 / self.entanglement_generation_rate

    @property
    def des_t_cycle(self) -> float:
        """Return the DES entanglement-attempt cycle length."""
        return self.des_entanglement_time_step

    @property
    def des_success_probability(self) -> float:
        """Return the DES per-cycle entanglement success probability."""
        return -math.expm1(
            -self.entanglement_generation_rate
            * self.des_entanglement_time_step
        )

    @property
    def catent_time(self) -> float:
        """Return the derived cat-entangling operation duration."""
        return (
            self.local_two_qubit_gate_time
            + self.local_one_qubit_gate_time
            + self.measurement_time
        )

    @property
    def catdisent_time(self) -> float:
        """Return the derived cat-disentangling operation duration."""
        return (2 * self.local_one_qubit_gate_time) + self.measurement_time


class BaseScheduler(ABC):
    """Base class for distributed scheduling algorithm implementations."""

    def __init__(
        self,
        distributed_circuit: DistributedCircuit,
        *,
        profile: SchedulerHardwareProfile | None = None,
        modality: SchedulerModality = DEFAULT_SCHEDULER_MODALITY,
        entanglement_profile: SchedulerEntanglementProfile = (
            DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
        ),
        multiplex_entangle: bool = True,
    ) -> None:
        """Initialize the scheduler with a distributed circuit.

        Args:
            distributed_circuit: Distributed circuit DAG to schedule.
            profile: Optional convenience object selecting both modality and
                entanglement profile, and carrying any custom hardware
                parameter overrides. When provided, ``modality`` and
                ``entanglement_profile`` must be left at their defaults; pass a
                profile rather than the scalar selectors to override individual
                hardware parameters.
            modality: Hardware timing profile used for local 1Q/2Q gate
                durations. Defaults to ``"trapped_ion.ba"`` (Ba+ trapped ion).
            entanglement_profile: Entanglement-generation profile used for
                entanglement timing. Defaults to ``"ion.time_bin"``.
            multiplex_entangle: True if we can perform entanglement generation
                for comm qubits on same chip simultaneously
        """
        hardware_profile = _resolve_scheduler_hardware_profile(
            profile=profile,
            modality=modality,
            entanglement_profile=entanglement_profile,
        )
        self.distributed_circuit = distributed_circuit
        self.hardware_profile = hardware_profile
        self.modality = hardware_profile.modality
        self.entanglement_profile = hardware_profile.entanglement_profile
        self.multiplex_entangle = multiplex_entangle
        self.timing_model = _load_scheduler_timing_model(hardware_profile)
        self.schedule: OperationSchedule | None = None

    @abstractmethod
    def run(self) -> None:
        """Run the scheduling algorithm and update ``schedule``."""
        raise NotImplementedError


class Scheduler:
    """Orchestrate a scheduling algorithm implementation."""

    def __init__(
        self,
        source: Compiler | Partitioner | DistributedCircuit,
        *,
        algo: str | type[_Algorithm] | _Algorithm = "fifo",
        profile: SchedulerHardwareProfile | None = None,
        modality: SchedulerModality = DEFAULT_SCHEDULER_MODALITY,
        entanglement_profile: SchedulerEntanglementProfile = (
            DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
        ),
        # TODO: make explicit / check
        multiplex_entangle: bool = True,
        algo_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the scheduler and select the algorithm.

        Args:
            source: What to schedule. A ``Compiler`` or ``Partitioner`` (its
                distributed circuit is used) or a ``DistributedCircuit``
                directly.
            algo: Algorithm name, class, or preconfigured instance.
            profile: Optional convenience object selecting both modality and
                entanglement profile. When provided, ``modality`` and
                ``entanglement_profile`` must be left at their defaults.
            modality: Hardware timing profile used for local 1Q/2Q gate
                durations. Defaults to ``"trapped_ion.ba"`` (Ba+ trapped ion).
            entanglement_profile: Entanglement-generation profile used for
                entanglement timing. Defaults to ``"ion.time_bin"``.
            multiplex_entangle: Whether entanglement generation may overlap
                across independent communication resources.
            algo_kwargs: Keyword arguments forwarded to the algorithm.
        """
        self._algorithm = self._resolve_algorithm(
            _resolve_distributed_circuit(source),
            algo,
            profile,
            modality,
            entanglement_profile,
            multiplex_entangle,
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
                "Scheduling completed in %.3fs: operations=%d "
                "makespan=%.3f failed_entanglement_operations=%d.",
                timer.elapsed_seconds(),
                len(schedule.operations),
                schedule.makespan,
                _count_failed_entanglement_operations(schedule),
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

    def plot_gantt(
        self,
        *,
        ax: Axes | None = None,
        title: str | None = None,
        display: Literal["pretty", "legacy"] = "pretty",
        explicit_ops: bool = False,
        show: bool = False,
        save_path: str | PathLike[str] | None = None,
        dpi: int = 150,
    ) -> Axes:
        """Render this scheduler's result as a Gantt chart.

        Args:
            ax: Existing axes to draw into. A new figure and axes are created
                when omitted.
            title: Optional chart title (ignored in ``"pretty"`` display).
            display: Which rendering to produce. ``"pretty"`` is the
                publication-ready variant; ``"legacy"`` is the on-screen
                diagnostic chart.
            explicit_ops: Whether to render one row per scheduled event instead
                of one row per physical qubit.
            show: Whether to call ``matplotlib.pyplot.show`` after rendering.
            save_path: Optional file path. When given, the rendered figure is
                saved there.
            dpi: Resolution used when saving to ``save_path``.

        Returns:
            The Matplotlib axes containing the rendered schedule.

        Raises:
            ValueError: If the scheduler has not produced a schedule yet.
        """
        if self.schedule is None:
            raise ValueError(
                "No schedule available; call run() before plot_gantt()."
            )
        from memq_dqc.scheduler.schedule_visualizer import plot_schedule_gantt

        axes = plot_schedule_gantt(
            self.schedule,
            ax=ax,
            title=title,
            show=show,
            explicit_ops=explicit_ops,
            display=display,
        )
        if save_path is not None:
            axes.figure.savefig(str(save_path), dpi=dpi, bbox_inches="tight")
        return axes

    def to_json(
        self,
        path: str | PathLike[str] | None = None,
        *,
        indent: int | None = 2,
    ) -> str:
        """Serialize this scheduler's result to a JSON document.

        Opt-in export; scheduling never serializes automatically. See
        [memq_dqc.scheduler.serialize.schedule_to_json][memq_dqc.scheduler.serialize.schedule_to_json] for the document
        layout.

        Args:
            path: Optional destination file. When given, the JSON document is
                written there in addition to being returned.
            indent: Indentation forwarded to the underlying serializer. Pass
                ``None`` for the most compact single-line output.

        Returns:
            The JSON document as a string.

        Raises:
            ValueError: If the scheduler has not produced a schedule yet.
        """
        if self.schedule is None:
            raise ValueError(
                "No schedule available; call run() before to_json()."
            )
        from memq_dqc.scheduler.serialize import schedule_to_json

        return schedule_to_json(self.schedule, path, indent=indent)

    def _resolve_algorithm(
        self,
        distributed_circuit: DistributedCircuit,
        algo: str | type[_Algorithm] | _Algorithm,
        profile: SchedulerHardwareProfile | None,
        modality: SchedulerModality,
        entanglement_profile: SchedulerEntanglementProfile,
        multiplex_entangle: bool,
        algo_kwargs: dict[str, Any] | None,
    ) -> BaseScheduler:
        if isinstance(algo, BaseScheduler):
            if (
                algo_kwargs
                or profile is not None
                or modality != DEFAULT_SCHEDULER_MODALITY
                or entanglement_profile
                != DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
                or multiplex_entangle is not True
            ):
                raise ValueError(
                    "algo_kwargs, profile, modality, entanglement_profile, "
                    "and multiplex_entangle "
                    "cannot be provided with an "
                    "algorithm instance."
                )
            return algo

        algo_kwargs = algo_kwargs or {}
        if isinstance(algo, str):
            algo_class = _get_algorithm_class(algo)
        else:
            algo_class = algo

        return algo_class(
            distributed_circuit,
            profile=profile,
            modality=modality,
            entanglement_profile=entanglement_profile,
            multiplex_entangle=multiplex_entangle,
            **algo_kwargs,
        )


def _resolve_distributed_circuit(
    source: Compiler | Partitioner | DistributedCircuit,
) -> DistributedCircuit:
    """Return the distributed circuit to schedule from a supported source.

    Accepts a ``Compiler`` or ``Partitioner`` (whose ``distributed_circuit``
    property is read, extracting it on first access) or a ``DistributedCircuit``
    directly.

    Raises:
        TypeError: If ``source`` is not a supported type.
    """
    if isinstance(source, DistributedCircuit):
        return source
    distributed = getattr(source, "distributed_circuit", None)
    if isinstance(distributed, DistributedCircuit):
        return distributed
    raise TypeError(
        "Scheduler requires a Compiler, Partitioner, or DistributedCircuit; "
        f"got {type(source).__name__}."
    )


def _get_algorithm_class(name: str) -> type[BaseScheduler]:
    """Resolve a scheduler class from a registry name."""
    if name == "fifo":
        from memq_dqc.scheduler.fifo import FIFOScheduler

        return FIFOScheduler
    if name == "des_link_fifo":
        from memq_dqc.scheduler.des_link_fifo import DESLinkFIFOScheduler

        return DESLinkFIFOScheduler
    if name == "des_link_shortest_duration":
        from memq_dqc.scheduler.des_link_shortest_duration import (
            DESLinkShortestDurationScheduler,
        )

        return DESLinkShortestDurationScheduler
    if name == "des_link_critical_path":
        from memq_dqc.scheduler.des_link_critical_path import (
            DESLinkCriticalPathScheduler,
        )

        return DESLinkCriticalPathScheduler
    raise ValueError(f"Unknown scheduling algorithm: {name}")


def _count_failed_entanglement_operations(
    schedule: OperationSchedule,
) -> int:
    """Return the number of scheduled entanglement events that were unused."""
    return sum(
        1
        for event in schedule.operations
        if isinstance(event, EntanglementGeneration) and not event.was_used
    )


def _physical_qubit_label(
    qubit: CircuitQubit | PhysicalQubit,
) -> str:
    """Return a stable physical-qubit label for schedule output."""
    if isinstance(qubit, PhysicalQubit):
        prefix = "c" if qubit.is_communication else "q"
        return f"{prefix}{qubit.qpu_id}[{qubit.qubit_id}]"
    return f"{qubit.register_name}[{qubit.index}]"


def _resolve_scheduler_hardware_profile(
    *,
    profile: SchedulerHardwareProfile | None,
    modality: SchedulerModality,
    entanglement_profile: SchedulerEntanglementProfile,
) -> SchedulerHardwareProfile:
    """Resolve one effective hardware profile from user inputs."""
    if profile is not None:
        if (
            modality != DEFAULT_SCHEDULER_MODALITY
            or entanglement_profile != DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
        ):
            raise ValueError(
                "profile cannot be combined with modality or "
                "entanglement_profile overrides."
            )
        return profile
    return SchedulerHardwareProfile(
        modality=modality,
        entanglement_profile=entanglement_profile,
    )


@cache
def _load_scheduler_timing_model(
    hardware_profile: SchedulerHardwareProfile,
) -> SchedulerTimingModel:
    """Load scheduler timing values for one supported hardware profile.

    Each value comes from the profile's named ``settings.toml`` entry unless
    the profile carries an explicit override for it.
    """
    settings = load_settings()
    modality_profile = settings.modality_profile(hardware_profile.modality)
    entanglement_profile = settings.entanglement_profile(
        hardware_profile.entanglement_profile
    )
    overrides = hardware_profile.overrides
    return SchedulerTimingModel(
        hardware_profile=hardware_profile,
        local_one_qubit_gate_time=overrides.get(
            "one_qubit_gate_time", modality_profile.one_qubit_gate_time
        ),
        local_two_qubit_gate_time=overrides.get(
            "two_qubit_gate_time", modality_profile.two_qubit_gate_time
        ),
        entanglement_generation_rate=overrides.get(
            "entanglement_rate", entanglement_profile.entanglement_rate
        ),
        des_entanglement_time_step=(
            settings.des_simulation.entanglement_time_step
        ),
        epr_lifetime=overrides.get(
            "epr_lifetime", entanglement_profile.epr_lifetime
        ),
        measurement_time=overrides.get("measurement_time", _MEASUREMENT_TIME),
    )


def _operation_duration(op: Op, timing_model: SchedulerTimingModel) -> float:
    """Return the execution time for an operation."""
    if op.name == "catent":
        return timing_model.catent_time
    if op.name == "catdisent":
        return timing_model.catdisent_time
    if op.name == "rswap":
        # A remote swap exchanges two states, i.e. two state teleportations.
        return 2 * timing_model.state_teleport_time
    if op.name == "measure":
        return timing_model.measurement_time
    if len(op.qubits) == 1:
        return timing_model.local_one_qubit_gate_time
    return timing_model.local_two_qubit_gate_time


def _is_catent_operation(op: Op) -> bool:
    """Return whether an operation prepares a cat-entangled remote gate."""
    return op.name == _CATENT_OP_NAME


def _catent_ebit_labels(op: Op) -> tuple[tuple[str, str], ...]:
    """Return the EPR qubit pairs consumed by a cat-entangling operation."""
    if not _is_catent_operation(op):
        return ()
    comm_qubits = op.qubits[2:]
    if len(comm_qubits) == 0 or len(comm_qubits) % 2 != 0:
        raise ValueError(
            "catent operations must contain data operands followed by one or "
            f"more communication-qubit pairs. Received {op.qubits!r}."
        )
    return tuple(
        (
            _physical_qubit_label(comm_qubits[index]),
            _physical_qubit_label(comm_qubits[index + 1]),
        )
        for index in range(0, len(comm_qubits), 2)
    )


def _remote_ops_with_catent_predecessor(
    distributed_circuit: DistributedCircuit,
) -> set[int]:
    """Return remote op IDs whose EPR setup is owned by a catent op."""
    graph = distributed_circuit.dag.graph
    remote_op_ids: set[int] = set()
    for op_id in graph.nodes:
        op = graph.nodes[op_id]["op"]
        if not op.is_remote:
            continue
        if any(
            _is_catent_operation(graph.nodes[predecessor]["op"])
            for predecessor in graph.predecessors(op_id)
        ):
            remote_op_ids.add(op_id)
    return remote_op_ids


def _remote_ebit_assignment_candidates(
    distributed_circuit: DistributedCircuit,
    op: Op,
) -> tuple[tuple[tuple[PhysicalQubit, PhysicalQubit], ...], ...]:
    """Return scheduler-selectable e-bit assignments for an EPR-backed op."""
    if not (op.is_remote or _is_catent_operation(op)):
        return ()

    candidates_by_op_id = distributed_circuit.ebit_candidates_by_op_id
    if candidates_by_op_id is not None:
        candidates = candidates_by_op_id.get(op.op_id)
        if candidates is None:
            raise ValueError(
                "Deferred e-bit assignment is missing candidates for remote "
                f"operation {op.op_id}."
            )
        if not candidates:
            raise ValueError(
                "Deferred e-bit assignment has no viable candidates for "
                f"remote operation {op.op_id}."
            )
        return candidates

    ebit_pairs = op.ebit_pairs
    if ebit_pairs is None:
        raise ValueError(
            "Remote operation is missing required EPR pair metadata."
        )
    return (ebit_pairs,)


def _remote_operation_qubit_labels(
    op: Op,
    assignment: tuple[tuple[PhysicalQubit, PhysicalQubit], ...],
) -> tuple[str, ...]:
    """Return scheduled qubit labels for a remote op and e-bit assignment."""
    data_qubits = tuple(
        _physical_qubit_label(qubit) for qubit in op.qubits[:2]
    )
    ebit_qubits = tuple(
        _physical_qubit_label(qubit) for pair in assignment for qubit in pair
    )
    return (*data_qubits, *ebit_qubits)


def _ebit_assignment_labels(
    assignment: tuple[tuple[PhysicalQubit, PhysicalQubit], ...],
) -> tuple[tuple[str, str], ...]:
    """Return physical-qubit label pairs for one e-bit assignment."""
    return tuple(
        (
            _physical_qubit_label(pair[0]),
            _physical_qubit_label(pair[1]),
        )
        for pair in assignment
    )


def _build_qubit_timelines(
    operations: list[ScheduleEvent],
    qubit_order: tuple[str, ...],
) -> tuple[ScheduledQubitTimeline, ...]:
    """Build per-qubit timeline views from scheduled operations."""
    ordered_qubits = list(qubit_order)
    operations_by_qubit = {qubit: [] for qubit in qubit_order}
    for scheduled_op in operations:
        for qubit in scheduled_op.qubits:
            if qubit not in operations_by_qubit:
                operations_by_qubit[qubit] = []
                ordered_qubits.append(qubit)
            operations_by_qubit[qubit].append(scheduled_op)

    return tuple(
        ScheduledQubitTimeline(
            qubit=qubit,
            operations=tuple(operations_by_qubit[qubit]),
        )
        for qubit in ordered_qubits
    )
