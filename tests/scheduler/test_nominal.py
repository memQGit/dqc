"""Tests for the zero-EPR-wait nominal schedule and instance assembly."""

from pathlib import Path

import pytest

from xdqc import compile_scheduling_instance
from xdqc.scheduler import scheduling_instance_to_json
from xdqc.scheduler.instance import SchedulingCompileOptions
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
