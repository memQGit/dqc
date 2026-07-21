# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from types import SimpleNamespace
from typing import Any

from openqasm3 import ast

from xdqc.builder.extract_utils import (
    identify_gate_groups,
    synthesize_state_teleportation_swaps,
)
from xdqc.circuit.op import Op
from xdqc.partition.partitioner import QPU
from xdqc.preprocessing.qasm.types import CircuitQubit


def _op(op_id, name, *qubit_indices):
    return Op(
        op_id=op_id,
        statement_id=op_id,
        name=name,
        is_remote=False,
        qubits=tuple(
            CircuitQubit(register_name="q", index=index)
            for index in qubit_indices
        ),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier(name),
            arguments=[],
            qubits=[],
        ),
    )


def _partitioned_circuit(ops, windows) -> tuple[Any, Any]:
    qpu = QPU(id=0)
    circuit = SimpleNamespace(mono=SimpleNamespace(ops=ops))
    partition = SimpleNamespace(
        windows=windows,
        schedule=[{qpu: {0, 1, 2, 3, 4}} for _ in windows],
    )
    return circuit, partition


def test_identify_gate_groups_groups_shared_control_gates() -> None:
    ops = [
        _op(0, "cx", 0, 1),
        _op(1, "h", 1),
        _op(2, "cx", 0, 2),
    ]
    circuit, partition = _partitioned_circuit(ops, [ops])

    reordered_ops, group_indices, gate_packets = identify_gate_groups(
        circuit,
        partition,
    )

    assert [op.op_id for op in reordered_ops] == [0, 1, 2]
    assert group_indices == {(0, 3)}
    assert gate_packets == [[{0, 1}, {1}, {0, 2}]]


def test_identify_gate_groups_commutes_disjoint_two_qubit_gate() -> None:
    ops = [
        _op(0, "cx", 0, 1),
        _op(1, "cx", 2, 3),
        _op(2, "cx", 0, 4),
    ]
    circuit, partition = _partitioned_circuit(ops, [ops])

    reordered_ops, group_indices, gate_packets = identify_gate_groups(
        circuit,
        partition,
    )

    assert [op.op_id for op in reordered_ops] == [0, 2, 1]
    assert group_indices == {(0, 2)}
    assert gate_packets == [[{0, 1}, {0, 4}]]


def test_identify_gate_groups_does_not_group_across_windows() -> None:
    ops = [
        _op(0, "cx", 0, 1),
        _op(1, "cx", 0, 2),
    ]
    circuit, partition = _partitioned_circuit(ops, [[ops[0]], [ops[1]]])

    reordered_ops, group_indices, gate_packets = identify_gate_groups(
        circuit,
        partition,
    )

    assert [op.op_id for op in reordered_ops] == [0, 1]
    assert group_indices == {(0, 1), (1, 2)}
    assert gate_packets == [[{0, 1}], [{0, 2}]]


def test_synthesize_swaps_emits_only_cross_qpu_swaps() -> None:
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    qpu2 = QPU(id=2)
    schedule = [
        {qpu0: {0, 1}, qpu1: {2, 3}, qpu2: {4, 5}},
        {qpu0: {0, 3}, qpu1: {1, 4}, qpu2: {2, 5}},
    ]

    swaps = synthesize_state_teleportation_swaps(schedule)

    assert len(swaps) == 1
    assert swaps[0]
    assert all(swap.pos0[0] != swap.pos1[0] for swap in swaps[0])


def test_synthesize_swaps_handles_three_qpu_cycle() -> None:
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    qpu2 = QPU(id=2)
    schedule = [
        {qpu0: {0, 1}, qpu1: {2, 3}, qpu2: {4, 5}},
        {qpu0: {1, 4}, qpu1: {0, 5}, qpu2: {2, 3}},
    ]

    swaps = synthesize_state_teleportation_swaps(schedule)

    assert len(swaps) == 1
    assert all(swap.pos0[0] != swap.pos1[0] for swap in swaps[0])


def test_synthesize_swaps_positions_remain_consistent_across_timesteps() -> (
    None
):
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    schedule = [
        {qpu0: {0, 1}, qpu1: {2, 3}},
        {qpu0: {1, 2}, qpu1: {0, 3}},
        {qpu0: {0, 1}, qpu1: {2, 3}},
    ]

    swaps = synthesize_state_teleportation_swaps(schedule)

    assert len(swaps) == 2

    current_pos_by_qubit = {
        0: (0, 0),
        1: (0, 1),
        2: (1, 0),
        3: (1, 1),
    }
    for timestep_swaps in swaps:
        for swap in timestep_swaps:
            assert swap.pos0 == current_pos_by_qubit[swap.q0]
            assert swap.pos1 == current_pos_by_qubit[swap.q1]
            current_pos_by_qubit[swap.q0], current_pos_by_qubit[swap.q1] = (
                current_pos_by_qubit[swap.q1],
                current_pos_by_qubit[swap.q0],
            )
