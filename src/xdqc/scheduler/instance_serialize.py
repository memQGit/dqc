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

"""JSON persistence for scheduling instances.

Round-trippable, human-readable JSON for
:class:`~xdqc.scheduler.instance.SchedulingInstance`. The document carries
an explicit ``type`` discriminator and ``schema_version`` for
forward-compatibility, orders every collection deterministically, and rejects
non-finite numbers (no ``NaN``/infinity) on both write and read. Loading
validates the reconstructed instance, so a persisted artifact can be reused
without any live compiler state. Pickle is intentionally not used for persisted
training artifacts.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any

from xdqc.scheduler.instance import (
    SCHEDULING_INSTANCE_SCHEMA_VERSION,
    EPRDemand,
    EPRLinkAssignment,
    SchedulingDependency,
    SchedulingInstance,
    SchedulingOperation,
    SchedulingResource,
    validate_scheduling_instance,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from os import PathLike

_INSTANCE_TYPE = "scheduling_instance"


def scheduling_instance_to_json(
    instance: SchedulingInstance,
    path: str | PathLike[str] | None = None,
    *,
    indent: int | None = 2,
) -> str:
    """Serialize a scheduling instance to a JSON document.

    Args:
        instance: The scheduling instance to serialize.
        path: Optional destination file. When given, the document is written
            there as UTF-8 text in addition to being returned.
        indent: Indentation forwarded to :func:`json.dumps`. Pass ``None`` for
            the most compact single-line output (suited to large corpora).

    Returns:
        The JSON document as a string.

    Raises:
        ValueError: If the instance contains a non-finite number.
    """
    document = json.dumps(
        _instance_to_dict(instance),
        indent=indent,
        allow_nan=False,
    )
    if path is not None:
        Path(path).write_text(document, encoding="utf-8")
    return document


def scheduling_instance_from_json(
    source: str | PathLike[str] | Mapping[str, Any],
) -> SchedulingInstance:
    """Load and validate a scheduling instance from JSON.

    Args:
        source: A parsed mapping, a JSON document string, or a path to a JSON
            file (as ``str`` or :class:`os.PathLike`).

    Returns:
        The reconstructed, validated :class:`SchedulingInstance`.

    Raises:
        ValueError: If the document type or schema version is unsupported, a
            number is non-finite, or the reconstructed instance is invalid.
    """
    data = _load_document(source)
    document_type = data.get("type")
    if document_type != _INSTANCE_TYPE:
        raise ValueError(
            f"Unsupported document type {document_type!r}; expected "
            f"{_INSTANCE_TYPE!r}."
        )
    schema_version = data.get("schema_version")
    if schema_version != SCHEDULING_INSTANCE_SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported scheduling-instance schema version "
            f"{schema_version!r}; this build supports "
            f"{SCHEDULING_INSTANCE_SCHEMA_VERSION}."
        )

    instance = _instance_from_dict(data)
    validate_scheduling_instance(instance)
    return instance


def _load_document(
    source: str | PathLike[str] | Mapping[str, Any],
) -> dict[str, Any]:
    """Return the raw document mapping from a supported source.

    Args:
        source: A mapping, a JSON string, or a path to a JSON file.

    Returns:
        The parsed document as a mapping.

    Raises:
        ValueError: If a parsed number is non-finite.
    """
    if isinstance(source, os.PathLike):
        text = Path(source).read_text(encoding="utf-8")
        return _loads(text)
    if isinstance(source, str):
        if source.lstrip().startswith("{"):
            return _loads(source)
        return _loads(Path(source).read_text(encoding="utf-8"))
    return dict(source)


def _loads(text: str) -> dict[str, Any]:
    """Parse JSON text, rejecting non-finite numeric literals."""
    return json.loads(text, parse_constant=_reject_nonfinite)


def _reject_nonfinite(constant: str) -> float:
    """Raise for ``NaN``/``Infinity`` JSON literals.

    Args:
        constant: The literal token JSON encountered.

    Raises:
        ValueError: Always, naming the offending literal.
    """
    raise ValueError(
        f"Scheduling-instance JSON must not contain the non-finite literal "
        f"{constant!r}."
    )


def _instance_to_dict(instance: SchedulingInstance) -> dict[str, Any]:
    """Return a JSON-serializable mapping for a scheduling instance."""
    return {
        "type": _INSTANCE_TYPE,
        "schema_version": instance.schema_version,
        "instance_id": instance.instance_id,
        "compiler_version": instance.compiler_version,
        "source_fingerprint": instance.source_fingerprint,
        "time_unit": instance.time_unit,
        "nominal_makespan": instance.nominal_makespan,
        "operations": [_operation_to_dict(op) for op in instance.operations],
        "dependencies": [
            _dependency_to_dict(dep) for dep in instance.dependencies
        ],
        "resources": [
            _resource_to_dict(resource) for resource in instance.resources
        ],
        "epr_demands": [
            _demand_to_dict(demand) for demand in instance.epr_demands
        ],
        "metadata": dict(instance.metadata),
    }


def _operation_to_dict(op: SchedulingOperation) -> dict[str, Any]:
    """Return a JSON-serializable mapping for one operation."""
    return {
        "op_id": op.op_id,
        "statement_id": op.statement_id,
        "name": op.name,
        "op_type": op.op_type,
        "is_remote": op.is_remote,
        "data_qubits": list(op.data_qubits),
        "comm_qubits": list(op.comm_qubits),
        "duration": op.duration,
        "group_id": op.group_id,
        "nominal_start": op.nominal_start,
        "nominal_end": op.nominal_end,
    }


def _dependency_to_dict(dep: SchedulingDependency) -> dict[str, Any]:
    """Return a JSON-serializable mapping for one dependency."""
    return {
        "source_op_id": dep.source_op_id,
        "target_op_id": dep.target_op_id,
        "resources": list(dep.resources),
        "classification": dep.classification,
    }


def _resource_to_dict(resource: SchedulingResource) -> dict[str, Any]:
    """Return a JSON-serializable mapping for one resource."""
    return {
        "resource_id": resource.resource_id,
        "resource_type": resource.resource_type,
        "qpu_id": resource.qpu_id,
        "local_index": resource.local_index,
        "endpoints": (
            None if resource.endpoints is None else list(resource.endpoints)
        ),
        "parameters": dict(resource.parameters),
    }


def _assignment_to_dict(assignment: EPRLinkAssignment) -> dict[str, Any]:
    """Return a JSON-serializable mapping for one link assignment."""
    return {
        "link_ids": list(assignment.link_ids),
        "comm_qubit_ids": list(assignment.comm_qubit_ids),
    }


def _demand_to_dict(demand: EPRDemand) -> dict[str, Any]:
    """Return a JSON-serializable mapping for one EPR demand."""
    return {
        "demand_id": demand.demand_id,
        "consumer_op_id": demand.consumer_op_id,
        "num_pairs": demand.num_pairs,
        "assigned": (
            None
            if demand.assigned is None
            else _assignment_to_dict(demand.assigned)
        ),
        "candidates": [
            _assignment_to_dict(candidate) for candidate in demand.candidates
        ],
        "nominal_start_time": demand.nominal_start_time,
        "predecessor_op_ids": list(demand.predecessor_op_ids),
        "remaining_critical_path": demand.remaining_critical_path,
    }


def _instance_from_dict(data: Mapping[str, Any]) -> SchedulingInstance:
    """Reconstruct a scheduling instance from a document mapping."""
    return SchedulingInstance(
        schema_version=data["schema_version"],
        instance_id=data["instance_id"],
        compiler_version=data["compiler_version"],
        source_fingerprint=data["source_fingerprint"],
        time_unit=data["time_unit"],
        operations=tuple(
            _operation_from_dict(entry) for entry in data["operations"]
        ),
        dependencies=tuple(
            _dependency_from_dict(entry) for entry in data["dependencies"]
        ),
        resources=tuple(
            _resource_from_dict(entry) for entry in data["resources"]
        ),
        epr_demands=tuple(
            _demand_from_dict(entry) for entry in data["epr_demands"]
        ),
        nominal_makespan=data["nominal_makespan"],
        metadata=dict(data.get("metadata", {})),
    )


def _operation_from_dict(entry: Mapping[str, Any]) -> SchedulingOperation:
    """Reconstruct one operation from a mapping."""
    return SchedulingOperation(
        op_id=entry["op_id"],
        statement_id=entry["statement_id"],
        name=entry["name"],
        op_type=entry["op_type"],
        is_remote=entry["is_remote"],
        data_qubits=tuple(entry["data_qubits"]),
        comm_qubits=tuple(entry["comm_qubits"]),
        duration=entry["duration"],
        group_id=entry["group_id"],
        nominal_start=entry["nominal_start"],
        nominal_end=entry["nominal_end"],
    )


def _dependency_from_dict(entry: Mapping[str, Any]) -> SchedulingDependency:
    """Reconstruct one dependency from a mapping."""
    return SchedulingDependency(
        source_op_id=entry["source_op_id"],
        target_op_id=entry["target_op_id"],
        resources=tuple(entry["resources"]),
        classification=entry.get("classification"),
    )


def _resource_from_dict(entry: Mapping[str, Any]) -> SchedulingResource:
    """Reconstruct one resource from a mapping."""
    endpoints = entry.get("endpoints")
    return SchedulingResource(
        resource_id=entry["resource_id"],
        resource_type=entry["resource_type"],
        qpu_id=entry.get("qpu_id"),
        local_index=entry.get("local_index"),
        endpoints=None if endpoints is None else (endpoints[0], endpoints[1]),
        parameters=dict(entry.get("parameters", {})),
    )


def _assignment_from_dict(entry: Mapping[str, Any]) -> EPRLinkAssignment:
    """Reconstruct one link assignment from a mapping."""
    return EPRLinkAssignment(
        link_ids=tuple(entry["link_ids"]),
        comm_qubit_ids=tuple(entry["comm_qubit_ids"]),
    )


def _demand_from_dict(entry: Mapping[str, Any]) -> EPRDemand:
    """Reconstruct one EPR demand from a mapping."""
    assigned = entry.get("assigned")
    return EPRDemand(
        demand_id=entry["demand_id"],
        consumer_op_id=entry["consumer_op_id"],
        num_pairs=entry["num_pairs"],
        assigned=(
            None if assigned is None else _assignment_from_dict(assigned)
        ),
        candidates=tuple(
            _assignment_from_dict(candidate)
            for candidate in entry.get("candidates", [])
        ),
        nominal_start_time=entry["nominal_start_time"],
        predecessor_op_ids=tuple(entry["predecessor_op_ids"]),
        remaining_critical_path=entry["remaining_critical_path"],
    )
