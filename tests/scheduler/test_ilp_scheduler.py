# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import pytest
from openqasm3 import ast

import memq_dqc.scheduler.schedule as schedule_module
from memq_dqc.builder import extract_distributed_circuit
from memq_dqc.circuit import DistributedCircuit
from memq_dqc.circuit.dag import DistributedCircuitDAG
from memq_dqc.circuit.op import Op
from memq_dqc.network import NetworkGraph
from memq_dqc.partition import Partitioner
from memq_dqc.partition.partitioner import QPU, BasePartitioner
from memq_dqc.preprocessing.qasm.io import load_qasm_program
from memq_dqc.preprocessing.qasm.types import CircuitQubit
from memq_dqc.scheduler import ILPScheduler, OperationSchedule, Scheduler
from memq_dqc.scheduler.schedule import SchedulerHardwareProfile


class _TwoQpuPartitioner(BasePartitioner):
    def run(self) -> None:
        self.windows = [self.circuit.mono.ops]
        self.schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]
        self.cost = 0.0


def _build_distributed_circuit(
    tmp_path,
    network_path,
    qasm_source: str,
) -> DistributedCircuit:
    qasm_path = tmp_path / "ilp_schedule.qasm"
    qasm_path.write_text(qasm_source, encoding="utf-8")
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


def _build_manual_distributed_circuit(
    template: DistributedCircuit,
    ops: list[Op],
) -> DistributedCircuit:
    return DistributedCircuit(
        program=template.program,
        statements=template.statements,
        ops=ops,
        num_two_qubit_gates=len(ops),
        num_remote_gates=sum(1 for op in ops if op.is_remote),
        num_local_swaps_added=0,
        dag=DistributedCircuitDAG(ops),
    )


def _remote_swap_gate(
    *,
    op_id: int,
    statement_id: int,
    data_register_a: str,
    data_register_b: str,
    comm_register_a0: str,
    comm_register_b0: str,
    comm_register_a1: str,
    comm_register_b1: str,
) -> Op:
    return Op(
        op_id=op_id,
        statement_id=statement_id,
        name="rswap",
        is_remote=True,
        qubits=(
            CircuitQubit(register_name=data_register_a, index=0),
            CircuitQubit(register_name=data_register_b, index=0),
            CircuitQubit(register_name=comm_register_a0, index=0),
            CircuitQubit(register_name=comm_register_b0, index=0),
            CircuitQubit(register_name=comm_register_a1, index=1),
            CircuitQubit(register_name=comm_register_b1, index=1),
        ),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("rswap"),
            arguments=[],
            qubits=[],
        ),
    )


def _patch_scheduler_timing_model(
    monkeypatch: pytest.MonkeyPatch,
    *,
    rate: float = 0.25,
    local_one_qubit_gate_time: float = 1.0,
    local_two_qubit_gate_time: float = 5.0,
    epr_lifetime: float = 50.0,
) -> None:
    def _load_timing_model(
        hardware_profile: SchedulerHardwareProfile,
    ) -> schedule_module.SchedulerTimingModel:
        return schedule_module.SchedulerTimingModel(
            hardware_profile=hardware_profile,
            local_one_qubit_gate_time=local_one_qubit_gate_time,
            local_two_qubit_gate_time=local_two_qubit_gate_time,
            entanglement_generation_rate=rate,
            des_entanglement_time_step=1.0,
            epr_lifetime=epr_lifetime,
        )

    monkeypatch.setattr(
        schedule_module,
        "_load_scheduler_timing_model",
        _load_timing_model,
    )


def _assert_qubit_capacity(schedule: OperationSchedule) -> None:
    for timeline in schedule.timelines:
        operations = timeline.operations
        for index, current_event in enumerate(operations):
            for next_event in operations[index + 1 :]:
                assert current_event.end_time <= next_event.start_time


def test_ilp_scheduler_builds_expected_remote_schedule(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_scheduler_timing_model(monkeypatch)
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[2] q;\n"
            "x q[0];\n"
            "h q[1];\n"
            "cx q[0], q[1];\n"
        ),
    )

    scheduler = Scheduler(
        distributed_circuit,
        algo="ilp",
        algo_kwargs={"show_progress": False},
    )
    scheduler.run()

    schedule = scheduler.schedule

    assert isinstance(schedule, OperationSchedule)
    assert [event.name for event in schedule.operations] == [
        "x",
        "h",
        "epr",
        "catent",
        "rcx",
        "catdisent",
    ]

    x_op, h_op, epr_op, catent_op, remote_op, catdisent_op = (
        schedule.operations
    )
    assert x_op.start_time == 0.0
    assert x_op.duration == 1.0
    assert h_op.start_time == 0.0
    assert h_op.duration == 1.0
    assert epr_op.start_time == 0.0
    assert epr_op.duration == 4.0
    assert catent_op.start_time == 4.0
    assert catent_op.duration == 9.0
    assert remote_op.start_time == 13.0
    assert remote_op.duration == 5.0
    assert catdisent_op.start_time == 18.0
    assert catdisent_op.duration == 5.0
    assert schedule.makespan == 23.0
    _assert_qubit_capacity(schedule)


@pytest.mark.parametrize(
    ("multiplex_entangle", "expected_starts"),
    [
        (True, [0.0, 0.0, 4.0]),
        (False, [0.0, 4.0, 8.0]),
    ],
)
def test_ilp_scheduler_respects_rswap_epr_timing(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    monkeypatch: pytest.MonkeyPatch,
    multiplex_entangle: bool,
    expected_starts: list[float],
) -> None:
    _patch_scheduler_timing_model(monkeypatch)
    template = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[2] q;\n"
            "cx q[0], q[1];\n"
        ),
    )
    distributed_circuit = _build_manual_distributed_circuit(
        template,
        [
            _remote_swap_gate(
                op_id=0,
                statement_id=0,
                data_register_a="q0",
                data_register_b="q1",
                comm_register_a0="c0",
                comm_register_b0="c1",
                comm_register_a1="c0",
                comm_register_b1="c1",
            )
        ],
    )

    scheduler = ILPScheduler(
        distributed_circuit,
        multiplex_entangle=multiplex_entangle,
        show_progress=False,
    )
    scheduler.run()

    assert scheduler.schedule is not None
    assert [event.name for event in scheduler.schedule.operations] == [
        "epr",
        "epr",
        "rswap",
    ]
    assert [event.start_time for event in scheduler.schedule.operations] == (
        expected_starts
    )
    assert scheduler.schedule.operations[-1].duration == 5.0
    _assert_qubit_capacity(scheduler.schedule)


def test_ilp_scheduler_emits_progress_output_by_default(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _patch_scheduler_timing_model(monkeypatch)
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[2] q;\n"
            "x q[0];\n"
            "h q[1];\n"
            "cx q[0], q[1];\n"
        ),
    )

    scheduler = ILPScheduler(distributed_circuit)
    scheduler.run()

    captured = capsys.readouterr()
    assert "Solving ILP" in captured.err
    assert "Reconstructing schedule" in captured.err


def test_ilp_scheduler_show_progress_defaults_to_true(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _patch_scheduler_timing_model(monkeypatch)
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[2] q;\n"
            "cx q[0], q[1];\n"
        ),
    )

    scheduler = ILPScheduler(distributed_circuit)

    assert scheduler.show_progress is True
