# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from openqasm3 import ast

from memq_dqc.builder.circuit_extractor import extract_distributed_circuit
from memq_dqc.circuit import Circuit, build_circuit
from memq_dqc.circuit.op import Op
from memq_dqc.network import NetworkGraph, PhysicalQubit
from memq_dqc.partition import Partitioner
from memq_dqc.preprocessing.qasm.io import load_qasm_program
from memq_dqc.preprocessing.qasm.types import CircuitQubit


def test_circuit_builds_mono_from_program(simple1_circuit_path) -> None:
    program = load_qasm_program(str(simple1_circuit_path))

    circuit = Circuit(program)

    assert circuit.mono.program is program
    assert circuit.mono.ops
    assert circuit.mono.statements
    assert circuit.distributed is None
    assert circuit.mono.dag.depth == len(circuit.mono.dag.layers)


def test_circuit_builds_from_path(simple1_circuit_path) -> None:
    circuit = Circuit(str(simple1_circuit_path))

    assert circuit.mono.ops
    assert circuit.mono.statements


def test_build_circuit_returns_circuit(simple1_circuit_path) -> None:
    circuit = build_circuit(str(simple1_circuit_path))

    assert isinstance(circuit, Circuit)


def test_distributed_ops_track_remote_flag(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo_kwargs={"window_length": 3},
    )
    partitioner.run()
    extract_distributed_circuit(partitioner)

    distributed = partitioner.circuit.distributed
    assert distributed is not None
    assert not any(op.is_remote for op in partitioner.circuit.mono.ops)
    assert any(op.is_remote for op in distributed.ops)
    assert any(op.name == "rcx" and op.is_remote for op in distributed.ops)
    assert any(op.name == "cx" and not op.is_remote for op in distributed.ops)


def test_op_ebit_pairs_returns_none_for_local_ops() -> None:
    op = Op(
        op_id=0,
        statement_id=0,
        name="cx",
        is_remote=False,
        qubits=(
            CircuitQubit(register_name="q0", index=0),
            CircuitQubit(register_name="q1", index=0),
        ),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("cx"),
            arguments=[],
            qubits=[],
        ),
    )

    assert op.ebit_pairs is None


def test_op_ebit_pairs_returns_one_pair_for_remote_gates() -> None:
    comm_a = CircuitQubit(register_name="c2", index=0)
    comm_b = CircuitQubit(register_name="c1", index=0)
    op = Op(
        op_id=0,
        statement_id=0,
        name="rcx",
        is_remote=True,
        qubits=(
            CircuitQubit(register_name="q0", index=0),
            CircuitQubit(register_name="q1", index=0),
            comm_a,
            comm_b,
        ),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("rcx"),
            arguments=[],
            qubits=[],
        ),
    )

    assert op.ebit_pairs == (
        (
            PhysicalQubit(
                qpu_id=2,
                qubit_id=0,
                qubit_type="communication",
            ),
            PhysicalQubit(
                qpu_id=1,
                qubit_id=0,
                qubit_type="communication",
            ),
        ),
    )


def test_op_ebit_pairs_returns_two_pairs_for_rswap() -> None:
    comm_a_0 = CircuitQubit(register_name="c2", index=0)
    comm_b_0 = CircuitQubit(register_name="c1", index=0)
    comm_a_1 = CircuitQubit(register_name="c2", index=1)
    comm_b_1 = CircuitQubit(register_name="c1", index=1)
    op = Op(
        op_id=0,
        statement_id=0,
        name="rswap",
        is_remote=True,
        qubits=(
            CircuitQubit(register_name="q0", index=0),
            CircuitQubit(register_name="q1", index=0),
            comm_a_0,
            comm_b_0,
            comm_a_1,
            comm_b_1,
        ),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("rswap"),
            arguments=[],
            qubits=[],
        ),
    )

    assert op.ebit_pairs == (
        (
            PhysicalQubit(
                qpu_id=2,
                qubit_id=0,
                qubit_type="communication",
            ),
            PhysicalQubit(
                qpu_id=1,
                qubit_id=0,
                qubit_type="communication",
            ),
        ),
        (
            PhysicalQubit(
                qpu_id=2,
                qubit_id=1,
                qubit_type="communication",
            ),
            PhysicalQubit(
                qpu_id=1,
                qubit_id=1,
                qubit_type="communication",
            ),
        ),
    )
