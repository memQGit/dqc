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
"""Tests for recompiling a scheduling instance from an injected placement."""

import dataclasses

import pytest

from xdqc import (
    Compiler,
    SchedulingInstance,
    validate_scheduling_instance,
)
from xdqc.partition.partitioner import QPU


def _copy_schedule(
    schedule: list[dict[QPU, set[int]]],
) -> list[dict[QPU, set[int]]]:
    """Return a deep copy of a partition schedule."""
    return [
        {QPU(qpu.id): set(qubits) for qpu, qubits in assignment.items()}
        for assignment in schedule
    ]


def _compiled(circuit_path, network_path) -> Compiler:
    """Return a compiled compiler for the given circuit and network."""
    compiler = Compiler(
        circuit_path,
        network_path,
        algo_kwargs={"window_length": 2},
    )
    compiler.compile()
    return compiler


def _strip_fingerprint(instance: SchedulingInstance) -> SchedulingInstance:
    """Return a copy with fingerprint-derived fields normalized."""
    return dataclasses.replace(
        instance,
        source_fingerprint="<fingerprint>",
        instance_id="<instance-id>",
    )


def test_recompile_round_trip_matches_to_scheduling_instance(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    compiler = _compiled(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    original = compiler.to_scheduling_instance()
    injected = _copy_schedule(compiler.partitioner.schedule)

    recompiled = compiler.recompile_with_placement(injected)

    assert _strip_fingerprint(recompiled) == _strip_fingerprint(original)
    validate_scheduling_instance(recompiled)


def test_recompile_relocation_adds_remote_swap_and_epr_demand(
    simple1_circuit_path,
    eight_comp_four_comm_network_path,
) -> None:
    # A static baseline: every window keeps the same placement, so the moved
    # qubit's gates stay local.
    static = [{QPU(1): {0, 1, 2}, QPU(2): {3, 4, 5}} for _ in range(4)]
    baseline = _compiled(
        simple1_circuit_path, eight_comp_four_comm_network_path
    ).recompile_with_placement(static)
    baseline_remote_gates = sum(
        1 for op in baseline.operations if op.op_type == "remote_gate"
    )

    # Relocation: after the first window, logical qubit 4 moves to QPU 1 and
    # qubit 0 moves to QPU 2 (a paired cross-QPU swap). Qubit 4's downstream
    # gates (with qubits 3 and 5, kept on QPU 2) flip to remote.
    relocation = [
        {QPU(1): {0, 1, 2}, QPU(2): {3, 4, 5}},
        {QPU(1): {1, 2, 4}, QPU(2): {0, 3, 5}},
        {QPU(1): {1, 2, 4}, QPU(2): {0, 3, 5}},
        {QPU(1): {1, 2, 4}, QPU(2): {0, 3, 5}},
    ]
    compiler = _compiled(
        simple1_circuit_path, eight_comp_four_comm_network_path
    )
    instance = compiler.recompile_with_placement(relocation)

    remote_swaps = [
        op for op in instance.operations if op.op_type == "remote_swap"
    ]
    assert len(remote_swaps) >= 1

    swap_demands = [
        demand for demand in instance.epr_demands if demand.num_pairs == 2
    ]
    assert swap_demands, "expected a two-pair EPR demand for the swap"

    relocation_remote_gates = sum(
        1 for op in instance.operations if op.op_type == "remote_gate"
    )
    # Moving qubit 4 flips its previously-local downstream gates to remote.
    assert relocation_remote_gates > baseline_remote_gates
    validate_scheduling_instance(instance)


def test_recompile_rejects_schedule_windows_size_mismatch(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    compiler = _compiled(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    # Drop one window so the schedule is shorter than the prior windows.
    injected = _copy_schedule(compiler.partitioner.schedule)[:-1]

    with pytest.raises(ValueError, match="differ in length"):
        compiler.recompile_with_placement(injected)


def test_recompile_rejects_out_of_range_qubit(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    compiler = _compiled(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    injected = _copy_schedule(compiler.partitioner.schedule)
    for assignment in injected:
        assignment[QPU(0)] = {0, 1, 99}
        assignment[QPU(1)] = {3, 4, 5}

    with pytest.raises(ValueError, match="logical qubit 99"):
        compiler.recompile_with_placement(injected)


def test_recompile_rejects_out_of_range_qpu(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    compiler = _compiled(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    injected = [
        {QPU(0): {0, 1, 2}, QPU(7): {3, 4, 5}}
        for _ in compiler.partitioner.schedule
    ]

    with pytest.raises(ValueError, match="unknown QPU id 7"):
        compiler.recompile_with_placement(injected)


def test_recompile_rejects_unequal_per_qpu_counts(
    simple1_circuit_path,
    eight_comp_four_comm_network_path,
) -> None:
    compiler = _compiled(
        simple1_circuit_path, eight_comp_four_comm_network_path
    )
    # Both windows are valid partitions within capacity, but the per-QPU
    # counts change (3/3 -> 4/2), which swap synthesis forbids.
    injected = [
        {QPU(1): {0, 1, 2}, QPU(2): {3, 4, 5}},
        {QPU(1): {0, 1, 2, 3}, QPU(2): {4, 5}},
        {QPU(1): {0, 1, 2, 3}, QPU(2): {4, 5}},
        {QPU(1): {0, 1, 2, 3}, QPU(2): {4, 5}},
    ]

    with pytest.raises(ValueError, match="per-QPU qubit counts"):
        compiler.recompile_with_placement(injected)


def test_recompile_rejects_non_partition_placement(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    compiler = _compiled(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    # Logical qubit 2 assigned to both QPUs; qubit 5 dropped.
    injected = [
        {QPU(0): {0, 1, 2}, QPU(1): {2, 3, 4}}
        for _ in compiler.partitioner.schedule
    ]

    with pytest.raises(ValueError, match="more than one QPU"):
        compiler.recompile_with_placement(injected)


def test_recompile_distinct_placements_yield_distinct_fingerprints(
    simple1_circuit_path,
    eight_comp_four_comm_network_path,
) -> None:
    placement_a = [{QPU(1): {0, 1, 2}, QPU(2): {3, 4, 5}} for _ in range(4)]
    placement_b = [
        {QPU(1): {0, 1, 2}, QPU(2): {3, 4, 5}},
        {QPU(1): {1, 2, 4}, QPU(2): {0, 3, 5}},
        {QPU(1): {1, 2, 4}, QPU(2): {0, 3, 5}},
        {QPU(1): {1, 2, 4}, QPU(2): {0, 3, 5}},
    ]

    instance_a = _compiled(
        simple1_circuit_path, eight_comp_four_comm_network_path
    ).recompile_with_placement(placement_a)
    instance_b = _compiled(
        simple1_circuit_path, eight_comp_four_comm_network_path
    ).recompile_with_placement(placement_b)

    assert instance_a.source_fingerprint != instance_b.source_fingerprint
    assert instance_a.instance_id != instance_b.instance_id


def test_recompile_leaves_plain_fingerprint_unchanged(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    # Regression guard: folding a placement in must not alter the fingerprint
    # of the normal (no-injection) compile path, i.e. passing ``placement``
    # as ``None`` is byte-identical to omitting it entirely.
    from xdqc.compiler import _fingerprint_from_parts
    from xdqc.partition.partitioner import (
        _resolve_network_input,
        _resolve_program_input,
    )
    from xdqc.scheduler.instance import SchedulingCompileOptions

    network = _resolve_network_input(three_comp_one_comm_x2_network_path)
    program = _resolve_program_input(simple1_circuit_path)
    options = SchedulingCompileOptions()

    assert _fingerprint_from_parts(
        program, network, options
    ) == _fingerprint_from_parts(program, network, options, placement=None)


def test_recompile_does_not_rerun_partitioning(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    compiler = _compiled(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    injected = _copy_schedule(compiler.partitioner.schedule)

    algorithm = compiler.partitioner._algorithm
    run_calls = {"count": 0}
    original_run = algorithm.run

    def spy_run(*args: object, **kwargs: object) -> None:
        run_calls["count"] += 1
        return original_run(*args, **kwargs)

    monkeypatch.setattr(algorithm, "run", spy_run)
    compiler.recompile_with_placement(injected)

    assert run_calls["count"] == 0
