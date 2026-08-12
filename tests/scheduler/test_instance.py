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

"""Tests for scheduling-instance records and validation."""

import dataclasses
import math
from pathlib import Path

import pytest

from xdqc import compile_scheduling_instance
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


def _tiny_instance() -> SchedulingInstance:
    resources = (
        SchedulingResource("q0[0]", "computation", qpu_id=0, local_index=0),
        SchedulingResource("q1[0]", "computation", qpu_id=1, local_index=0),
        SchedulingResource("c0[0]", "communication", qpu_id=0, local_index=0),
        SchedulingResource("c1[0]", "communication", qpu_id=1, local_index=0),
        SchedulingResource(
            "link:c0[0]<->c1[0]",
            "link",
            endpoints=("c0[0]", "c1[0]"),
        ),
    )
    operations = (
        SchedulingOperation(
            op_id=0,
            statement_id=0,
            name="catent",
            op_type="epr_generation",
            is_remote=True,
            data_qubits=("q0[0]", "q1[0]"),
            comm_qubits=("c0[0]", "c1[0]"),
            duration=30.0,
            group_id=0,
            nominal_start=0.0,
            nominal_end=30.0,
        ),
        SchedulingOperation(
            op_id=1,
            statement_id=1,
            name="h",
            op_type="local_gate",
            is_remote=False,
            data_qubits=("q0[0]",),
            comm_qubits=(),
            duration=10.0,
            group_id=None,
            nominal_start=30.0,
            nominal_end=40.0,
        ),
    )
    dependencies = (SchedulingDependency(0, 1, ("q0[0]",), "local"),)
    epr_demands = (
        EPRDemand(
            demand_id="epr-0",
            consumer_op_id=0,
            num_pairs=1,
            assigned=EPRLinkAssignment(
                link_ids=("link:c0[0]<->c1[0]",),
                comm_qubit_ids=("c0[0]", "c1[0]"),
            ),
            candidates=(),
            nominal_start_time=0.0,
            predecessor_op_ids=(),
            remaining_critical_path=40.0,
        ),
    )
    return SchedulingInstance(
        schema_version=SCHEDULING_INSTANCE_SCHEMA_VERSION,
        instance_id="inst-tiny",
        compiler_version="0.0.0-test",
        source_fingerprint="tinyfingerprint",
        time_unit="microseconds",
        operations=operations,
        dependencies=dependencies,
        resources=resources,
        epr_demands=epr_demands,
        nominal_makespan=40.0,
        metadata={},
    )


def test_tiny_instance_is_valid() -> None:
    validate_scheduling_instance(_tiny_instance())


def test_compiled_instance_is_valid(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    instance = compile_scheduling_instance(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    validate_scheduling_instance(instance)
    assert instance.schema_version == SCHEDULING_INSTANCE_SCHEMA_VERSION
    assert instance.operations
    assert instance.epr_demands


def test_duplicate_operation_id_rejected() -> None:
    instance = _tiny_instance()
    duplicated = dataclasses.replace(
        instance,
        operations=(*instance.operations, instance.operations[0]),
    )
    with pytest.raises(ValueError, match="Duplicate operation id"):
        validate_scheduling_instance(duplicated)


def test_dangling_dependency_rejected() -> None:
    instance = _tiny_instance()
    broken = dataclasses.replace(
        instance,
        dependencies=(
            *instance.dependencies,
            SchedulingDependency(99, 1, (), None),
        ),
    )
    with pytest.raises(ValueError, match="unknown source operation"):
        validate_scheduling_instance(broken)


def test_cycle_rejected() -> None:
    instance = _tiny_instance()
    cyclic = dataclasses.replace(
        instance,
        dependencies=(
            SchedulingDependency(0, 1, ("q0[0]",), "local"),
            SchedulingDependency(1, 0, ("q0[0]",), "local"),
        ),
    )
    with pytest.raises(ValueError, match="not acyclic"):
        validate_scheduling_instance(cyclic)


def test_makespan_mismatch_rejected() -> None:
    instance = _tiny_instance()
    bad = dataclasses.replace(instance, nominal_makespan=999.0)
    with pytest.raises(ValueError, match="nominal_makespan"):
        validate_scheduling_instance(bad)


def test_negative_duration_rejected() -> None:
    instance = _tiny_instance()
    op = dataclasses.replace(instance.operations[1], duration=-1.0)
    bad = dataclasses.replace(
        instance, operations=(instance.operations[0], op)
    )
    with pytest.raises(ValueError, match="invalid duration"):
        validate_scheduling_instance(bad)


def test_non_consuming_demand_rejected() -> None:
    instance = _tiny_instance()
    bad_demand = dataclasses.replace(
        instance.epr_demands[0],
        demand_id="epr-1",
        consumer_op_id=1,
    )
    bad = dataclasses.replace(
        instance, epr_demands=(instance.epr_demands[0], bad_demand)
    )
    with pytest.raises(ValueError, match="non-EPR-consuming"):
        validate_scheduling_instance(bad)


def test_unknown_link_rejected() -> None:
    instance = _tiny_instance()
    demand = dataclasses.replace(
        instance.epr_demands[0],
        assigned=EPRLinkAssignment(
            link_ids=("link:ghost",),
            comm_qubit_ids=("c0[0]", "c1[0]"),
        ),
    )
    bad = dataclasses.replace(instance, epr_demands=(demand,))
    with pytest.raises(ValueError, match="unknown link resource"):
        validate_scheduling_instance(bad)


def test_pair_count_mismatch_rejected() -> None:
    instance = _tiny_instance()
    demand = dataclasses.replace(instance.epr_demands[0], num_pairs=2)
    bad = dataclasses.replace(instance, epr_demands=(demand,))
    with pytest.raises(ValueError, match="expects 2 pair"):
        validate_scheduling_instance(bad)


def test_nominal_ordering_violation_rejected() -> None:
    instance = _tiny_instance()
    early = dataclasses.replace(
        instance.operations[1], nominal_start=0.0, nominal_end=10.0
    )
    bad = dataclasses.replace(
        instance,
        operations=(instance.operations[0], early),
        nominal_makespan=30.0,
    )
    with pytest.raises(ValueError, match="Nominal ordering violates"):
        validate_scheduling_instance(bad)


def test_resource_double_booking_rejected() -> None:
    instance = _tiny_instance()
    overlapping = dataclasses.replace(
        instance.operations[1], nominal_start=10.0, nominal_end=20.0
    )
    bad = dataclasses.replace(
        instance,
        operations=(instance.operations[0], overlapping),
        dependencies=(),
        nominal_makespan=30.0,
    )
    with pytest.raises(ValueError, match="double-booked"):
        validate_scheduling_instance(bad)


def test_infinite_makespan_rejected() -> None:
    instance = _tiny_instance()
    bad = dataclasses.replace(instance, nominal_makespan=math.inf)
    with pytest.raises(ValueError):
        validate_scheduling_instance(bad)
