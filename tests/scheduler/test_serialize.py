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
"""Tests for JSON serialization of operation schedules."""

import json

import pytest

from xdqc import Partitioner, Scheduler
from xdqc.scheduler import (
    EntanglementGeneration,
    OperationSchedule,
    ScheduledOperation,
    ScheduledQubitTimeline,
    schedule_to_json,
)


def _example_schedule() -> OperationSchedule:
    operation = ScheduledOperation(
        op_id=0,
        statement_id=1,
        name="cx",
        qubits=("q0[0]", "q0[1]"),
        start_time=0.0,
        duration=2.0,
        is_remote=False,
    )
    entanglement = EntanglementGeneration(
        qubits=("c0[0]", "c1[0]"),
        start_time=2.0,
        duration=50.0,
        was_used=False,
    )
    timelines = (
        ScheduledQubitTimeline(qubit="q0[0]", operations=(operation,)),
        ScheduledQubitTimeline(qubit="c0[0]", operations=(entanglement,)),
    )
    return OperationSchedule(
        operations=(operation, entanglement),
        timelines=timelines,
        makespan=52.0,
    )


def test_schedule_to_json_top_level_shape() -> None:
    document = json.loads(schedule_to_json(_example_schedule()))

    assert set(document) == {"makespan", "operations"}
    assert document["makespan"] == 52.0
    assert len(document["operations"]) == 2


def test_schedule_to_json_operation_fields() -> None:
    document = json.loads(schedule_to_json(_example_schedule()))

    op = document["operations"][0]
    assert op == {
        "type": "operation",
        "op_id": 0,
        "statement_id": 1,
        "name": "cx",
        "qubits": ["q0[0]", "q0[1]"],
        "start_time": 0.0,
        "duration": 2.0,
        "end_time": 2.0,
        "is_remote": False,
    }


def test_schedule_to_json_entanglement_fields() -> None:
    document = json.loads(schedule_to_json(_example_schedule()))

    epr = document["operations"][1]
    assert epr == {
        "type": "entanglement",
        "name": "epr",
        "qubits": ["c0[0]", "c1[0]"],
        "start_time": 2.0,
        "duration": 50.0,
        "end_time": 52.0,
        "is_remote": True,
        "was_used": False,
    }


def test_schedule_to_json_omits_timelines() -> None:
    document = json.loads(schedule_to_json(_example_schedule()))

    assert "timelines" not in document


def test_schedule_to_json_writes_file(tmp_path) -> None:
    out_path = tmp_path / "schedule.json"

    document = schedule_to_json(_example_schedule(), out_path)

    assert out_path.is_file()
    assert json.loads(out_path.read_text(encoding="utf-8")) == json.loads(
        document
    )


def test_schedule_to_json_indent_none_is_compact() -> None:
    document = schedule_to_json(_example_schedule(), indent=None)

    assert "\n" not in document
    assert json.loads(document)["makespan"] == 52.0


def test_schedule_to_json_rejects_unknown_event() -> None:
    schedule = OperationSchedule(
        operations=(object(),),  # type: ignore[arg-type]
        timelines=(),
        makespan=0.0,
    )

    with pytest.raises(TypeError, match="Unsupported schedule event type"):
        schedule_to_json(schedule)


def _ran_scheduler(circuit_path, network_path) -> Scheduler:
    partitioner = Partitioner(
        network_path, circuit_path, algo_kwargs={"window_length": 2}
    )
    partitioner.run()
    scheduler = Scheduler(partitioner.distributed_circuit, algo="fifo")
    scheduler.run()
    return scheduler


def test_scheduler_to_json_matches_result(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    scheduler = _ran_scheduler(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )

    document = json.loads(scheduler.to_json())

    assert scheduler.schedule is not None
    assert document["makespan"] == scheduler.schedule.makespan
    assert len(document["operations"]) == len(scheduler.schedule.operations)


def test_scheduler_to_json_writes_file(
    tmp_path,
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    scheduler = _ran_scheduler(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    out_path = tmp_path / "schedule.json"

    scheduler.to_json(out_path)

    assert out_path.is_file()
    assert json.loads(out_path.read_text(encoding="utf-8"))["operations"]


def test_scheduler_to_json_requires_schedule(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    partitioner = Partitioner(
        three_comp_one_comm_x2_network_path,
        simple1_circuit_path,
        algo_kwargs={"window_length": 2},
    )
    partitioner.run()
    scheduler = Scheduler(partitioner.distributed_circuit, algo="fifo")

    with pytest.raises(ValueError, match="No schedule available"):
        scheduler.to_json()
