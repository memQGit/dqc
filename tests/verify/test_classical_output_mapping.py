# Copyright 2026 memQ Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from pathlib import Path

import pytest
from qiskit import ClassicalRegister, QuantumCircuit, QuantumRegister

from memq_dqc.verify import verify_distributed_circuit
from memq_dqc.verify.verify import _exact_classical_distribution, get_counts


@pytest.mark.parametrize(
    ("first_width", "first_bit", "second_width", "second_bit", "one", "equal"),
    [
        pytest.param(3, 0, 3, 2, True, False, id="different-destinations"),
        pytest.param(3, 0, 3, 2, False, True, id="same-all-zero-output"),
        pytest.param(1, 0, 3, 0, False, False, id="different-register-widths"),
    ],
)
def test_statevector_compares_complete_classical_output(
    tmp_path: Path,
    first_width: int,
    first_bit: int,
    second_width: int,
    second_bit: int,
    one: bool,
    equal: bool,
) -> None:
    paths = [tmp_path / "original.qasm", tmp_path / "distributed.qasm"]
    for path, width, bit in zip(
        paths,
        (first_width, second_width),
        (first_bit, second_bit),
        strict=True,
    ):
        gate = "x q[0];\n" if one else ""
        path.write_text(
            'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
            f"qubit[1] q;\nbit[{width}] result;\n{gate}"
            f"result[{bit}] = measure q[0];\n",
            encoding="utf-8",
        )

    assert (
        verify_distributed_circuit(*map(str, paths), method="statevector")
        is equal
    )


def test_classical_positions_span_registers_in_global_bit_order() -> None:
    qubits = QuantumRegister(3, "q")
    low = ClassicalRegister(2, "low")
    high = ClassicalRegister(3, "high")
    circuit = QuantumCircuit(qubits, low, high)
    circuit.x(0)
    circuit.x(1)
    circuit.measure(2, high[2])
    circuit.measure(0, high[0])
    circuit.measure(1, low[0])

    assert get_counts(circuit, shots=32) == {"001 01": 32}
    assert _exact_classical_distribution(circuit) == {"00101": 1.0}


def test_repeated_qubit_readout_keeps_sparse_outputs_correlated() -> None:
    circuit = QuantumCircuit(1, 130)
    circuit.h(0)
    circuit.measure(0, 129)
    circuit.measure(0, 0)

    expected = {"0" * 130: 0.5, "1" + "0" * 128 + "1": 0.5}
    assert _exact_classical_distribution(circuit) == pytest.approx(expected)


def test_last_measurement_to_a_classical_bit_wins() -> None:
    circuit = QuantumCircuit(2, 3)
    circuit.h(0)
    circuit.x(1)
    circuit.measure(0, 2)
    circuit.measure(1, 2)
    circuit.measure(0, 0)

    expected = {"100": 0.5, "101": 0.5}
    assert _exact_classical_distribution(circuit) == pytest.approx(expected)


def test_wire_terminal_measurement_can_precede_disjoint_gates() -> None:
    circuit = QuantumCircuit(2, 3)
    circuit.x(0)
    circuit.measure(0, 2)
    circuit.x(1)
    circuit.measure(1, 0)

    assert _exact_classical_distribution(circuit) == {"101": 1.0}
