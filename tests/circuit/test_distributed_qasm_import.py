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

import json
from importlib.resources import files

import openqasm3
import pytest
from qiskit import qasm3

from memq_dqc import Compiler, Scheduler
from memq_dqc.assets import network_path
from memq_dqc.partition import QPU, BasePartitioner

_QFT4 = """OPENQASM 3.0;
include "stdgates.inc";
qubit[4] q;
bit[4] c;
h q[3];
cp(1.5707963267948966) q[2], q[3];
cp(0.7853981633974483) q[1], q[3];
cp(0.39269908169872414) q[0], q[3];
h q[2];
cp(1.5707963267948966) q[1], q[2];
cp(0.7853981633974483) q[0], q[2];
h q[1];
cp(1.5707963267948966) q[0], q[1];
h q[0];
swap q[0], q[3];
swap q[1], q[2];
c[0] = measure q[0];
c[1] = measure q[1];
c[2] = measure q[2];
c[3] = measure q[3];
"""


class _FixedPartitioner(BasePartitioner):
    def run(self):
        self.schedule = [{QPU(id=0): {0, 3}, QPU(id=1): {1, 2}}]
        self.windows = [self.circuit.mono.ops]


def _distgates():
    return (files("memq_dqc") / "builder" / "distgates.inc").read_text()


def _inline_distgates(source):
    # Qiskit's importer only resolves stdgates.inc. Expand the package's
    # include in-place so this also tests emitted declaration order.
    return source.replace(
        'include "builder/distgates.inc";',
        _distgates(),
    )


def test_distgates_parameter_definitions_parse_and_import():
    source = (
        'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
        + _distgates()
        + "\nqubit[4] q;\n"
        + "rcp(0.5) q[0], q[1], q[2], q[3];\n"
        + "rcry(0.75) q[0], q[1], q[2], q[3];\n"
    )
    openqasm3.parse(source)
    circuit = qasm3.loads(source)
    assert [instruction.operation.name for instruction in circuit.data] == [
        "rcp",
        "rcry",
    ]
    assert [instruction.operation.params for instruction in circuit.data] == [
        [0.5],
        [0.75],
    ]


@pytest.mark.parametrize("indices", [(0, 1), (5, 6), (7, 19)])
@pytest.mark.parametrize("group_gates", [False, True])
def test_qft_output_imports_with_physical_comm_indices(
    tmp_path, indices, group_gates
):
    network = json.loads(network_path("10_qubits/n2_pair_a2a").read_text())
    for name, qubit in network["qubits"].items():
        if qubit["type"] == "communication":
            qubit["localIndex"] = indices[int(name.rsplit("_", 1)[1])]
    path = tmp_path / "network.json"
    path.write_text(json.dumps(network))
    compiler = Compiler(_QFT4, path, algo=_FixedPartitioner)
    compiler.compile(group_gates=group_gates)

    includes = [
        node.filename
        for node in compiler.distributed_circuit.program.statements
        if isinstance(node, openqasm3.ast.Include)
    ]
    assert includes == ["stdgates.inc", "builder/distgates.inc"]
    imported = qasm3.loads(_inline_distgates(compiler.distributed_qasm))
    sizes = {register.name: register.size for register in imported.qregs}
    assert sizes["c0"] == sizes["c1"] == max(indices) + 1
    assert compiler.network.num_comm_qubits == 4

    remote_ops = [
        op for op in compiler.distributed_circuit.ops if op.is_remote
    ]
    assert remote_ops
    used_comm_indices = set()
    for op in remote_ops:
        pairs = op.ebit_pairs
        assert pairs is not None
        for pair in pairs:
            assert compiler.network.graph.has_edge(*pair)
            for qubit in pair:
                assert qubit.qubit_id in indices
                used_comm_indices.add(qubit.qubit_id)
    assert used_comm_indices == set(indices)

    scheduler = Scheduler(compiler)
    scheduler.run()
    assert scheduler.schedule is not None
    assert scheduler.schedule.makespan > 0


@pytest.mark.parametrize("gate", ["cx", "cp(0.5)", "cry(0.75)", "cz", "swap"])
def test_each_remote_gate_imports(gate):
    source = (
        'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
        + "qubit[4] q;\n"
        + f"{gate} q[0], q[1];\n"
    )
    compiler = Compiler(
        source,
        network_path("10_qubits/n2_pair_a2a"),
        algo=_FixedPartitioner,
    )
    compiler.compile()
    imported = qasm3.loads(_inline_distgates(compiler.distributed_qasm))
    name = "r" + gate.split("(")[0]
    remote = [
        instruction.operation
        for instruction in imported.data
        if instruction.operation.name == name
    ]
    assert len(remote) == 1
    assert remote[0].num_qubits == (6 if gate == "swap" else 4)
