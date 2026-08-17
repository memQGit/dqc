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

"""JSON serialization for operation schedules.

Opt-in helpers for converting an [OperationSchedule][memq_dqc.scheduler.schedule.OperationSchedule] into a JSON
document. Serialization never happens automatically as part of scheduling;
call [schedule_to_json][memq_dqc.scheduler.serialize.schedule_to_json] (or [Scheduler.to_json][memq_dqc.scheduler.schedule.Scheduler.to_json]) explicitly when
an exportable representation is needed.

The document has two top-level keys:

* ``makespan``: the schedule's total execution time.
* ``operations``: a flat, time-ordered list of events. Per-qubit timelines
  are omitted because they are fully reconstructable from ``operations``.

Each entry in ``operations`` carries a ``type`` discriminator that is either
``"operation"`` (a [ScheduledOperation][memq_dqc.scheduler.schedule.ScheduledOperation]) or ``"entanglement"`` (an
[EntanglementGeneration][memq_dqc.scheduler.schedule.EntanglementGeneration]), its stored fields, and the derived
``end_time`` for convenience.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

from memq_dqc.scheduler.schedule import (
    EntanglementGeneration,
    OperationSchedule,
    ScheduledOperation,
    ScheduleEvent,
)

if TYPE_CHECKING:
    from os import PathLike


def _event_to_dict(event: ScheduleEvent) -> dict[str, Any]:
    """Return a JSON-serializable mapping for one scheduled event.

    Args:
        event: A scheduled operation or entanglement-generation event.

    Returns:
        A mapping of the event's fields, tagged with a ``type`` discriminator
        and augmented with the derived ``end_time``.

    Raises:
        TypeError: If the event is not a supported schedule event type.
    """
    if isinstance(event, ScheduledOperation):
        return {
            "type": "operation",
            "op_id": event.op_id,
            "statement_id": event.statement_id,
            "name": event.name,
            "qubits": list(event.qubits),
            "start_time": event.start_time,
            "duration": event.duration,
            "end_time": event.end_time,
            "is_remote": event.is_remote,
        }
    if isinstance(event, EntanglementGeneration):
        return {
            "type": "entanglement",
            "name": event.name,
            "qubits": list(event.qubits),
            "start_time": event.start_time,
            "duration": event.duration,
            "end_time": event.end_time,
            "is_remote": event.is_remote,
            "was_used": event.was_used,
        }
    raise TypeError(
        f"Unsupported schedule event type: {type(event).__name__}."
    )


def _schedule_to_dict(schedule: OperationSchedule) -> dict[str, Any]:
    """Return a JSON-serializable mapping for an operation schedule.

    Args:
        schedule: The operation schedule to convert.

    Returns:
        A mapping with ``makespan`` and ``operations`` keys.
    """
    return {
        "makespan": schedule.makespan,
        "operations": [_event_to_dict(event) for event in schedule.operations],
    }


def schedule_to_json(
    schedule: OperationSchedule,
    path: str | PathLike[str] | None = None,
    *,
    indent: int | None = 2,
) -> str:
    """Serialize an operation schedule to a JSON document.

    This is an opt-in helper; scheduling never serializes automatically. The
    document has a ``makespan`` field and a flat, time-ordered ``operations``
    list. Each operation carries a ``type`` discriminator (``"operation"`` or
    ``"entanglement"``), its stored fields, and the derived ``end_time``.

    Args:
        schedule: The operation schedule to serialize.
        path: Optional destination file. When given, the JSON document is
            written there as UTF-8 text in addition to being returned.
        indent: Indentation forwarded to `json.dumps`. Pass ``None`` for
            the most compact single-line output.

    Returns:
        The JSON document as a string.
    """
    document = json.dumps(_schedule_to_dict(schedule), indent=indent)
    if path is not None:
        Path(path).write_text(document, encoding="utf-8")
    return document
