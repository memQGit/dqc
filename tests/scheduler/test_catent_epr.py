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
from openqasm3 import ast

from memq_dqc import Compiler
from memq_dqc.assets import network_path
from memq_dqc.circuit import DistributedCircuit, Op
from memq_dqc.circuit.dag import DistributedCircuitDAG
from memq_dqc.partition import QPU, BasePartitioner
from memq_dqc.preprocessing.qasm.types import CircuitQubit
from memq_dqc.scheduler import ScheduledOperation, Scheduler, fifo_schedule
from memq_dqc.scheduler.schedule import _remote_ops_with_catent_setup

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


class _QftPartitioner(BasePartitioner):
    def run(self):
        self.schedule = [{QPU(id=0): {0, 3}, QPU(id=1): {1, 2}}]
        self.windows = [self.circuit.mono.ops]


@pytest.mark.parametrize(
    "group_gates, expected_pairs", [(True, 3), (False, 4)]
)
@pytest.mark.parametrize("ebit_assignment", [True, False])
@pytest.mark.parametrize("algo", ["fifo", "des_link_fifo"])
def test_qft_epr_events_match_compile_cost(
    tmp_path: Path, group_gates, expected_pairs, ebit_assignment, algo
):
    # Issue #130: the default split groups the final two remote CP gates.
    qasm_path = tmp_path / "qft4.qasm"
    qasm_path.write_text(_QFT4, encoding="utf-8")
    compiler = Compiler(
        qasm_path, network_path("10_qubits/n2_pair_a2a"), algo=_QftPartitioner
    )
    compiler.compile(group_gates=group_gates, ebit_assignment=ebit_assignment)
    scheduler = (
        Scheduler(compiler)
        if algo == "fifo"
        else Scheduler(compiler, algo=algo, algo_kwargs={"seed": 0})
    )
    scheduler.run()

    assert scheduler.schedule is not None
    events = scheduler.schedule.operations
    assert sum(event.name == "catent" for event in events) == expected_pairs
    assert sum(event.name == "epr" for event in events) == expected_pairs
    assert compiler.cost == expected_pairs
    assert sum(event.name == "rcp" for event in events) == 4


def _op(op_id, name, registers):
    return Op(
        op_id=op_id,
        statement_id=op_id,
        name=name,
        is_remote=name in {"rcx", "rswap"},
        qubits=tuple(
            CircuitQubit(register_name=register, index=0)
            for register in registers
        ),
        node=ast.QuantumGate(
            modifiers=[], name=ast.Identifier(name), arguments=[], qubits=[]
        ),
    )


def _circuit(ops):
    return DistributedCircuit(
        program=ast.Program(statements=[], version="3.0"),
        statements=[],
        ops=ops,
        num_two_qubit_gates=sum(op.is_remote for op in ops),
        num_remote_gates=sum(op.is_remote for op in ops),
        num_local_swaps_added=0,
        dag=DistributedCircuitDAG(ops),
    )


def test_catent_setup_membership_follows_brackets_not_predecessors():
    qubits = ["q0", "q1", "c0", "c1"]
    circuit = _circuit(
        [
            _op(0, "rcx", qubits),
            _op(1, "catent", qubits),
            _op(2, "rcx", qubits),
            _op(3, "rz", ["q1"]),
            _op(4, "rcx", qubits),
            # Remote swaps require independent teleportation EPRs even inside
            # a cat-entanglement region, just as in the annotated DAG.
            _op(5, "rswap", ["q2", "q3", "c2", "c3", "c4", "c5"]),
            _op(6, "catdisent", qubits),
            _op(7, "rcx", qubits),
            _op(8, "catent", qubits),
            _op(9, "rcx", qubits),
            _op(10, "catdisent", qubits),
        ]
    )

    assert _remote_ops_with_catent_setup(circuit) == {2, 4, 9}


def test_fifo_group_reuses_epr_across_local_gate_then_releases_pair():
    qubits = ["q0", "q1", "c0", "c1"]
    circuit = _circuit(
        [
            _op(0, "catent", qubits),
            _op(1, "rcx", qubits),
            _op(2, "rz", ["q1"]),
            _op(3, "rcx", qubits),
            _op(4, "catdisent", qubits),
            _op(5, "rcx", qubits),
        ]
    )

    schedule = fifo_schedule(circuit)
    eprs = [event for event in schedule.operations if event.name == "epr"]
    operations = {
        event.op_id: event
        for event in schedule.operations
        if isinstance(event, ScheduledOperation)
    }

    assert len(eprs) == 2  # One for the group, one for the ungrouped gate.
    assert operations[3].start_time == operations[2].end_time
    assert eprs[1].start_time >= operations[4].end_time
    assert operations[5].start_time >= eprs[1].end_time
