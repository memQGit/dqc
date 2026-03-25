# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import pytest
from openqasm3 import ast

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
    DESEntanglementScheduler,
    OperationSchedule,
    Scheduler,
    des_epr_schedule,
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


def test_des_epr_schedule_single_cycle_success(
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

    schedule = des_epr_schedule(
        distributed_circuit,
        t_cycle=5.0,
        p_success=1.0,
        seed=0,
    )

    assert isinstance(schedule, OperationSchedule)
    assert [event.name for event in schedule.operations] == ["epr", "rcx"]

    epr_event, remote_op = schedule.operations
    assert epr_event.start_time == 0.0
    assert epr_event.duration == 5.0
    assert remote_op.start_time == 5.0
    assert remote_op.duration == 6.0
    assert schedule.makespan == 11.0


def test_des_epr_schedule_retries_until_seeded_success(
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

    schedule = des_epr_schedule(
        distributed_circuit,
        t_cycle=5.0,
        p_success=0.5,
        seed=0,
    )

    epr_event, remote_op = schedule.operations
    assert epr_event.duration == 15.0
    assert remote_op.start_time == 15.0
    assert schedule.makespan == 21.0


def test_des_epr_schedule_waits_for_data_qubits_before_request(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
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

    schedule = des_epr_schedule(
        distributed_circuit,
        t_cycle=5.0,
        p_success=1.0,
        seed=0,
    )

    assert [event.name for event in schedule.operations] == [
        "x",
        "h",
        "epr",
        "rcx",
    ]

    x_op, h_op, epr_event, remote_op = schedule.operations
    assert x_op.end_time == 1.0
    assert h_op.end_time == 1.0
    assert epr_event.start_time == 1.0
    assert epr_event.duration == 5.0
    assert remote_op.start_time == 6.0
    assert schedule.makespan == 12.0


def test_des_epr_schedule_runs_parallel_requests_on_disjoint_links(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
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

    schedule = des_epr_schedule(
        distributed_circuit,
        t_cycle=5.0,
        p_success=1.0,
        seed=0,
    )

    assert [event.name for event in schedule.operations] == [
        "epr",
        "epr",
        "rcx",
        "rcx",
    ]
    first_epr, second_epr, first_remote, second_remote = schedule.operations
    assert first_epr.start_time == 0.0
    assert second_epr.start_time == 0.0
    assert first_remote.start_time == 5.0
    assert second_remote.start_time == 5.0
    assert schedule.makespan == 11.0


def test_scheduler_runs_des_epr_via_registry(
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

    scheduler = Scheduler(
        distributed_circuit,
        algo="des_epr",
        algo_kwargs={"t_cycle": 5.0, "p_success": 1.0, "seed": 0},
    )
    scheduler.run()

    assert isinstance(scheduler.schedule, OperationSchedule)
    assert [event.name for event in scheduler.schedule.operations] == [
        "epr",
        "rcx",
    ]


def test_des_epr_schedule_rejects_invalid_parameters(
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

    with pytest.raises(ValueError, match="t_cycle"):
        DESEntanglementScheduler(
            distributed_circuit,
            t_cycle=0.0,
            p_success=1.0,
        ).run()

    with pytest.raises(ValueError, match="p_success"):
        DESEntanglementScheduler(
            distributed_circuit,
            t_cycle=5.0,
            p_success=0.0,
        ).run()


def test_des_epr_schedule_supports_rswap_with_two_pairs(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
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

    schedule = des_epr_schedule(
        distributed_circuit,
        t_cycle=5.0,
        p_success=1.0,
        seed=0,
    )

    assert [event.name for event in schedule.operations] == [
        "epr",
        "epr",
        "rswap",
    ]
    first_epr, second_epr, rswap_op = schedule.operations
    assert first_epr.duration == 5.0
    assert second_epr.duration == 5.0
    assert rswap_op.start_time == 5.0
    assert rswap_op.duration == 7.0
    assert schedule.makespan == 12.0


def test_des_epr_schedule_waits_for_both_rswap_pairs(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
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

    schedule = des_epr_schedule(
        distributed_circuit,
        t_cycle=5.0,
        p_success=0.5,
        seed=1,
    )

    first_epr, second_epr, rswap_op = schedule.operations
    assert first_epr.duration == 5.0
    assert second_epr.duration == 15.0
    assert rswap_op.start_time == 15.0
    assert schedule.makespan == 22.0
