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

import logging
from pathlib import Path

import pytest

from memq_dqc.builder import extract_distributed_circuit
from memq_dqc.network import NetworkGraph
from memq_dqc.partition import Partitioner
from memq_dqc.partition.partitioner import QPU, BasePartitioner
from memq_dqc.preprocessing.qasm.io import load_qasm_program
from memq_dqc.scheduler import (
    EntanglementGeneration,
    OperationSchedule,
    ScheduledOperation,
    Scheduler,
    SchedulerHardwareProfile,
    fifo_schedule,
)
from memq_dqc.scheduler.schedule import (
    _build_qubit_timelines,
    _count_failed_entanglement_operations,
)

_DEFAULT_EPR_DURATION = 1.0 / 3.5e-6


class _TwoQpuPartitioner(BasePartitioner):
    def run(self) -> None:
        self.windows = [self.circuit.mono.ops]
        self.schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]
        self.cost = 0.0


class _TwoQpuTwoCommPartitioner(BasePartitioner):
    def run(self) -> None:
        self.windows = [self.circuit.mono.ops]
        self.schedule = [{QPU(id=1): {0, 1}, QPU(id=2): {2, 3}}]
        self.cost = 0.0


def _build_distributed_circuit(tmp_path, network_path):
    qasm_path = tmp_path / "fifo_schedule.qasm"
    qasm_path.write_text(
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[2] q;\n"
            "x q[0];\n"
            "h q[1];\n"
            "cx q[0], q[1];\n"
        ),
        encoding="utf-8",
    )
    program = load_qasm_program(str(qasm_path))
    network = NetworkGraph(str(network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_TwoQpuPartitioner(network, program),
    )
    partitioner.run()
    extract_distributed_circuit(partitioner)
    assert partitioner.circuit.distributed is not None
    return partitioner.circuit.distributed


def _build_multi_comm_distributed_circuit(tmp_path, *, ebit_assignment: bool):
    qasm_path = tmp_path / "fifo_multi_comm_schedule.qasm"
    qasm_path.write_text(
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[4] q;\n"
            "cx q[0], q[2];\n"
            "cx q[1], q[3];\n"
        ),
        encoding="utf-8",
    )
    program = load_qasm_program(str(qasm_path))
    network = NetworkGraph(
        str(
            Path(__file__).parents[1]
            / "fixtures"
            / "networks"
            / "simple_8comp_4comm.json"
        )
    )
    partitioner = Partitioner(
        network,
        program,
        algo=_TwoQpuTwoCommPartitioner(network, program),
    )
    partitioner.run()
    extract_distributed_circuit(
        partitioner,
        ebit_assignment=ebit_assignment,
    )
    assert partitioner.circuit.distributed is not None
    return partitioner.circuit.distributed


def test_fifo_schedule_returns_operation_schedule(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )

    schedule = fifo_schedule(distributed_circuit)

    assert isinstance(schedule, OperationSchedule)
    assert [op.name for op in schedule.operations] == [
        "x",
        "h",
        "epr",
        "catent",
        "rcx",
        "catdisent",
    ]
    assert schedule.qubits == ("q0[0]", "q1[0]", "c0[0]", "c1[0]")

    x_op, h_op, epr_op, catent_op, remote_op, catdisent_op = (
        schedule.operations
    )
    assert x_op.qubits == ("q0[0]",)
    assert x_op.start_time == 0.0
    assert x_op.duration == 10.0
    assert h_op.qubits == ("q1[0]",)
    assert h_op.start_time == 0.0
    assert h_op.duration == 10.0
    assert epr_op.qubits == ("c0[0]", "c1[0]")
    assert epr_op.start_time == 0.0
    assert epr_op.duration == pytest.approx(_DEFAULT_EPR_DURATION)
    assert epr_op.end_time == pytest.approx(_DEFAULT_EPR_DURATION)
    assert catent_op.qubits == ("q0[0]", "q1[0]", "c0[0]", "c1[0]")
    assert catent_op.start_time == pytest.approx(epr_op.end_time)
    assert catent_op.duration == 513.0
    assert remote_op.start_time == pytest.approx(catent_op.end_time)
    assert remote_op.duration == 500.0
    assert catdisent_op.start_time == pytest.approx(remote_op.end_time)
    assert catdisent_op.duration == 23.0
    assert remote_op.is_remote is True
    assert schedule.makespan == pytest.approx(_DEFAULT_EPR_DURATION + 1036.0)


def test_deferred_ebit_assignment_removes_comm_dependency(
    tmp_path,
) -> None:
    explicit = _build_multi_comm_distributed_circuit(
        tmp_path,
        ebit_assignment=True,
    )
    deferred = _build_multi_comm_distributed_circuit(
        tmp_path,
        ebit_assignment=False,
    )
    explicit_comm_edge = (3, 6)
    assert explicit.dag.graph.has_edge(*explicit_comm_edge)
    assert any(
        qubit.register_name.startswith("c")
        for qubit in explicit.dag.graph[explicit_comm_edge[0]][
            explicit_comm_edge[1]
        ]["qubits"]
    )
    assert not deferred.dag.graph.has_edge(*explicit_comm_edge)
    assert deferred.ebit_candidates_by_op_id is not None
    assert len(deferred.ebit_candidates_by_op_id[1]) == 2
    assert len(deferred.ebit_candidates_by_op_id[6]) == 2


def test_deferred_ebit_assignment_changes_fifo_schedule(
    tmp_path,
) -> None:
    explicit = _build_multi_comm_distributed_circuit(
        tmp_path,
        ebit_assignment=True,
    )
    deferred = _build_multi_comm_distributed_circuit(
        tmp_path,
        ebit_assignment=False,
    )

    explicit_schedule = fifo_schedule(explicit)
    deferred_schedule = fifo_schedule(deferred)

    assert deferred_schedule.makespan < explicit_schedule.makespan
    assert any(
        event.name == "epr" and event.qubits == ("c1[1]", "c2[1]")
        for event in deferred_schedule.operations
    )


def test_scheduler_runs_fifo_by_default(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )

    scheduler = Scheduler(distributed_circuit)
    scheduler.run()

    schedule = scheduler.schedule

    assert isinstance(schedule, OperationSchedule)
    assert [op.name for op in schedule.operations] == [
        "x",
        "h",
        "epr",
        "catent",
        "rcx",
        "catdisent",
    ]


def test_scheduler_info_verbosity_reports_summary_metrics(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    caplog,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )
    scheduler = Scheduler(
        distributed_circuit,
        algo="des_link_fifo",
        algo_kwargs={"seed": 0},
    )

    with caplog.at_level(logging.INFO, logger="memq_dqc"):
        scheduler.run(verbosity="info")

    assert "makespan=" in caplog.text
    assert "failed_entanglement_operations=0" in caplog.text


def test_scheduler_accepts_explicit_multiplex_setting(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )

    scheduler = Scheduler(
        distributed_circuit,
        multiplex_entangle=False,
    )

    assert scheduler.multiplex_entangle is False


@pytest.mark.parametrize(
    (
        "modality",
        "expected_one_qubit",
        "expected_catent_duration",
        "expected_remote_duration",
        "expected_catdisent_duration",
        "expected_entanglement_duration",
    ),
    [
        ("trapped_ion.sr", 13.0, 216.0, 200.0, 29.0, 1.0 / 3.5e-6),
        ("neutral_atom", 1.0, 4.8, 0.8, 5.0, 1.0 / 3.5e-6),
    ],
)
def test_scheduler_accepts_explicit_modality(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    modality,
    expected_one_qubit,
    expected_catent_duration,
    expected_remote_duration,
    expected_catdisent_duration,
    expected_entanglement_duration,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )

    scheduler = Scheduler(distributed_circuit, modality=modality)
    scheduler.run()

    assert scheduler.schedule is not None
    x_op, h_op, epr_op, catent_op, remote_op, catdisent_op = (
        scheduler.schedule.operations
    )
    assert x_op.duration == pytest.approx(expected_one_qubit)
    assert h_op.duration == pytest.approx(expected_one_qubit)
    assert epr_op.duration == pytest.approx(expected_entanglement_duration)
    assert catent_op.duration == pytest.approx(expected_catent_duration)
    assert remote_op.duration == pytest.approx(expected_remote_duration)
    assert catdisent_op.duration == pytest.approx(expected_catdisent_duration)


def test_scheduler_accepts_explicit_entanglement_profile(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )

    scheduler = Scheduler(
        distributed_circuit,
        entanglement_profile="ion.polarization",
    )
    scheduler.run()

    assert scheduler.schedule is not None
    _x_op, _h_op, epr_op, catent_op, remote_op, catdisent_op = (
        scheduler.schedule.operations
    )
    assert epr_op.duration == pytest.approx(400.0)
    assert catent_op.duration == pytest.approx(513.0)
    assert remote_op.duration == pytest.approx(500.0)
    assert catdisent_op.duration == pytest.approx(23.0)


def test_scheduler_profile_object_supports_cross_family_mix(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )

    scheduler = Scheduler(
        distributed_circuit,
        profile=SchedulerHardwareProfile.neutral_atom(
            entanglement_profile="ion.polarization"
        ),
    )
    scheduler.run()

    assert scheduler.schedule is not None
    x_op, h_op, epr_op, catent_op, remote_op, catdisent_op = (
        scheduler.schedule.operations
    )
    assert x_op.duration == pytest.approx(1.0)
    assert h_op.duration == pytest.approx(1.0)
    assert epr_op.duration == pytest.approx(400.0)
    assert catent_op.duration == pytest.approx(4.8)
    assert remote_op.duration == pytest.approx(0.8)
    assert catdisent_op.duration == pytest.approx(5.0)


def test_scheduler_rejects_unknown_algorithm(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )

    with pytest.raises(
        ValueError, match="Unknown scheduling algorithm: unknown"
    ):
        Scheduler(distributed_circuit, algo="unknown")


def test_fifo_schedule_builds_per_qubit_timelines(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )

    schedule = fifo_schedule(distributed_circuit)
    timeline_by_qubit = {
        timeline.qubit: [op.name for op in timeline.operations]
        for timeline in schedule.timelines
    }

    assert timeline_by_qubit == {
        "q0[0]": ["x", "catent", "rcx", "catdisent"],
        "q1[0]": ["h", "catent", "rcx", "catdisent"],
        "c0[0]": ["epr", "catent", "rcx", "catdisent"],
        "c1[0]": ["epr", "catent", "rcx", "catdisent"],
    }


def test_operation_schedule_accepts_entanglement_generation_events() -> None:
    scheduled_events = [
        EntanglementGeneration(
            qubits=("c0[0]", "c1[0]"),
            start_time=0.0,
        ),
        ScheduledOperation(
            op_id=0,
            statement_id=0,
            name="rcx",
            qubits=("q0[0]", "q1[0]", "c0[0]", "c1[0]"),
            start_time=10.0,
            duration=6.0,
            is_remote=True,
        ),
    ]
    qubit_order = ("q0[0]", "q1[0]", "c0[0]", "c1[0]")
    schedule = OperationSchedule(
        operations=tuple(scheduled_events),
        timelines=_build_qubit_timelines(scheduled_events, qubit_order),
        makespan=max(event.end_time for event in scheduled_events),
    )

    assert [event.name for event in schedule.operations] == ["epr", "rcx"]
    timeline_by_qubit = {
        timeline.qubit: [event.name for event in timeline.operations]
        for timeline in schedule.timelines
    }

    assert timeline_by_qubit == {
        "q0[0]": ["rcx"],
        "q1[0]": ["rcx"],
        "c0[0]": ["epr", "rcx"],
        "c1[0]": ["epr", "rcx"],
    }


def test_count_failed_entanglement_operations() -> None:
    schedule = OperationSchedule(
        operations=(
            EntanglementGeneration(
                qubits=("c0[0]", "c1[0]"),
                start_time=0.0,
                duration=10.0,
                was_used=False,
            ),
            EntanglementGeneration(
                qubits=("c0[0]", "c1[0]"),
                start_time=10.0,
                duration=10.0,
                was_used=True,
            ),
            ScheduledOperation(
                op_id=0,
                statement_id=0,
                name="rcx",
                qubits=("q0[0]", "q1[0]", "c0[0]", "c1[0]"),
                start_time=20.0,
                duration=6.0,
                is_remote=True,
            ),
        ),
        timelines=(),
        makespan=26.0,
    )

    assert _count_failed_entanglement_operations(schedule) == 1
