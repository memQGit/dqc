# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import logging
from pathlib import Path
from typing import Any, cast

import openqasm3
import pytest
from qiskit import QuantumCircuit

from memq_dqc.verify import (
    manual_cost_verification,
    verify_distributed_circuit,
)
from memq_dqc.verify import verify as verify_module
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


def test_dist_to_mono_circuit_drops_catent_disent_with_comm_qubits(
    tmp_path: Path,
) -> None:
    dist_qasm = """OPENQASM 3.0;
include "builder/distgates.inc";
qubit[2] q0;
qubit[2] q1;
qubit[1] c0;
qubit[1] c1;
catent q0[0], q1[1], c0[0], c1[0];
rcx q0[0], q1[1], c0[0], c1[0];
catdisent q0[0], q1[1], c0[0], c1[0];
"""
    dist_path = tmp_path / "dist_catent_comm.qasm"
    dist_path.write_text(dist_qasm, encoding="utf-8")

    mono_qasm = dist_to_mono_circuit(str(dist_path))
    mono_prog = openqasm3.parser.parse(mono_qasm)
    gates = [
        stmt
        for stmt in mono_prog.statements
        if isinstance(stmt, openqasm3.ast.QuantumGate)
    ]

    assert [gate.name.name for gate in gates] == ["cx"]
    assert len(gates[0].qubits) == 2


def test_dist_to_mono_circuit_drops_catent_disent_without_comm_qubits(
    tmp_path: Path,
) -> None:
    # Older / alternate output emits catent/catdisent with data operands
    # only, so name-based removal (not the comm-qubit heuristic) must catch
    # them.
    dist_qasm = """OPENQASM 3.0;
include "builder/distgates.inc";
qubit[2] q0;
qubit[2] q1;
catent q0[0], q1[1];
rcx q0[0], q1[1];
catdisent q0[0], q1[1];
"""
    dist_path = tmp_path / "dist_catent_no_comm.qasm"
    dist_path.write_text(dist_qasm, encoding="utf-8")

    mono_qasm = dist_to_mono_circuit(str(dist_path))
    mono_prog = openqasm3.parser.parse(mono_qasm)
    gate_names = [
        stmt.name.name
        for stmt in mono_prog.statements
        if isinstance(stmt, openqasm3.ast.QuantumGate)
    ]

    assert gate_names == ["cx"]
    assert "catent" not in mono_qasm
    assert "catdisent" not in mono_qasm
    assert "distgates.inc" not in mono_qasm


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


def test_verify_distributed_circuit_quiet_emits_no_logs(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(verify_module.qiskit.qasm3, "load", lambda _: object())
    monkeypatch.setattr(
        verify_module.qiskit.qasm3, "loads", lambda _: object()
    )
    monkeypatch.setattr(
        verify_module, "dist_to_mono_circuit", lambda _: "OPENQASM 3.0;"
    )
    counts = iter([{"00": 10}, {"00": 10}])
    monkeypatch.setattr(
        verify_module,
        "get_counts",
        lambda _circuit, *, shots: next(counts),
    )
    monkeypatch.setattr(
        verify_module, "hellinger_fidelity", lambda _orig, _mono: 1.0
    )

    caplog.set_level(logging.DEBUG, logger="memq_dqc")
    assert verify_distributed_circuit(
        "orig.qasm", "dist.qasm", method="sampling", shots=10
    )

    records = [
        record
        for record in caplog.records
        if record.name.startswith("memq_dqc")
    ]
    assert records == []


def test_verify_distributed_circuit_info_logs_success(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(verify_module.qiskit.qasm3, "load", lambda _: object())
    monkeypatch.setattr(
        verify_module.qiskit.qasm3, "loads", lambda _: object()
    )
    monkeypatch.setattr(
        verify_module, "dist_to_mono_circuit", lambda _: "OPENQASM 3.0;"
    )
    counts = iter([{"00": 10}, {"00": 10}])
    monkeypatch.setattr(
        verify_module,
        "get_counts",
        lambda _circuit, *, shots: next(counts),
    )
    monkeypatch.setattr(
        verify_module, "hellinger_fidelity", lambda _orig, _mono: 0.95
    )

    caplog.set_level(logging.DEBUG, logger="memq_dqc")
    assert verify_distributed_circuit(
        "orig.qasm",
        "dist.qasm",
        method="sampling",
        shots=10,
        fidelity_threshold=0.9,
        verbosity="info",
    )

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("memq_dqc")
    ]
    assert any(
        "Starting distributed circuit verification: method=sampling "
        "shots=10 fidelity_threshold=0.900." in msg
        for msg in messages
    )
    assert any("Verification succeeded in" in msg for msg in messages)


def test_verify_distributed_circuit_debug_logs_failure_details(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(verify_module.qiskit.qasm3, "load", lambda _: object())
    monkeypatch.setattr(
        verify_module.qiskit.qasm3, "loads", lambda _: object()
    )
    monkeypatch.setattr(
        verify_module, "dist_to_mono_circuit", lambda _: "OPENQASM 3.0;"
    )
    counts = iter([{"00": 6, "11": 4}, {"00": 2, "11": 8}])
    monkeypatch.setattr(
        verify_module,
        "get_counts",
        lambda _circuit, *, shots: next(counts),
    )
    monkeypatch.setattr(
        verify_module, "hellinger_fidelity", lambda _orig, _mono: 0.5
    )

    caplog.set_level(logging.DEBUG, logger="memq_dqc")
    assert not verify_distributed_circuit(
        "orig.qasm",
        "dist.qasm",
        method="sampling",
        shots=10,
        fidelity_threshold=0.9,
        verbosity="debug",
    )

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("memq_dqc")
    ]
    assert any("Loaded original circuit in" in msg for msg in messages)
    assert any("Computed fidelity in" in msg for msg in messages)
    assert any("Verification failed in" in msg for msg in messages)


def test_verify_distributed_circuit_rejects_invalid_verbosity() -> None:
    invalid_verbosity = cast(Any, "loud")
    with pytest.raises(ValueError, match="Unsupported verbosity"):
        verify_distributed_circuit(
            "orig.qasm",
            "dist.qasm",
            method="sampling",
            verbosity=invalid_verbosity,
        )


def test_verify_distributed_circuit_rejects_invalid_method() -> None:
    invalid_method = cast(Any, "exact")
    with pytest.raises(ValueError, match="Unsupported method"):
        verify_distributed_circuit(
            "orig.qasm",
            "dist.qasm",
            method=invalid_method,
        )


def _measured_circuit(
    x_qubits: tuple[int, ...],
    clbit_to_qubit: tuple[int, ...],
) -> QuantumCircuit:
    """Build a deterministic 2-qubit circuit with a custom measurement map.

    Applies ``x`` to each qubit in ``x_qubits`` (producing a computational
    basis state) then measures so that classical bit ``c`` reads qubit
    ``clbit_to_qubit[c]``.
    """
    qc = QuantumCircuit(2, 2)
    for qubit in x_qubits:
        qc.x(qubit)
    for clbit, qubit in enumerate(clbit_to_qubit):
        qc.measure(qubit, clbit)
    return qc


def _patch_loaded_circuits(
    monkeypatch: pytest.MonkeyPatch,
    original: QuantumCircuit,
    mono: QuantumCircuit,
) -> None:
    """Make the loaders return the given circuits instead of reading files."""
    monkeypatch.setattr(
        verify_module.qiskit.qasm3, "load", lambda _path: original
    )
    monkeypatch.setattr(verify_module, "dist_to_mono_circuit", lambda _p: "")
    monkeypatch.setattr(verify_module.qiskit.qasm3, "loads", lambda _src: mono)


def test_statevector_method_is_invariant_to_qubit_relabeling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Same classical distribution, but the data qubit is relabeled and the
    # measurement mapping compensates (mimics QPU repartitioning).
    original = _measured_circuit(x_qubits=(0,), clbit_to_qubit=(0, 1))
    relabeled = _measured_circuit(x_qubits=(1,), clbit_to_qubit=(1, 0))

    _patch_loaded_circuits(monkeypatch, original, relabeled)

    assert verify_distributed_circuit(
        "orig.qasm", "dist.qasm", method="statevector"
    )


def test_statevector_method_detects_inequivalent_circuits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _measured_circuit(x_qubits=(0,), clbit_to_qubit=(0, 1))
    wrong = _measured_circuit(x_qubits=(0, 1), clbit_to_qubit=(0, 1))

    _patch_loaded_circuits(monkeypatch, original, wrong)

    assert not verify_distributed_circuit(
        "orig.qasm", "dist.qasm", method="statevector"
    )


def test_statevector_method_rejects_circuit_exceeding_max_qubits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = _measured_circuit(x_qubits=(0,), clbit_to_qubit=(0, 1))
    mono = _measured_circuit(x_qubits=(0,), clbit_to_qubit=(0, 1))

    _patch_loaded_circuits(monkeypatch, original, mono)

    with pytest.raises(ValueError, match="exceeding max_qubits"):
        verify_distributed_circuit(
            "orig.qasm", "dist.qasm", method="statevector", max_qubits=1
        )


def test_statevector_method_requires_measurements(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = QuantumCircuit(2)
    original.h(0)
    mono = original.copy()

    _patch_loaded_circuits(monkeypatch, original, mono)

    with pytest.raises(ValueError, match="requires the circuit to contain"):
        verify_distributed_circuit(
            "orig.qasm", "dist.qasm", method="statevector"
        )
