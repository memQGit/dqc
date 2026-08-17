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

"""Deterministic zero-EPR-wait nominal schedule and instance assembly.

Builds a [SchedulingInstance][memq_dqc.scheduler.instance.SchedulingInstance] from a
compiled [DistributedCircuit][memq_dqc.circuit.circuit.DistributedCircuit] and its
[NetworkGraph][memq_dqc.network.network_graph.NetworkGraph]. The nominal schedule is a deterministic
*prediction*, not an executable final schedule: every distributed operation is
placed as early as possible subject to DAG precedence and per-qubit exclusivity,
using deterministic operation durations and *zero* EPR-generation time. The
external simulator supplies its own entanglement-generation and lifetime models
and enforces the DAG dynamically; the nominal times are observations and
readiness estimates only.

The builder reuses the annotated distributed DAG
([memq_dqc.circuit.dag.build_annotated_dag][memq_dqc.circuit.dag.annotated.build_annotated_dag]) for operation classification,
physical/communication qubits, e-bit pairs, and cat-entanglement groups, and the
scheduler timing model for deterministic durations.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import networkx as nx

from memq_dqc.circuit.dag import build_annotated_dag
from memq_dqc.scheduler.instance import (
    SCHEDULING_INSTANCE_SCHEMA_VERSION,
    EPRDemand,
    EPRLinkAssignment,
    SchedulingCompileOptions,
    SchedulingDependency,
    SchedulingInstance,
    SchedulingOperation,
    SchedulingResource,
    validate_scheduling_instance,
)
from memq_dqc.scheduler.schedule import (
    _load_scheduler_timing_model,
    _operation_duration,
    _physical_qubit_label,
    _resolve_scheduler_hardware_profile,
)

if TYPE_CHECKING:
    from memq_dqc.circuit.circuit import DistributedCircuit
    from memq_dqc.network import NetworkGraph, PhysicalQubit
    from memq_dqc.scheduler.instance import JSONValue
    from memq_dqc.scheduler.schedule import SchedulerTimingModel

TIME_UNIT = "microseconds"

_EPR_GENERATION_TYPE = "epr_generation"
_REMOTE_SWAP_TYPE = "remote_swap"
_REMOTE_GATE_TYPE = "remote_gate"


def build_scheduling_instance(
    distributed: DistributedCircuit,
    network: NetworkGraph,
    *,
    options: SchedulingCompileOptions,
    compiler_version: str,
    source_fingerprint: str,
) -> SchedulingInstance:
    """Assemble a validated scheduling instance for a compiled circuit.

    Args:
        distributed: The compiled distributed circuit to describe.
        network: The network graph the circuit was compiled for.
        options: Compilation options recorded for reproducibility; its
            ``hardware_profile`` selects deterministic operation durations.
        compiler_version: memq_dqc version producing the instance.
        source_fingerprint: Precomputed fingerprint of the normalized inputs
            and options; also used to derive ``instance_id``.

    Returns:
        A validated [SchedulingInstance][memq_dqc.scheduler.instance.SchedulingInstance].
    """
    profile = _resolve_scheduler_hardware_profile(
        profile=options.hardware_profile,
        modality="trapped_ion.ba",
        entanglement_profile="ion.time_bin",
    )
    timing_model = _load_scheduler_timing_model(profile)

    graph = build_annotated_dag(distributed)
    order = list(nx.lexicographical_topological_sort(graph, key=lambda n: n))
    durations = {
        op_id: _operation_duration(graph.nodes[op_id]["op"], timing_model)
        for op_id in order
    }
    starts, ends = _compute_nominal_schedule(graph, order, durations)
    remaining_path = _remaining_critical_path(graph, order, durations)

    operations = tuple(
        _build_operation(graph.nodes[op_id], durations[op_id], starts, ends)
        for op_id in sorted(graph.nodes)
    )
    dependencies = _build_dependencies(graph)
    qubit_resources, link_registry = _build_qubit_and_seed_link_resources(
        network
    )
    epr_demands = _build_epr_demands(
        graph, order, starts, remaining_path, link_registry
    )
    resources = tuple(
        sorted(
            (*qubit_resources, *link_registry.values()),
            key=lambda resource: resource.resource_id,
        )
    )

    nominal_makespan = max(ends.values(), default=0.0)
    metadata = _build_metadata(
        options, profile, compiler_version, timing_model
    )

    instance = SchedulingInstance(
        schema_version=SCHEDULING_INSTANCE_SCHEMA_VERSION,
        instance_id=f"inst-{source_fingerprint[:16]}",
        compiler_version=compiler_version,
        source_fingerprint=source_fingerprint,
        time_unit=TIME_UNIT,
        operations=operations,
        dependencies=dependencies,
        resources=resources,
        epr_demands=epr_demands,
        nominal_makespan=nominal_makespan,
        metadata=metadata,
    )
    validate_scheduling_instance(instance)
    return instance


def _compute_nominal_schedule(
    graph: nx.DiGraph,
    order: list[int],
    durations: dict[int, float],
) -> tuple[dict[int, float], dict[int, float]]:
    """Return ASAP nominal start/end times with zero EPR-generation wait.

    Each operation starts at the latest of its predecessors' end times and the
    free times of every qubit resource it occupies, enforcing DAG precedence
    and computation/communication-qubit exclusivity.

    Args:
        graph: Annotated distributed DAG.
        order: A topological ordering of ``graph`` node ids.
        durations: Deterministic duration per operation id.

    Returns:
        A ``(starts, ends)`` pair mapping op id to nominal start and end time.
    """
    starts: dict[int, float] = {}
    ends: dict[int, float] = {}
    resource_free: dict[str, float] = {}
    for op_id in order:
        node = graph.nodes[op_id]
        qubit_ids = _operation_qubit_ids(node)
        predecessor_end = max(
            (ends[pred] for pred in graph.predecessors(op_id)),
            default=0.0,
        )
        resource_ready = max(
            (resource_free.get(qubit_id, 0.0) for qubit_id in qubit_ids),
            default=0.0,
        )
        start = max(predecessor_end, resource_ready)
        end = start + durations[op_id]
        starts[op_id] = start
        ends[op_id] = end
        for qubit_id in qubit_ids:
            resource_free[qubit_id] = end
    return starts, ends


def _remaining_critical_path(
    graph: nx.DiGraph,
    order: list[int],
    durations: dict[int, float],
) -> dict[int, float]:
    """Return the remaining-critical-path duration for each operation.

    The value for an operation is its own duration plus the longest downstream
    chain of durations to a DAG sink.

    Args:
        graph: Annotated distributed DAG.
        order: A topological ordering of ``graph`` node ids.
        durations: Deterministic duration per operation id.

    Returns:
        Mapping from op id to remaining-critical-path duration.
    """
    remaining: dict[int, float] = {}
    for op_id in reversed(order):
        successor_cost = max(
            (remaining[succ] for succ in graph.successors(op_id)),
            default=0.0,
        )
        remaining[op_id] = durations[op_id] + successor_cost
    return remaining


def _operation_qubit_ids(node: dict) -> tuple[str, ...]:
    """Return the physical qubit resource ids an operation occupies."""
    return (
        *(_physical_qubit_label(q) for q in node["physical_qubits"]),
        *(_physical_qubit_label(q) for q in node["comm_qubits"]),
    )


def _build_operation(
    node: dict,
    duration: float,
    starts: dict[int, float],
    ends: dict[int, float],
) -> SchedulingOperation:
    """Return the scheduling-operation record for one annotated node."""
    op_id = node["op_id"]
    return SchedulingOperation(
        op_id=op_id,
        statement_id=node["statement_id"],
        name=node["name"],
        op_type=node["op_type"],
        is_remote=node["is_remote"],
        data_qubits=tuple(
            _physical_qubit_label(q) for q in node["physical_qubits"]
        ),
        comm_qubits=tuple(
            _physical_qubit_label(q) for q in node["comm_qubits"]
        ),
        duration=duration,
        group_id=node["group_id"],
        nominal_start=starts[op_id],
        nominal_end=ends[op_id],
    )


def _build_dependencies(
    graph: nx.DiGraph,
) -> tuple[SchedulingDependency, ...]:
    """Return dependency records for every edge, ordered deterministically."""
    dependencies: list[SchedulingDependency] = []
    for source_id, target_id in sorted(graph.edges):
        edge = graph.edges[source_id, target_id]
        resources = tuple(
            sorted(_physical_qubit_label(q) for q in edge["qubits"])
        )
        classification = "cross_qpu" if edge["is_cross_qpu"] else "local"
        dependencies.append(
            SchedulingDependency(
                source_op_id=source_id,
                target_op_id=target_id,
                resources=resources,
                classification=classification,
            )
        )
    return tuple(dependencies)


def _build_qubit_and_seed_link_resources(
    network: NetworkGraph,
) -> tuple[tuple[SchedulingResource, ...], dict[str, SchedulingResource]]:
    """Return qubit resources and a link registry seeded from remote edges.

    Args:
        network: The network graph.

    Returns:
        A ``(qubit_resources, link_registry)`` pair. ``link_registry`` maps
        link id to its resource and is later extended with any additional link
        referenced by an EPR demand.
    """
    qubit_resources: list[SchedulingResource] = []
    for qubit in network.computation_qubits():
        qubit_resources.append(
            SchedulingResource(
                resource_id=_physical_qubit_label(qubit),
                resource_type="computation",
                qpu_id=qubit.qpu_id,
                local_index=qubit.qubit_id,
            )
        )
    for qubit in network.communication_qubits():
        qubit_resources.append(
            SchedulingResource(
                resource_id=_physical_qubit_label(qubit),
                resource_type="communication",
                qpu_id=qubit.qpu_id,
                local_index=qubit.qubit_id,
            )
        )

    link_registry: dict[str, SchedulingResource] = {}
    for first, second, data in network.graph.edges(data=True):
        if data.get("connection_type") != "remote":
            continue
        if not (first.is_communication and second.is_communication):
            continue
        _register_link(link_registry, first, second)
    return tuple(qubit_resources), link_registry


def _build_epr_demands(
    graph: nx.DiGraph,
    order: list[int],
    starts: dict[int, float],
    remaining_path: dict[int, float],
    link_registry: dict[str, SchedulingResource],
) -> tuple[EPRDemand, ...]:
    """Return EPR demands for EPR-consuming operations.

    Consumers are ``catent`` operations, ``rswap`` operations, and ungrouped
    remote gates; grouped remote gates reuse their group's ``catent`` pair and
    do not generate their own demand. Any link referenced here that is not
    already a resource is registered in ``link_registry``.

    Args:
        graph: Annotated distributed DAG.
        order: A topological ordering of ``graph`` node ids.
        starts: Nominal start times by op id.
        remaining_path: Remaining-critical-path durations by op id.
        link_registry: Mutable link resource registry to extend.

    Returns:
        EPR demands ordered by consumer op id.

    Raises:
        ValueError: If a consumer operation lacks e-bit pair information.
    """
    demands: list[EPRDemand] = []
    for op_id in order:
        node = graph.nodes[op_id]
        if not _is_epr_consumer(node):
            continue

        ebit_pairs = node["ebit_pairs"]
        ebit_candidates = node["ebit_candidates"]
        if ebit_pairs is not None:
            assigned = _assignment_from_pairs(ebit_pairs, link_registry)
            candidates: tuple[EPRLinkAssignment, ...] = ()
            num_pairs = len(ebit_pairs)
        elif ebit_candidates:
            assigned = None
            candidates = tuple(
                _assignment_from_pairs(assignment, link_registry)
                for assignment in ebit_candidates
            )
            num_pairs = len(ebit_candidates[0])
        else:
            raise ValueError(
                f"EPR-consuming operation {op_id} has no e-bit pair "
                "information (neither assigned pairs nor candidates)."
            )

        demands.append(
            EPRDemand(
                demand_id=f"epr-{op_id}",
                consumer_op_id=op_id,
                num_pairs=num_pairs,
                assigned=assigned,
                candidates=candidates,
                nominal_start_time=starts[op_id],
                predecessor_op_ids=tuple(sorted(graph.predecessors(op_id))),
                remaining_critical_path=remaining_path[op_id],
            )
        )
    demands.sort(key=lambda demand: demand.consumer_op_id)
    return tuple(demands)


def _is_epr_consumer(node: dict) -> bool:
    """Return whether an annotated node generates fresh entanglement.

    Args:
        node: An annotated-DAG node attribute mapping.

    Returns:
        True for ``catent`` (``epr_generation``), ``rswap`` (``remote_swap``),
        and ungrouped remote gates; False for grouped remote gates that reuse a
        ``catent`` pair and for all local operations.
    """
    op_type = node["op_type"]
    if op_type in (_EPR_GENERATION_TYPE, _REMOTE_SWAP_TYPE):
        return True
    return op_type == _REMOTE_GATE_TYPE and node["group_id"] is None


def _assignment_from_pairs(
    pairs: tuple[tuple[PhysicalQubit, PhysicalQubit], ...],
    link_registry: dict[str, SchedulingResource],
) -> EPRLinkAssignment:
    """Return a link assignment for a sequence of communication-qubit pairs.

    Registers any referenced link that is not already known so the resulting
    instance stays self-consistent.

    Args:
        pairs: Communication-qubit e-bit pairs.
        link_registry: Mutable link resource registry to extend.

    Returns:
        The corresponding [EPRLinkAssignment][memq_dqc.scheduler.instance.EPRLinkAssignment].
    """
    link_ids: list[str] = []
    comm_qubit_ids: list[str] = []
    for first, second in pairs:
        link_id, endpoints = _register_link(link_registry, first, second)
        link_ids.append(link_id)
        comm_qubit_ids.extend(endpoints)
    return EPRLinkAssignment(
        link_ids=tuple(link_ids),
        comm_qubit_ids=tuple(comm_qubit_ids),
    )


def _register_link(
    link_registry: dict[str, SchedulingResource],
    first: PhysicalQubit,
    second: PhysicalQubit,
) -> tuple[str, tuple[str, str]]:
    """Register (if needed) and return the link id and endpoints for a pair.

    Args:
        link_registry: Mutable link resource registry.
        first: One communication qubit of the pair.
        second: The other communication qubit of the pair.

    Returns:
        A ``(link_id, endpoints)`` pair, where ``endpoints`` is the sorted
        communication-qubit resource-id pair.
    """
    label_a = _physical_qubit_label(first)
    label_b = _physical_qubit_label(second)
    endpoints: tuple[str, str] = (
        (label_a, label_b) if label_a <= label_b else (label_b, label_a)
    )
    link_id = f"link:{endpoints[0]}<->{endpoints[1]}"
    if link_id not in link_registry:
        link_registry[link_id] = SchedulingResource(
            resource_id=link_id,
            resource_type="link",
            endpoints=endpoints,
        )
    return link_id, endpoints


def _build_metadata(
    options: SchedulingCompileOptions,
    profile: object,
    compiler_version: str,
    timing_model: SchedulerTimingModel,
) -> dict[str, JSONValue]:
    """Return reproducibility metadata recorded on the instance.

    Args:
        options: Compilation options to record.
        profile: The resolved scheduler hardware profile.
        compiler_version: memq_dqc version producing the instance.
        timing_model: The resolved timing model, recorded under ``"hardware"``
            so a consumer can recover the effective hardware parameters without
            re-resolving the profile against ``settings.toml``.

    Returns:
        The metadata mapping.
    """
    return {
        "memq_dqc_version": compiler_version,
        "partitioner": options.partitioner,
        "partitioner_kwargs": dict(options.partitioner_kwargs or {}),
        "partition_seed": options.partition_seed,
        "ebit_assignment": options.ebit_assignment,
        "group_gates": options.group_gates,
        "max_group_size": options.max_group_size,
        "modality": getattr(profile, "modality", None),
        "entanglement_profile": getattr(profile, "entanglement_profile", None),
        "hardware": {
            "one_qubit_gate_time": timing_model.local_one_qubit_gate_time,
            "two_qubit_gate_time": timing_model.local_two_qubit_gate_time,
            "measurement_time": timing_model.measurement_time,
            "entanglement_rate": timing_model.entanglement_generation_rate,
            "epr_lifetime": timing_model.epr_lifetime,
            "des_entanglement_time_step": (
                timing_model.des_entanglement_time_step
            ),
        },
        "schema_version": SCHEDULING_INSTANCE_SCHEMA_VERSION,
    }
