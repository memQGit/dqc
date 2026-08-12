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

"""Tests for the zero-EPR-wait nominal schedule and instance assembly."""

from pathlib import Path

import pytest

from xdqc import (
    SchedulerHardwareProfile,
    compile_scheduling_instance,
    compute_scheduling_source_fingerprint,
    load_settings,
)
from xdqc.scheduler import scheduling_instance_to_json
from xdqc.scheduler.instance import (
    SchedulingCompileOptions,
    SchedulingInstance,
)
from xdqc.scheduler.nominal import TIME_UNIT

_CONSUMER_OP_TYPES = {"epr_generation", "remote_swap", "remote_gate"}


@pytest.fixture()
def instance(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
):
    return compile_scheduling_instance(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )


def test_time_unit_and_makespan(instance) -> None:
    assert instance.time_unit == TIME_UNIT
    expected = max(op.nominal_end for op in instance.operations)
    assert instance.nominal_makespan == pytest.approx(expected)


def test_dependencies_respected_by_nominal_times(instance) -> None:
    by_id = {op.op_id: op for op in instance.operations}
    for dependency in instance.dependencies:
        source = by_id[dependency.source_op_id]
        target = by_id[dependency.target_op_id]
        assert target.nominal_start >= source.nominal_end - 1e-9


def test_some_operation_starts_at_zero(instance) -> None:
    assert any(op.nominal_start == 0.0 for op in instance.operations)


def test_demands_map_to_consuming_operations(instance) -> None:
    by_id = {op.op_id: op for op in instance.operations}
    assert instance.epr_demands
    for demand in instance.epr_demands:
        consumer = by_id[demand.consumer_op_id]
        assert consumer.op_type in _CONSUMER_OP_TYPES
        assert demand.num_pairs >= 1
        assert demand.assigned is not None
        assert len(demand.assigned.link_ids) == demand.num_pairs
        assert demand.nominal_start_time == consumer.nominal_start


def test_expected_number_of_demands(instance) -> None:
    consumers = [
        op
        for op in instance.operations
        if op.op_type in {"epr_generation", "remote_swap"}
        or (op.op_type == "remote_gate" and op.group_id is None)
    ]
    assert len(instance.epr_demands) == len(consumers)


def test_resources_cover_all_operation_qubits(instance) -> None:
    resource_ids = {resource.resource_id for resource in instance.resources}
    for op in instance.operations:
        for qubit in (*op.data_qubits, *op.comm_qubits):
            assert qubit in resource_ids


def test_link_resources_present_for_demands(instance) -> None:
    link_ids = {
        resource.resource_id
        for resource in instance.resources
        if resource.resource_type == "link"
    }
    assert link_ids
    for demand in instance.epr_demands:
        assert demand.assigned is not None
        for link_id in demand.assigned.link_ids:
            assert link_id in link_ids


def test_deferred_ebit_assignment_exposes_candidates(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    instance = compile_scheduling_instance(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        options=SchedulingCompileOptions(ebit_assignment=False),
    )
    assert instance.epr_demands
    for demand in instance.epr_demands:
        assert demand.assigned is None
        assert demand.candidates
        for candidate in demand.candidates:
            assert len(candidate.link_ids) == demand.num_pairs


def test_seed_is_recorded_and_reproducible(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    options = SchedulingCompileOptions(partition_seed=0)
    first = compile_scheduling_instance(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        options=options,
    )
    second = compile_scheduling_instance(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        options=options,
    )
    assert first.metadata["partition_seed"] == 0
    assert first.source_fingerprint == second.source_fingerprint
    assert scheduling_instance_to_json(
        first, indent=None
    ) == scheduling_instance_to_json(second, indent=None)


def test_default_compile_is_reproducible(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    first = compile_scheduling_instance(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    second = compile_scheduling_instance(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    assert scheduling_instance_to_json(
        first, indent=None
    ) == scheduling_instance_to_json(second, indent=None)


def test_bell_has_no_epr_demands(
    bell_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    instance = compile_scheduling_instance(
        bell_circuit_path, three_comp_one_comm_x2_network_path
    )
    assert instance.epr_demands == ()


def _hardware(instance: SchedulingInstance) -> dict[str, float]:
    """Return the instance's recorded hardware parameters as plain floats."""
    recorded = instance.metadata["hardware"]
    assert isinstance(recorded, dict)
    return {
        key: value
        for key, value in recorded.items()
        if isinstance(value, float)
    }


def test_default_metadata_records_settings_hardware(instance) -> None:
    settings = load_settings()
    profile = SchedulerHardwareProfile()
    modality = settings.modality_profile(profile.modality)
    entanglement = settings.entanglement_profile(profile.entanglement_profile)

    hardware = _hardware(instance)

    assert hardware["one_qubit_gate_time"] == pytest.approx(
        modality.one_qubit_gate_time
    )
    assert hardware["two_qubit_gate_time"] == pytest.approx(
        modality.two_qubit_gate_time
    )
    assert hardware["entanglement_rate"] == pytest.approx(
        entanglement.entanglement_rate
    )
    assert hardware["epr_lifetime"] == pytest.approx(entanglement.epr_lifetime)
    assert hardware["des_entanglement_time_step"] == pytest.approx(
        settings.des_simulation.entanglement_time_step
    )


def test_gate_time_override_slows_the_schedule(
    instance,
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    baseline_two_qubit = _hardware(instance)["two_qubit_gate_time"]
    options = SchedulingCompileOptions(
        hardware_profile=SchedulerHardwareProfile(
            two_qubit_gate_time=2 * baseline_two_qubit
        )
    )

    slower = compile_scheduling_instance(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        options=options,
    )

    assert _hardware(slower)["two_qubit_gate_time"] == pytest.approx(
        2 * baseline_two_qubit
    )
    assert slower.nominal_makespan > instance.nominal_makespan
    baseline_durations = {op.op_id: op.duration for op in instance.operations}
    assert any(
        op.duration > baseline_durations[op.op_id] for op in slower.operations
    )
    assert all(
        op.duration >= baseline_durations[op.op_id] for op in slower.operations
    )


def test_override_compile_is_reproducible(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    options = SchedulingCompileOptions(
        partition_seed=0,
        hardware_profile=SchedulerHardwareProfile(
            two_qubit_gate_time=120.0, epr_lifetime=80.0
        ),
    )

    first = compile_scheduling_instance(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        options=options,
    )
    second = compile_scheduling_instance(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        options=options,
    )

    assert scheduling_instance_to_json(
        first, indent=None
    ) == scheduling_instance_to_json(second, indent=None)


def test_overrides_change_the_source_fingerprint(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    baseline = compute_scheduling_source_fingerprint(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    overridden = compute_scheduling_source_fingerprint(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        SchedulingCompileOptions(
            hardware_profile=SchedulerHardwareProfile(
                two_qubit_gate_time=120.0
            )
        ),
    )
    other = compute_scheduling_source_fingerprint(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        SchedulingCompileOptions(
            hardware_profile=SchedulerHardwareProfile(
                two_qubit_gate_time=240.0
            )
        ),
    )

    assert baseline != overridden
    assert overridden != other


def test_empty_overrides_leave_the_fingerprint_unchanged(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    baseline = compute_scheduling_source_fingerprint(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    explicit_default = compute_scheduling_source_fingerprint(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        SchedulingCompileOptions(hardware_profile=SchedulerHardwareProfile()),
    )

    assert baseline == explicit_default
