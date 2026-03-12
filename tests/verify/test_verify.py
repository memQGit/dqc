# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

import openqasm3

# TODO: add back - from memq_dqc.verify import verify_distributed_circuit
from memq_dqc.verify import manual_cost_verification
from memq_dqc.verify.verify import dist_to_mono_circuit

# TODO: need more tests!


def test_dist_to_mono_circuit_removes_comm_qubits_for_remote_gates(
    tmp_path: Path,
) -> None:
    dist_qasm = """OPENQASM 3.0;
include "builder/distgates.inc";
qubit[2] q0;
qubit[2] q1;
qubit[1] c0;
qubit[1] c1;
rcx q0[0], q1[1], c0[0], c1[0];
"""
    dist_path = tmp_path / "dist_remote4q.qasm"
    dist_path.write_text(dist_qasm, encoding="utf-8")

    mono_qasm = dist_to_mono_circuit(str(dist_path))
    mono_prog = openqasm3.parser.parse(mono_qasm)
    gate_stmt = next(
        stmt
        for stmt in mono_prog.statements
        if isinstance(stmt, openqasm3.ast.QuantumGate)
    )

    assert gate_stmt.name.name == "cx"
    assert len(gate_stmt.qubits) == 2
    assert all(
        not qubit.name.name.startswith("c")
        if isinstance(qubit, openqasm3.ast.IndexedIdentifier)
        else not qubit.name.startswith("c")
        for qubit in gate_stmt.qubits
    )
    assert all(
        not (
            isinstance(stmt, openqasm3.ast.QubitDeclaration)
            and stmt.qubit.name.startswith("c")
        )
        for stmt in mono_prog.statements
    )


def test_dist_to_mono_circuit_converts_rcry_to_cry(
    tmp_path: Path,
) -> None:
    dist_qasm = """OPENQASM 3.0;
include "builder/distgates.inc";
qubit[2] q0;
qubit[2] q1;
qubit[1] c0;
qubit[1] c1;
rcry(pi / 8) q0[0], q1[1], c0[0], c1[0];
"""
    dist_path = tmp_path / "dist_rcry.qasm"
    dist_path.write_text(dist_qasm, encoding="utf-8")

    mono_qasm = dist_to_mono_circuit(str(dist_path))
    mono_prog = openqasm3.parser.parse(mono_qasm)
    gate_stmt = next(
        stmt
        for stmt in mono_prog.statements
        if isinstance(stmt, openqasm3.ast.QuantumGate)
    )

    assert gate_stmt.name.name == "cry"
    assert len(gate_stmt.qubits) == 2
    assert all(
        not qubit.name.name.startswith("c")
        if isinstance(qubit, openqasm3.ast.IndexedIdentifier)
        else not qubit.name.startswith("c")
        for qubit in gate_stmt.qubits
    )


def test_manual_cost_verification_counts_remote_operations() -> None:
    qasm = """OPENQASM 3.0;
include "builder/distgates.inc";
qubit[2] q0;
qubit[2] q1;
qubit[1] c0;
qubit[1] c1;
h q0[0];
rcx q0[0], q1[1], c0[0], c1[0];
rcp(pi / 4) q0[0], q1[1], c0[0], c1[0];
rcry(pi / 8) q0[0], q1[1], c0[0], c1[0];
rcz q0[1], q1[0], c0[0], c1[0];
rswap q0[0], q1[0], c0[0], c1[0];
"""
    assert manual_cost_verification(qasm) == 6


def test_manual_cost_verification_returns_zero_for_no_remote_ops() -> None:
    qasm = """OPENQASM 3.0;
include "stdgates.inc";
qubit[2] q;
h q[0];
cx q[0], q[1];
"""
    assert manual_cost_verification(qasm) == 0
