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

"""Versioned scheduling-instance data model for external RL schedulers.

A [SchedulingInstance][memq_dqc.scheduler.instance.SchedulingInstance] is a single, self-contained artifact holding
every input an external discrete-event simulator or reinforcement-learning
scheduler needs to plan a distributed circuit: the distributed operation DAG,
a deterministic zero-EPR-wait nominal schedule, the physical resources and
links, and the entanglement (EPR) demands. It carries no OpenQASM AST objects
and no live compiler state, so it round-trips through JSON without loss.

This module defines only immutable, typed records plus
[validate_scheduling_instance][memq_dqc.scheduler.instance.validate_scheduling_instance]. Construction lives in
[memq_dqc.scheduler.nominal][memq_dqc.scheduler.nominal] and
[memq_dqc.compiler.compile_scheduling_instance][memq_dqc.compiler.compile_scheduling_instance]; JSON persistence lives in
[memq_dqc.scheduler.instance_serialize][memq_dqc.scheduler.instance_serialize]. The schema is versioned and kept
separate from the annotated-DAG and operation-schedule JSON schemas so existing
consumers of those documents are unaffected.

Attributes:
    SCHEDULING_INSTANCE_SCHEMA_VERSION: Current scheduling-instance schema
        version. Bumped only on incompatible layout changes.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, TypeAlias, TypeVar

SCHEDULING_INSTANCE_SCHEMA_VERSION = 1

JSONValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | list["JSONValue"]
    | dict[str, "JSONValue"]
)

ResourceType: TypeAlias = Literal["computation", "communication", "link"]


@dataclass(frozen=True, slots=True)
class SchedulingCompileOptions:
    """Options controlling how a scheduling instance is compiled.

    For the initial RL corpus the MVP requires ``ebit_assignment=True`` and
    ``group_gates=False``; the remaining fields are kept general for later
    experiments.

    Attributes:
        partitioner: Registry name of the partitioning algorithm.
        partitioner_kwargs: Extra keyword arguments forwarded to the
            partitioning algorithm, or ``None`` for defaults.
        partition_seed: Optional seed for partitioners with random components.
        ebit_assignment: Whether the compiler assigns concrete e-bit pairs
            (``True``) or exposes candidate assignments for deferred choice.
        group_gates: Whether compatible remote gates share a cat-entanglement
            region.
        max_group_size: Optional maximum number of two-qubit gates per group.
        hardware_profile: Scheduler hardware profile whose timings set the
            deterministic operation durations. ``None`` selects the default
            profile. Besides naming a modality and entanglement profile, a
            [SchedulerHardwareProfile][memq_dqc.scheduler.schedule.SchedulerHardwareProfile] can carry
            custom hardware parameters (gate, measurement, and entanglement
            timings) that override the selected profile's values.
    """

    partitioner: str = "interaction"
    partitioner_kwargs: Mapping[str, Any] | None = None
    partition_seed: int | None = None
    ebit_assignment: bool = True
    group_gates: bool = False
    max_group_size: int | None = None
    hardware_profile: Any | None = None


@dataclass(frozen=True, slots=True)
class SchedulingResource:
    """One physical resource: a qubit or an inter-QPU link.

    Attributes:
        resource_id: Stable identifier, e.g. ``"q0[3]"``, ``"c0[1]"``, or a
            link id such as ``"link:c0[0]<->c1[0]"``.
        resource_type: Whether the resource is a computation qubit, a
            communication qubit, or an inter-QPU link.
        qpu_id: Owning QPU id for qubit resources; ``None`` for links.
        local_index: Local slot index for qubit resources; ``None`` for links.
        endpoints: The two communication-qubit resource ids a link connects;
            ``None`` for qubit resources.
        parameters: Reserved mapping for external hardware annotations
            (coherence times, link fidelities); empty by default.
    """

    resource_id: str
    resource_type: ResourceType
    qpu_id: int | None = None
    local_index: int | None = None
    endpoints: tuple[str, str] | None = None
    parameters: Mapping[str, JSONValue] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class SchedulingOperation:
    """One distributed operation with its nominal timing.

    Attributes:
        op_id: Operation identifier from the distributed DAG.
        statement_id: Statement identifier from the distributed program.
        name: Gate or instruction name.
        op_type: Classification, e.g. ``"remote_gate"``, ``"epr_generation"``,
            ``"local_gate"`` (see the annotated-DAG classifier).
        is_remote: Whether the operation is a remote distributed operation.
        data_qubits: Ordered physical data-qubit resource ids.
        comm_qubits: Ordered physical communication-qubit resource ids.
        duration: Deterministic operation duration in ``time_unit`` units.
        group_id: Cat-entanglement group id, or ``None`` when ungrouped.
        nominal_start: Start time in the zero-EPR-wait nominal schedule.
        nominal_end: End time in the zero-EPR-wait nominal schedule.
    """

    op_id: int
    statement_id: int
    name: str
    op_type: str
    is_remote: bool
    data_qubits: tuple[str, ...]
    comm_qubits: tuple[str, ...]
    duration: float
    group_id: int | None
    nominal_start: float
    nominal_end: float


@dataclass(frozen=True, slots=True)
class SchedulingDependency:
    """One precedence edge in the distributed operation DAG.

    Attributes:
        source_op_id: Operation id the dependency originates from.
        target_op_id: Operation id that depends on the source.
        resources: Physical qubit resource ids that created the dependency.
        classification: Optional dependency label, e.g. ``"cross_qpu"`` or
            ``"local"``.
    """

    source_op_id: int
    target_op_id: int
    resources: tuple[str, ...]
    classification: str | None = None


@dataclass(frozen=True, slots=True)
class EPRLinkAssignment:
    """One concrete or candidate link assignment for an EPR demand.

    Attributes:
        link_ids: Link resource ids, one per required EPR pair.
        comm_qubit_ids: Communication-qubit resource ids occupied by this
            assignment.
    """

    link_ids: tuple[str, ...]
    comm_qubit_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class EPRDemand:
    """A request for newly generated entanglement by one operation.

    An EPR demand is a scheduling resource request, not an EPR-generation
    event. The external simulator creates as many generation attempts as its
    policy requires.

    Attributes:
        demand_id: Stable identifier for the demand.
        consumer_op_id: Operation that consumes the entanglement (a ``catent``,
            an ``rswap``, or an ungrouped remote gate).
        num_pairs: Number of EPR pairs the consumer requires.
        assigned: The fixed link assignment, or ``None`` when assignment is
            deferred to the scheduler.
        candidates: Candidate link assignments when assignment is deferred;
            empty when a fixed assignment is present.
        nominal_start_time: Consumer's nominal start time.
        predecessor_op_ids: Operation ids that must complete before the
            consumer.
        remaining_critical_path: Static remaining-critical-path duration from
            the consumer to a DAG sink.
    """

    demand_id: str
    consumer_op_id: int
    num_pairs: int
    assigned: EPRLinkAssignment | None
    candidates: tuple[EPRLinkAssignment, ...]
    nominal_start_time: float
    predecessor_op_ids: tuple[int, ...]
    remaining_critical_path: float


@dataclass(frozen=True, slots=True)
class SchedulingInstance:
    """A self-contained scheduling artifact for an external RL scheduler.

    Attributes:
        schema_version: Scheduling-instance schema version.
        instance_id: Deterministic identifier derived from
            ``source_fingerprint``.
        compiler_version: memq_dqc version that produced the instance.
        source_fingerprint: Hash of the normalized inputs, options, hardware
            profile, and schema version.
        time_unit: Unit for all durations and nominal times.
        operations: Distributed operations, ordered by ``op_id``.
        dependencies: Precedence edges, ordered by ``(source, target)``.
        resources: Physical resources, ordered by ``resource_id``.
        epr_demands: Entanglement demands, ordered by ``demand_id``.
        nominal_makespan: Maximum nominal operation end time.
        metadata: Reproducibility metadata (partitioner, seed, profile, ...).
    """

    schema_version: int
    instance_id: str
    compiler_version: str
    source_fingerprint: str
    time_unit: str
    operations: tuple[SchedulingOperation, ...]
    dependencies: tuple[SchedulingDependency, ...]
    resources: tuple[SchedulingResource, ...]
    epr_demands: tuple[EPRDemand, ...]
    nominal_makespan: float
    metadata: Mapping[str, JSONValue] = field(default_factory=dict)


_EPR_CONSUMER_OP_TYPES = frozenset(
    {"epr_generation", "remote_swap", "remote_gate"}
)
_INTERVAL_EPSILON = 1e-9

_IdT = TypeVar("_IdT")


def validate_scheduling_instance(instance: SchedulingInstance) -> None:
    """Validate the structural and nominal-schedule invariants of an instance.

    Args:
        instance: The scheduling instance to validate.

    Raises:
        ValueError: If any invariant is violated. The message names the
            offending id(s) and the invariant.
    """
    op_ids = _validate_unique_ids(
        (op.op_id for op in instance.operations),
        kind="operation",
    )
    resource_ids = _validate_unique_ids(
        (resource.resource_id for resource in instance.resources),
        kind="resource",
    )
    _validate_unique_ids(
        (demand.demand_id for demand in instance.epr_demands),
        kind="EPR demand",
    )

    op_by_id = {op.op_id: op for op in instance.operations}
    _validate_dependencies(instance, op_ids)
    _validate_acyclic(instance, op_ids)
    _validate_epr_demands(instance, op_by_id, resource_ids)
    _validate_nominal_times(instance)
    _validate_nominal_ordering(instance, op_by_id)
    _validate_resource_intervals(instance)
    _validate_makespan(instance)


def _validate_unique_ids(
    ids: Iterable[_IdT],
    *,
    kind: str,
) -> set[_IdT]:
    """Return the id set, raising if any id repeats.

    Args:
        ids: Iterable of identifiers to check.
        kind: Human-readable id kind for error messages.

    Returns:
        The set of unique identifiers.

    Raises:
        ValueError: If an identifier appears more than once.
    """
    seen: set[_IdT] = set()
    for identifier in ids:
        if identifier in seen:
            raise ValueError(
                f"Duplicate {kind} id {identifier!r} violates id uniqueness."
            )
        seen.add(identifier)
    return seen


def _validate_dependencies(
    instance: SchedulingInstance,
    op_ids: set[int],
) -> None:
    """Validate that every dependency endpoint refers to a known operation.

    Raises:
        ValueError: If a dependency references an unknown operation id.
    """
    for dependency in instance.dependencies:
        if dependency.source_op_id not in op_ids:
            raise ValueError(
                "Dependency references unknown source operation "
                f"{dependency.source_op_id!r} (endpoints-exist invariant)."
            )
        if dependency.target_op_id not in op_ids:
            raise ValueError(
                "Dependency references unknown target operation "
                f"{dependency.target_op_id!r} (endpoints-exist invariant)."
            )


def _validate_acyclic(
    instance: SchedulingInstance,
    op_ids: set[int],
) -> None:
    """Validate that the operation dependency graph is acyclic.

    Uses Kahn's algorithm so the check has no third-party dependency.

    Raises:
        ValueError: If the dependency graph contains a cycle.
    """
    successors: dict[int, list[int]] = {op_id: [] for op_id in op_ids}
    in_degree: dict[int, int] = {op_id: 0 for op_id in op_ids}
    for dependency in instance.dependencies:
        successors[dependency.source_op_id].append(dependency.target_op_id)
        in_degree[dependency.target_op_id] += 1

    ready = [op_id for op_id, degree in in_degree.items() if degree == 0]
    visited = 0
    while ready:
        current = ready.pop()
        visited += 1
        for successor in successors[current]:
            in_degree[successor] -= 1
            if in_degree[successor] == 0:
                ready.append(successor)

    if visited != len(op_ids):
        raise ValueError(
            "Operation dependency graph is not acyclic (acyclicity invariant)."
        )


def _validate_epr_demands(
    instance: SchedulingInstance,
    op_by_id: Mapping[int, SchedulingOperation],
    resource_ids: set[str],
) -> None:
    """Validate EPR-demand references, pair counts, and assignments.

    Raises:
        ValueError: If a demand references a non-consuming or unknown
            operation, an unknown link or communication qubit, or an assignment
            whose link count disagrees with ``num_pairs``.
    """
    for demand in instance.epr_demands:
        consumer = op_by_id.get(demand.consumer_op_id)
        if consumer is None:
            raise ValueError(
                f"EPR demand {demand.demand_id!r} references unknown consumer "
                f"operation {demand.consumer_op_id!r}."
            )
        if consumer.op_type not in _EPR_CONSUMER_OP_TYPES:
            raise ValueError(
                f"EPR demand {demand.demand_id!r} references non-EPR-consuming "
                f"operation {demand.consumer_op_id!r} of type "
                f"{consumer.op_type!r}."
            )
        if demand.num_pairs <= 0:
            raise ValueError(
                f"EPR demand {demand.demand_id!r} must require at least one "
                f"pair; got {demand.num_pairs}."
            )

        assignments = list(demand.candidates)
        if demand.assigned is not None:
            assignments.append(demand.assigned)
        if not assignments:
            raise ValueError(
                f"EPR demand {demand.demand_id!r} has neither a fixed "
                "assignment nor candidate assignments."
            )
        for assignment in assignments:
            if len(assignment.link_ids) != demand.num_pairs:
                raise ValueError(
                    f"EPR demand {demand.demand_id!r} expects "
                    f"{demand.num_pairs} pair(s) but an assignment lists "
                    f"{len(assignment.link_ids)} link(s)."
                )
            for link_id in assignment.link_ids:
                if link_id not in resource_ids:
                    raise ValueError(
                        f"EPR demand {demand.demand_id!r} references unknown "
                        f"link resource {link_id!r}."
                    )
            for comm_id in assignment.comm_qubit_ids:
                if comm_id not in resource_ids:
                    raise ValueError(
                        f"EPR demand {demand.demand_id!r} references unknown "
                        f"communication-qubit resource {comm_id!r}."
                    )


def _validate_nominal_times(instance: SchedulingInstance) -> None:
    """Validate that durations and nominal times are finite and nonnegative.

    Raises:
        ValueError: If any duration or nominal time is non-finite, negative, or
            inconsistent (``nominal_end`` before ``nominal_start``).
    """
    import math

    for op in instance.operations:
        for label, value in (
            ("duration", op.duration),
            ("nominal_start", op.nominal_start),
            ("nominal_end", op.nominal_end),
        ):
            if not math.isfinite(value) or value < 0.0:
                raise ValueError(
                    f"Operation {op.op_id!r} has invalid {label}={value!r} "
                    "(finite-nonnegative invariant)."
                )
        if op.nominal_end + _INTERVAL_EPSILON < op.nominal_start:
            raise ValueError(
                f"Operation {op.op_id!r} ends before it starts "
                f"(nominal_start={op.nominal_start}, "
                f"nominal_end={op.nominal_end})."
            )
    if not math.isfinite(instance.nominal_makespan) or (
        instance.nominal_makespan < 0.0
    ):
        raise ValueError(
            f"nominal_makespan={instance.nominal_makespan!r} is not a finite "
            "nonnegative value."
        )


def _validate_nominal_ordering(
    instance: SchedulingInstance,
    op_by_id: Mapping[int, SchedulingOperation],
) -> None:
    """Validate that nominal start times satisfy every dependency.

    Raises:
        ValueError: If a target operation starts before its source ends.
    """
    for dependency in instance.dependencies:
        source = op_by_id[dependency.source_op_id]
        target = op_by_id[dependency.target_op_id]
        if target.nominal_start + _INTERVAL_EPSILON < source.nominal_end:
            raise ValueError(
                f"Nominal ordering violates dependency "
                f"{dependency.source_op_id}->{dependency.target_op_id}: "
                f"target starts at {target.nominal_start} before source ends "
                f"at {source.nominal_end}."
            )


def _validate_resource_intervals(instance: SchedulingInstance) -> None:
    """Validate that per-qubit nominal intervals do not illegally overlap.

    Raises:
        ValueError: If two operations occupy the same qubit resource at
            overlapping times.
    """
    intervals: dict[str, list[tuple[float, float, int]]] = {}
    for op in instance.operations:
        for resource_id in (*op.data_qubits, *op.comm_qubits):
            intervals.setdefault(resource_id, []).append(
                (op.nominal_start, op.nominal_end, op.op_id)
            )

    for resource_id, entries in intervals.items():
        entries.sort()
        for (_, prev_end, prev_op), (start, _, current_op) in zip(
            entries, entries[1:], strict=False
        ):
            if start + _INTERVAL_EPSILON < prev_end:
                raise ValueError(
                    f"Qubit resource {resource_id!r} is double-booked by "
                    f"operations {prev_op} and {current_op} "
                    "(resource-exclusivity invariant)."
                )


def _validate_makespan(instance: SchedulingInstance) -> None:
    """Validate that ``nominal_makespan`` equals the maximum nominal end.

    Raises:
        ValueError: If the recorded makespan disagrees with the operations.
    """
    expected = max(
        (op.nominal_end for op in instance.operations),
        default=0.0,
    )
    if abs(expected - instance.nominal_makespan) > _INTERVAL_EPSILON:
        raise ValueError(
            f"nominal_makespan={instance.nominal_makespan} does not equal the "
            f"maximum nominal operation end time {expected}."
        )
