# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from memq_dqc.circuit import Circuit, build_circuit
from memq_dqc.preprocessing.qasm.io import load_qasm_program


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
