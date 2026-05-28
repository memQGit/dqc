# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import math

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
from memq_dqc.scheduler import (
    DESLinkFIFOScheduler,
    OperationSchedule,
    Scheduler,
    SchedulerHardwareProfile,
    des_link_fifo_schedule,
)


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
    qasm_path = tmp_path / "des_schedule.qasm"
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


def _remote_gate(
    *,
    op_id: int,
    statement_id: int,
    data_register_a: str,
    data_register_b: str,
    comm_register_a: str,
    comm_register_b: str,
) -> Op:
    return Op(
        op_id=op_id,
        statement_id=statement_id,
        name="rcx",
        is_remote=True,
        qubits=(
            CircuitQubit(register_name=data_register_a, index=0),
            CircuitQubit(register_name=data_register_b, index=0),
            CircuitQubit(register_name=comm_register_a, index=0),
            CircuitQubit(register_name=comm_register_b, index=0),
        ),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("rcx"),
            arguments=[],
            qubits=[],
        ),
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
    rate: float,
    local_one_qubit_gate_time: float = 10.0,
    local_two_qubit_gate_time: float = 500.0,
    des_entanglement_time_step: float = 1.0,
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
            des_entanglement_time_step=des_entanglement_time_step,
            epr_lifetime=epr_lifetime,
        )

    monkeypatch.setattr(
        schedule_module,
        "_load_scheduler_timing_model",
        _load_timing_model,
    )


def test_des_link_fifo_schedule_single_cycle_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    _patch_scheduler_timing_model(monkeypatch, rate=100.0)
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[2] q;\n"
            "cx q[0], q[1];\n"
        ),
    )

    schedule = des_link_fifo_schedule(distributed_circuit, seed=0)

    assert isinstance(schedule, OperationSchedule)
    assert [event.name for event in schedule.operations] == [
        "epr",
        "catent",
        "rcx",
        "catdisent",
    ]

    epr_event, catent_event, remote_op, catdisent_event = schedule.operations
    assert epr_event.start_time == 0.0
    assert epr_event.duration == 1.0
    assert catent_event.start_time == 1.0
    assert catent_event.duration == 513.0
    assert remote_op.start_time == 514.0
    assert remote_op.duration == 500.0
    assert catdisent_event.start_time == 1014.0
    assert catdisent_event.duration == 23.0
    assert schedule.makespan == 1037.0


def test_des_link_fifo_schedule_retries_until_seeded_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    _patch_scheduler_timing_model(monkeypatch, rate=0.5)
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[2] q;\n"
            "cx q[0], q[1];\n"
        ),
    )

    schedule = des_link_fifo_schedule(distributed_circuit, seed=0)

    epr_event, catent_event, remote_op, catdisent_event = schedule.operations
    assert epr_event.duration == 4.0
    assert catent_event.start_time == 4.0
    assert catent_event.duration == 513.0
    assert remote_op.start_time == 517.0
    assert remote_op.duration == 500.0
    assert catdisent_event.start_time == 1017.0
    assert catdisent_event.duration == 23.0
    assert schedule.makespan == 1040.0


def test_des_link_fifo_schedule_waits_for_data_qubits_before_request(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    _patch_scheduler_timing_model(monkeypatch, rate=100.0)
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

    schedule = des_link_fifo_schedule(distributed_circuit, seed=0)

    assert [event.name for event in schedule.operations] == [
        "x",
        "h",
        "epr",
        "catent",
        "rcx",
        "catdisent",
    ]

    x_op, h_op, epr_event, catent_event, remote_op, catdisent_event = (
        schedule.operations
    )
    assert x_op.end_time == 10.0
    assert h_op.end_time == 10.0
    assert epr_event.start_time == 10.0
    assert epr_event.duration == 1.0
    assert catent_event.start_time == 11.0
    assert catent_event.duration == 513.0
    assert remote_op.start_time == 524.0
    assert remote_op.duration == 500.0
    assert catdisent_event.start_time == 1024.0
    assert catdisent_event.duration == 23.0
    assert schedule.makespan == 1047.0


def test_des_link_fifo_schedule_runs_parallel_requests_on_disjoint_links(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    _patch_scheduler_timing_model(monkeypatch, rate=100.0)
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
            _remote_gate(
                op_id=0,
                statement_id=0,
                data_register_a="q0",
                data_register_b="q1",
                comm_register_a="c0",
                comm_register_b="c1",
            ),
            _remote_gate(
                op_id=1,
                statement_id=1,
                data_register_a="q2",
                data_register_b="q3",
                comm_register_a="c2",
                comm_register_b="c3",
            ),
        ],
    )

    schedule = des_link_fifo_schedule(distributed_circuit, seed=0)

    assert [event.name for event in schedule.operations] == [
        "epr",
        "epr",
        "rcx",
        "rcx",
    ]
    first_epr, second_epr, first_remote, second_remote = schedule.operations
    assert first_epr.start_time == 0.0
    assert second_epr.start_time == 0.0
    assert first_remote.start_time == 1.0
    assert second_remote.start_time == 1.0
    assert first_remote.duration == 500.0
    assert second_remote.duration == 500.0
    assert schedule.makespan == 501.0


def test_scheduler_runs_des_link_fifo_via_registry(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    _patch_scheduler_timing_model(monkeypatch, rate=100.0)
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[2] q;\n"
            "cx q[0], q[1];\n"
        ),
    )

    scheduler = Scheduler(
        distributed_circuit,
        algo="des_link_fifo",
        algo_kwargs={"seed": 0},
    )
    scheduler.run()

    assert isinstance(scheduler.schedule, OperationSchedule)
    assert [event.name for event in scheduler.schedule.operations] == [
        "epr",
        "catent",
        "rcx",
        "catdisent",
    ]


def test_des_link_fifo_scheduler_uses_profile_rate_defaults(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[2] q;\n"
            "cx q[0], q[1];\n"
        ),
    )

    scheduler = DESLinkFIFOScheduler(
        distributed_circuit,
        profile=SchedulerHardwareProfile.sr_trapped_ion(
            entanglement_profile="neutral_atom.polarization"
        ),
    )

    assert scheduler.t_cycle == pytest.approx(1.0)
    assert scheduler.p_success == pytest.approx(1.0 - math.exp(-3.2e-2))


def test_des_link_fifo_schedule_rejects_invalid_parameters(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    class _InvalidTimingModel:
        local_one_qubit_gate_time = 10.0
        local_two_qubit_gate_time = 500.0
        measurement_time = 3.0
        entanglement_generation_rate = 0.5
        entanglement_time = 2.0
        epr_lifetime = 50.0
        state_teleport_time = 523.0
        catent_time = 513.0
        catdisent_time = 23.0
        des_t_cycle = 0.0
        des_success_probability = 0.0

    monkeypatch.setattr(
        schedule_module,
        "_load_scheduler_timing_model",
        lambda hardware_profile: _InvalidTimingModel(),
    )
    distributed_circuit = _build_distributed_circuit(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        (
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            "qubit[2] q;\n"
            "cx q[0], q[1];\n"
        ),
    )

    with pytest.raises(ValueError, match="t_cycle"):
        DESLinkFIFOScheduler(distributed_circuit).run()


def test_des_link_fifo_schedule_supports_rswap_with_two_pairs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    _patch_scheduler_timing_model(monkeypatch, rate=100.0)
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

    schedule = des_link_fifo_schedule(distributed_circuit, seed=0)

    assert [event.name for event in schedule.operations] == [
        "epr",
        "epr",
        "rswap",
    ]
    first_epr, second_epr, rswap_op = schedule.operations
    assert first_epr.duration == 1.0
    assert second_epr.duration == 1.0
    assert rswap_op.start_time == 1.0
    assert rswap_op.duration == 500.0
    assert schedule.makespan == 501.0


def test_des_link_fifo_schedule_waits_for_both_rswap_pairs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    _patch_scheduler_timing_model(monkeypatch, rate=0.5)
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

    schedule = des_link_fifo_schedule(distributed_circuit, seed=1)

    first_epr, second_epr, rswap_op = schedule.operations
    assert first_epr.duration == 3.0
    assert second_epr.duration == 3.0
    assert rswap_op.start_time == 3.0
    assert rswap_op.duration == 500.0
    assert schedule.makespan == 503.0


def test_des_link_fifo_schedule_regenerates_expired_pairs(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    _patch_scheduler_timing_model(
        monkeypatch,
        rate=100.0,
        epr_lifetime=50.0,
    )
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

    def _resolve_link_parameters(
        self: DESLinkFIFOScheduler,
        link_key: tuple[str, str],
    ) -> tuple[float, float]:
        del self
        if link_key == ("c0[0]", "c1[0]"):
            return 1.0, 1.0
        return 60.0, 1.0

    monkeypatch.setattr(
        DESLinkFIFOScheduler,
        "_resolve_link_parameters",
        _resolve_link_parameters,
    )

    schedule = des_link_fifo_schedule(distributed_circuit, seed=0)

    unused_epr, slow_epr, regenerated_epr, rswap_op = schedule.operations
    assert [event.name for event in schedule.operations] == [
        "epr",
        "epr",
        "epr",
        "rswap",
    ]
    assert isinstance(unused_epr, schedule_module.EntanglementGeneration)
    assert isinstance(slow_epr, schedule_module.EntanglementGeneration)
    assert isinstance(regenerated_epr, schedule_module.EntanglementGeneration)
    assert unused_epr.was_used is False
    assert unused_epr.start_time == 0.0
    assert unused_epr.duration == 51.0
    assert slow_epr.was_used is True
    assert slow_epr.start_time == 0.0
    assert slow_epr.duration == 60.0
    assert regenerated_epr.was_used is True
    assert regenerated_epr.start_time == 51.0
    assert regenerated_epr.duration == 9.0
    assert rswap_op.start_time == 60.0
    assert rswap_op.duration == 500.0
    assert schedule.makespan == 560.0
