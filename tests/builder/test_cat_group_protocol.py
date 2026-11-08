# Copyright 2026 memQ Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Exercise the cat protocol, rather than replacing remote gates by local ones."""

import numpy as np
import pytest
from openqasm3 import ast
from qiskit import QuantumCircuit
from qiskit.quantum_info import DensityMatrix, partial_trace

from memq_dqc import Compiler
from memq_dqc.partition import QPU, BasePartitioner
from memq_dqc.preprocessing.qasm.types import CircuitQubit


class _FixedPartitioner(BasePartitioner):
    def run(self):
        self.schedule = [{QPU(id=0): {0, 1}, QPU(id=1): {2, 3}}]
        self.windows = [self.circuit.mono.ops]


_INTERLUDES = [
    pytest.param("x q[0];", "x", (0,), (), 2, id="x-control"),
    pytest.param("y q[0];", "y", (0,), (), 2, id="y-control"),
    pytest.param("h q[0];", "h", (0,), (), 2, id="h-control"),
    pytest.param("rx(0.3) q[0];", "rx", (0,), (0.3,), 2, id="rx-control"),
    pytest.param("swap q[0], q[1];", "swap", (0, 1), (), 2, id="swap-first"),
    pytest.param("swap q[1], q[0];", "swap", (1, 0), (), 2, id="swap-second"),
    pytest.param("cx q[1], q[0];", "cx", (1, 0), (), 2, id="cx-target"),
    pytest.param("rz(0.3) q[0];", "rz", (0,), (0.3,), 1, id="rz-control"),
    pytest.param("cx q[0], q[1];", "cx", (0, 1), (), 1, id="cx-control"),
    pytest.param("cz q[1], q[0];", "cz", (1, 0), (), 1, id="cz-reversed"),
    pytest.param("x q[2];", "x", (2,), (), 1, id="x-target"),
]


def _compile_interlude(
    tmp_path, network_path, interlude, prepare, remote_gate="cx", **options
):
    source = tmp_path / "cat_group.qasm"
    # Prepare nontrivial phases and entanglement as well as the issue's |0000>.
    prefix = (
        "h q[0];\ns q[0];\nry(0.4) q[1];\ncx q[0], q[1];\n"
        "h q[2];\ns q[2];\nry(0.7) q[3];\n"
        if prepare
        else ""
    )
    gate = remote_gate + ("(0.3)" if remote_gate in {"cp", "cry"} else "")
    source.write_text(
        'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[4] q;\n'
        + prefix
        + f"{gate} q[0], q[2];\n{interlude}\n{gate} q[0], q[3];\n",
        encoding="utf-8",
    )
    compiler = Compiler(source, network_path, algo=_FixedPartitioner)
    compiler.compile(**options)
    return compiler


def _protocol_data_state(compiler):
    # Map the emitted physical operands directly, independent of QASM register
    # declaration sizes. These tests check the protocol, not serialization.
    indices = {
        CircuitQubit("q0", 0): 0,
        CircuitQubit("q0", 1): 1,
        CircuitQubit("q1", 0): 2,
        CircuitQubit("q1", 1): 3,
    }
    ops = compiler.distributed_circuit.ops
    for op in ops:
        for qubit in op.qubits:
            if qubit not in indices:
                indices[qubit] = len(indices)
    circuit = QuantumCircuit(len(indices))
    for op in ops:
        qubits = [indices[qubit] for qubit in op.qubits]
        assert isinstance(op.node, ast.QuantumGate)
        arguments = []
        for argument in op.node.arguments:
            assert isinstance(argument, (ast.FloatLiteral, ast.IntegerLiteral))
            arguments.append(argument.value)
        if op.name == "catent":
            control, _, local_comm, remote_comm = qubits
            circuit.reset([local_comm, remote_comm])
            circuit.h(local_comm)
            circuit.cx(local_comm, remote_comm)
            circuit.cx(control, local_comm)
            # Coherent feed-forward followed by discarding the measured qubit
            # is the exact channel of measure(local_comm); if 1: X(remote_comm).
            circuit.cx(local_comm, remote_comm)
            circuit.reset(local_comm)
        elif op.name == "catdisent":
            control, _, _, remote_comm = qubits
            circuit.h(remote_comm)
            # Likewise, measure(remote_comm); if 1: Z(control), then discard.
            circuit.cz(remote_comm, control)
            circuit.reset(remote_comm)
        elif op.name in {"rcx", "rcp", "rcry", "rcz"}:
            getattr(circuit, op.name[1:])(*arguments, qubits[3], qubits[1])
        else:
            getattr(circuit, op.name)(*arguments, *qubits)

    return partial_trace(
        DensityMatrix.from_instruction(circuit), list(range(4, len(indices)))
    )


@pytest.mark.parametrize("interlude,name,qubits,arguments,groups", _INTERLUDES)
@pytest.mark.parametrize(
    "prepare", [False, True], ids=["zero", "superposition"]
)
@pytest.mark.parametrize(
    "group_gates", [True, False], ids=["grouped", "ungrouped"]
)
@pytest.mark.parametrize("remote_gate", ["cx", "cp", "cry", "cz"])
def test_cat_protocol_preserves_data_state(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    interlude,
    name,
    qubits,
    arguments,
    groups,
    prepare,
    group_gates,
    remote_gate,
):
    compiler = _compile_interlude(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        interlude,
        prepare,
        remote_gate=remote_gate,
        group_gates=group_gates,
    )
    expected = QuantumCircuit(4)
    if prepare:
        expected.h(0)
        expected.s(0)
        expected.ry(0.4, 1)
        expected.cx(0, 1)
        expected.h(2)
        expected.s(2)
        expected.ry(0.7, 3)
    remote_arguments = (0.3,) if remote_gate in {"cp", "cry"} else ()
    getattr(expected, remote_gate)(*remote_arguments, 0, 2)
    getattr(expected, name)(*arguments, *qubits)
    getattr(expected, remote_gate)(*remote_arguments, 0, 3)

    np.testing.assert_allclose(
        _protocol_data_state(compiler).data,
        DensityMatrix.from_instruction(expected).data,
        atol=1e-12,
    )
    names = [op.name for op in compiler.distributed_circuit.ops]
    assert names.count("catent") == (groups if group_gates else 2)
    assert names.count("catdisent") == names.count("catent")


@pytest.mark.parametrize("ebit_assignment", [True, False])
@pytest.mark.parametrize(
    "interlude", ["x q[0];", "y q[0];", "swap q[0], q[1];"]
)
def test_control_change_is_outside_cat_region(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    ebit_assignment,
    interlude,
):
    compiler = _compile_interlude(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        interlude,
        False,
        ebit_assignment=ebit_assignment,
    )

    assert [op.name for op in compiler.distributed_circuit.ops] == [
        "catent",
        "rcx",
        "catdisent",
        interlude.split()[0],
        "catent",
        "rcx",
        "catdisent",
    ]
    assert compiler.cost == 2.0
