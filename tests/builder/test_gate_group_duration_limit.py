# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Tests for the EPR-lifetime gate-group duration cap."""

from openqasm3 import ast

from xdqc.builder.extract_utils import (
    GroupDurationLimit,
    _identify_existing_gate_groups,
)
from xdqc.circuit.op import Op
from xdqc.preprocessing.qasm.types import CircuitQubit


def _two_qubit_op(op_id: int, control: int, target: int) -> Op:
    return Op(
        op_id=op_id,
        statement_id=op_id,
        name="cx",
        is_remote=False,
        qubits=(
            CircuitQubit(register_name="q", index=control),
            CircuitQubit(register_name="q", index=target),
        ),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("cx"),
            arguments=[],
            qubits=[],
        ),
    )


def _one_qubit_op(op_id: int, qubit: int) -> Op:
    return Op(
        op_id=op_id,
        statement_id=op_id,
        name="rz",
        is_remote=False,
        qubits=(CircuitQubit(register_name="q", index=qubit),),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("rz"),
            arguments=[],
            qubits=[],
        ),
    )


def test_group_duration_limit_allows_within_budget():
    limit = GroupDurationLimit(
        gate_duration_budget=2.0,
        one_qubit_gate_time=1.0,
        two_qubit_gate_time=0.8,
    )
    seed = _two_qubit_op(0, 0, 1)
    nxt = _two_qubit_op(1, 0, 2)

    assert limit.op_duration(seed) == 0.8
    assert limit.op_duration(_one_qubit_op(2, 2)) == 1.0
    # 0.8 + 0.8 = 1.6 <= 2.0 fits; 0.8 + 1.6 = 2.4 > 2.0 does not.
    assert limit.allows(0.8, [nxt]) is True
    assert limit.allows(0.8, [nxt, _two_qubit_op(3, 0, 3)]) is False


def test_duration_cap_splits_shared_control_chain():
    # Four shared-control two-qubit gates that would otherwise group together.
    gate_ops = [
        _two_qubit_op(0, 0, 1),
        _two_qubit_op(1, 0, 2),
        _two_qubit_op(2, 0, 3),
        _two_qubit_op(3, 0, 4),
    ]
    # Budget fits two 0.8 gates per group (1.6) but not three (2.4).
    limit = GroupDurationLimit(
        gate_duration_budget=1.7,
        one_qubit_gate_time=1.0,
        two_qubit_gate_time=0.8,
    )

    _, group_indices = _identify_existing_gate_groups(
        gate_ops,
        False,
        None,
        limit,
    )

    # Two groups of two gates each.
    assert sorted(group_indices) == [(0, 2), (2, 4)]


def test_duration_cap_forces_singletons_when_budget_below_one_gate():
    gate_ops = [
        _two_qubit_op(0, 0, 1),
        _two_qubit_op(1, 0, 2),
        _two_qubit_op(2, 0, 3),
    ]
    # Budget below one extra gate: the seed is always kept, nothing added.
    limit = GroupDurationLimit(
        gate_duration_budget=0.5,
        one_qubit_gate_time=1.0,
        two_qubit_gate_time=0.8,
    )

    _, group_indices = _identify_existing_gate_groups(
        gate_ops,
        False,
        None,
        limit,
    )

    assert sorted(group_indices) == [(0, 1), (1, 2), (2, 3)]


def test_duration_cap_counts_interleaved_target_one_qubit_gates():
    # Shared-control gates with a target-qubit 1q gate folded into the group.
    gate_ops = [
        _two_qubit_op(0, 0, 1),
        _one_qubit_op(1, 1),
        _two_qubit_op(2, 0, 2),
        _two_qubit_op(3, 0, 3),
    ]
    # seed 0.8; + rz(1.0) + cx(0.8) = 2.6 <= 2.7 fits; next cx would be 3.4.
    limit = GroupDurationLimit(
        gate_duration_budget=2.7,
        one_qubit_gate_time=1.0,
        two_qubit_gate_time=0.8,
    )

    reordered_ops, group_indices = _identify_existing_gate_groups(
        gate_ops,
        False,
        None,
        limit,
    )

    # First group holds cx, rz, cx (indices 0..3); the last cx is its own.
    assert (0, 3) in group_indices
    assert reordered_ops[0].op_id == 0
    assert [op.name for op in reordered_ops[0:3]] == ["cx", "rz", "cx"]
