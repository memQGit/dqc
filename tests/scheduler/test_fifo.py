# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import matplotlib.pyplot as plt
import pytest
from matplotlib.axes import Axes

from memq_dqc.builder import extract_distributed_circuit
from memq_dqc.network import NetworkGraph
from memq_dqc.partition import Partitioner
from memq_dqc.partition.partitioner import QPU, BasePartitioner
from memq_dqc.preprocessing.qasm.io import load_qasm_program
from memq_dqc.scheduler import (
    EntanglementGeneration,
    EPRMinimizationScheduler,
    OperationSchedule,
    ScheduledOperation,
    Scheduler,
    fifo_schedule,
    plot_schedule_gantt,
)
from memq_dqc.scheduler.schedule import _build_qubit_timelines


class _TwoQpuPartitioner(BasePartitioner):
    def run(self) -> None:
        self.windows = [self.circuit.mono.ops]
        self.schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]
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
    assert [op.name for op in schedule.operations] == ["x", "h", "epr", "rcx"]
    assert schedule.qubits == ("q0[0]", "q1[0]", "c0[0]", "c1[0]")

    x_op, h_op, epr_op, remote_op = schedule.operations
    assert x_op.qubits == ("q0[0]",)
    assert x_op.start_time == 0.0
    assert x_op.duration == 1.0
    assert h_op.qubits == ("q1[0]",)
    assert h_op.start_time == 0.0
    assert h_op.duration == 1.0
    assert epr_op.qubits == ("c0[0]", "c1[0]")
    assert epr_op.start_time == 0.0
    assert epr_op.duration == 10.0
    assert epr_op.end_time == 10.0
    assert remote_op.qubits == ("q0[0]", "q1[0]", "c0[0]", "c1[0]")
    assert remote_op.start_time == epr_op.end_time
    assert remote_op.duration == 6.0
    assert remote_op.end_time == 16.0
    assert remote_op.is_remote is True
    assert schedule.makespan == 16.0


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
        "rcx",
    ]


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


def test_epr_minimization_scheduler_is_unimplemented(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )

    scheduler = Scheduler(
        distributed_circuit,
        algo=EPRMinimizationScheduler(distributed_circuit),
    )

    with pytest.raises(
        NotImplementedError,
        match="EPR-minimization scheduling is not yet implemented.",
    ):
        scheduler.run()


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
        "q0[0]": ["x", "rcx"],
        "q1[0]": ["h", "rcx"],
        "c0[0]": ["epr", "rcx"],
        "c1[0]": ["epr", "rcx"],
    }


def test_plot_schedule_gantt_renders_axes(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )
    schedule = fifo_schedule(distributed_circuit)

    axes = plot_schedule_gantt(schedule, title="FIFO Schedule")

    assert isinstance(axes, Axes)
    assert axes.get_title() == "FIFO Schedule"
    assert axes.get_xlabel() == "Time"
    assert axes.get_ylabel() == "Physical Qubit"
    assert [tick.get_text() for tick in axes.get_yticklabels()] == [
        "q0[0]",
        "q1[0]",
        "c0[0]",
        "c1[0]",
    ]
    assert len(axes.patches) == 8
    assert {text.get_text() for text in axes.texts} >= {
        "x",
        "h",
        "epr",
        "rcx",
    }
    plt.close("all")


def test_plot_schedule_gantt_marks_communication_qubit_boxes(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )
    schedule = fifo_schedule(distributed_circuit)

    axes = plot_schedule_gantt(schedule)

    hatched_patches = [
        patch for patch in axes.patches if patch.get_hatch() == "///"
    ]
    plain_patches = [
        patch for patch in axes.patches if patch.get_hatch() in {"", None}
    ]

    assert len(hatched_patches) == 4
    assert len(plain_patches) == 4
    plt.close("all")


def test_plot_schedule_gantt_explicit_ops_renders_one_row_per_event(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
    )
    schedule = fifo_schedule(distributed_circuit)

    axes = plot_schedule_gantt(schedule, explicit_ops=True)

    assert axes.get_ylabel() == "Operation"
    assert [tick.get_text() for tick in axes.get_yticklabels()] == [
        "1: x",
        "2: h",
        "3: epr",
        "4: rcx",
    ]
    assert len(axes.patches) == 4

    hatched_patches = [
        patch for patch in axes.patches if patch.get_hatch() == "///"
    ]
    plain_patches = [
        patch for patch in axes.patches if patch.get_hatch() in {"", None}
    ]

    assert len(hatched_patches) == 2
    assert len(plain_patches) == 2
    assert {text.get_text() for text in axes.texts} >= {
        "x",
        "h",
        "epr",
        "rcx",
    }
    plt.close("all")


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

    axes = plot_schedule_gantt(schedule)

    assert {text.get_text() for text in axes.texts} >= {"epr", "rcx"}
    plt.close("all")
