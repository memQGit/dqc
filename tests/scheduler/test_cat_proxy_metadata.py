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
"""Late-bound cat-proxy metadata through scheduling and serialization."""

import json
from dataclasses import replace

import numpy as np
import pytest
from openqasm3 import ast
from qiskit import QuantumCircuit, qasm3
from qiskit.quantum_info import DensityMatrix, partial_trace

from memq_dqc import Compiler
from memq_dqc.partition import QPU, BasePartitioner
from memq_dqc.scheduler import (
    EntanglementGeneration,
    ScheduledOperation,
    Scheduler,
    SchedulerHardwareProfile,
    SchedulingCompileOptions,
    build_scheduling_instance,
    schedule_to_json,
    scheduling_instance_from_json,
    scheduling_instance_to_json,
    validate_scheduling_instance,
)
from memq_dqc.scheduler.schedule import _bound_cat_group_qubits


class _FixedPartitioner(BasePartitioner):
    def run(self):
        self.schedule = [{QPU(id=0): {0, 1}, QPU(id=1): {2, 3}}]
        self.windows = [self.circuit.mono.ops]


class _ReversePartitioner(BasePartitioner):
    def run(self):
        self.schedule = [{QPU(id=0): {2, 3}, QPU(id=1): {0, 1}}]
        self.windows = [self.circuit.mono.ops]


_PROFILE = SchedulerHardwareProfile(
    one_qubit_gate_time=1.0,
    two_qubit_gate_time=5.0,
    measurement_time=1.0,
    entanglement_rate=100.0,
    epr_lifetime=1000.0,
)


def _compile(
    tmp_path, network_path, gate="y", *, deferred=True, reverse=False
):
    # Duplicate the fixture's communication link so the scheduler can select
    # a different pair than the compiler's concrete first choice.
    network = json.loads(network_path.read_text())
    for qpu in (0, 1):
        old = f"c_{qpu}_0"
        new = f"c_{qpu}_1"
        qubit = dict(network["qubits"][old])
        qubit.update(
            id=new,
            localIndex=1,
            label=f"c({qpu},1)",
            remoteConnections=[f"c_{1 - qpu}_1"],
        )
        network["qubits"][new] = qubit
        network["processors"][str(qpu)]["qubits"]["communication"].append(new)
        for data in network["processors"][str(qpu)]["qubits"]["computation"]:
            network["qubits"][data]["localConnections"].append(new)
    network_file = tmp_path / "two_links.json"
    network_file.write_text(json.dumps(network), encoding="utf-8")
    expected = QuantumCircuit(4)
    expected.h(0)
    expected.s(0)
    expected.ry(0.41, 1)
    expected.cx(0, 1)
    expected.h(2)
    expected.ry(0.53, 3)
    expected.cx(0, 2)
    getattr(expected, gate)(0)
    expected.cx(0, 3)
    source = tmp_path / "proxy.qasm"
    source.write_text(qasm3.dumps(expected), encoding="utf-8")
    compiler = Compiler(
        source,
        network_file,
        algo=_ReversePartitioner if reverse else _FixedPartitioner,
    )
    compiler.compile(ebit_assignment=not deferred)
    distributed = compiler.distributed_circuit
    if deferred:
        candidates = distributed.ebit_candidates_by_op_id
        assert candidates is not None
        catent = next(op for op in distributed.ops if op.name == "catent")
        assert len(candidates[catent.op_id]) == 2
        # Leave remote-member candidate lists untouched: every member must
        # follow the opener's binding rather than independently pick a link.
        candidates[catent.op_id] = candidates[catent.op_id][1:]
    return compiler, expected


def _scheduled_data_state(compiler, schedule, *, reverse=False):
    indices = {"q0[0]": 0, "q0[1]": 1, "q1[0]": 2, "q1[1]": 3}
    if reverse:
        indices = {"q1[0]": 0, "q1[1]": 1, "q0[0]": 2, "q0[1]": 3}
    for event in schedule.operations:
        for qubit in event.qubits:
            if qubit not in indices:
                indices[qubit] = len(indices)
    circuit = QuantumCircuit(len(indices))
    source_ops = {op.op_id: op for op in compiler.distributed_circuit.ops}
    for event in sorted(
        schedule.operations, key=lambda event: event.start_time
    ):
        if isinstance(event, EntanglementGeneration):
            continue
        qubits = [indices[qubit] for qubit in event.qubits]
        if event.name == "catent":
            control, _, local, remote = qubits
            circuit.reset([local, remote])
            circuit.h(local)
            circuit.cx(local, remote)
            circuit.cx(control, local)
            circuit.cx(local, remote)
            circuit.reset(local)
        elif event.name == "catdisent":
            control, _, _, remote = qubits
            circuit.h(remote)
            circuit.cz(remote, control)
            circuit.reset(remote)
        elif event.name == "rcx":
            circuit.cx(qubits[3], qubits[1])
        else:
            op = source_ops[event.op_id]
            arguments = [argument.value for argument in op.node.arguments]
            data_qubits = [
                indices[qubit]
                for qubit in event.qubits
                if qubit not in event.cat_proxy_qubits
            ]
            getattr(circuit, event.name)(*arguments, *data_qubits)
            for proxy in event.cat_proxy_qubits:
                circuit.x(indices[proxy])
    return partial_trace(
        DensityMatrix.from_instruction(circuit), list(range(4, len(indices)))
    )


@pytest.mark.parametrize("reverse", [False, True])
@pytest.mark.parametrize("gate", ["x", "y"])
@pytest.mark.parametrize("deferred", [False, True])
@pytest.mark.parametrize(
    "algorithm",
    [
        "fifo",
        "des_link_fifo",
        "des_link_shortest_duration",
        "des_link_critical_path",
    ],
)
def test_scheduled_proxy_uses_group_selected_link(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    gate,
    deferred,
    algorithm,
    reverse,
):
    compiler, expected = _compile(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        gate,
        deferred=deferred,
        reverse=reverse,
    )
    scheduler = Scheduler(
        compiler,
        algo=algorithm,
        profile=_PROFILE,
        algo_kwargs={} if algorithm == "fifo" else {"seed": 0},
    )
    scheduler.run()
    schedule = scheduler.schedule
    assert schedule is not None
    events = [
        event
        for event in schedule.operations
        if isinstance(event, ScheduledOperation)
    ]
    assert (
        len([event for event in schedule.operations if event.name == "epr"])
        == 1
    )
    catent = next(event for event in events if event.name == "catent")
    catdisent = next(event for event in events if event.name == "catdisent")
    remotes = [event for event in events if event.name == "rcx"]
    assert catent.qubits[2:] == catdisent.qubits[2:]
    assert all(event.qubits[2:] == catent.qubits[2:] for event in remotes)
    if deferred:
        marked = next(event for event in events if event.cat_proxy_qubits)
        proxy = "c0[1]" if reverse else "c1[1]"
        root = "q1[0]" if reverse else "q0[0]"
        assert marked.cat_proxy_qubits == (proxy,)
        assert marked.qubits == (root, proxy)
        assert marked.name == gate
        assert marked.duration == 2.0
        assert remotes[0].end_time <= marked.start_time
        assert marked.end_time <= remotes[1].start_time
        exported = json.loads(schedule_to_json(schedule))
        assert exported["schema_version"] == 2
        exported_marker = next(
            event
            for event in exported["operations"]
            if event.get("cat_proxy_qubits")
        )
        assert exported_marker["cat_proxy_qubits"] == [proxy]
        assert exported_marker["name"] == gate
    else:
        assert all(not event.cat_proxy_qubits for event in events)
        assert "schema_version" not in json.loads(schedule_to_json(schedule))
    np.testing.assert_allclose(
        _scheduled_data_state(compiler, schedule, reverse=reverse).data,
        DensityMatrix.from_instruction(expected).data,
        atol=1e-12,
    )


def test_scheduling_instance_preserves_symbolic_correction(
    tmp_path, three_comp_one_comm_x2_network_path
):
    compiler, _ = _compile(tmp_path, three_comp_one_comm_x2_network_path)
    instance = build_scheduling_instance(
        compiler.distributed_circuit,
        compiler.partitioner.network,
        options=SchedulingCompileOptions(
            ebit_assignment=False, hardware_profile=_PROFILE
        ),
        compiler_version="test",
        source_fingerprint="proxy-test",
    )
    marked = next(op for op in instance.operations if op.cat_proxy_x)
    assert instance.schema_version == instance.metadata["schema_version"] == 2
    catent = next(op for op in instance.operations if op.name == "catent")
    assert marked.group_id == catent.group_id
    assert marked.duration == 2.0
    assert marked.comm_qubits == ()
    assert len(instance.epr_demands) == 1
    encoded = scheduling_instance_to_json(instance)
    restored = scheduling_instance_from_json(encoded)
    assert restored == instance
    legacy = json.loads(encoded)
    legacy["schema_version"] = 1
    with pytest.raises(ValueError, match="require schema version 2"):
        scheduling_instance_from_json(legacy)
    with pytest.raises(ValueError, match="require schema version 2"):
        scheduling_instance_to_json(replace(instance, schema_version=1))
    with pytest.raises(ValueError, match="does not match its group"):
        validate_scheduling_instance(
            replace(
                instance,
                operations=tuple(
                    replace(op, group_id=None) if op.cat_proxy_x else op
                    for op in instance.operations
                ),
            )
        )


@pytest.mark.parametrize(
    "invalid", ["name", "root", "modifier", "missing-proxy"]
)
def test_invalid_bound_correction_is_rejected(
    tmp_path, three_comp_one_comm_x2_network_path, invalid
):
    compiler, _ = _compile(tmp_path, three_comp_one_comm_x2_network_path)
    ops = compiler.distributed_circuit.ops
    marker = next(op for op in ops if op.cat_proxy_x)
    root = next(op for op in ops if op.name == "catent").qubits[0]
    comm = ("c0[1]", "c1[1]")
    if invalid == "name":
        marker = replace(marker, name="h")
    elif invalid == "root":
        marker = replace(marker, qubits=(replace(root, index=1),))
    elif invalid == "modifier":
        assert isinstance(marker.node, ast.QuantumGate)
        marker.node.modifiers = [
            ast.QuantumGateModifier(
                ast.GateModifierName.pow, ast.FloatLiteral(0.5)
            )
        ]
    else:
        comm = ()
    with pytest.raises(ValueError, match="does not match its group"):
        _bound_cat_group_qubits(marker, root, comm)


def test_correction_schedule_label_is_explicit():
    from memq_dqc.scheduler.schedule_visualizer import (
        _event_label,
        _pretty_event_text,
    )

    event = ScheduledOperation(
        op_id=0,
        statement_id=0,
        name="y",
        qubits=("q0[0]", "c1[1]"),
        start_time=0.0,
        duration=2.0,
        is_remote=False,
        cat_proxy_qubits=("c1[1]",),
    )
    assert _event_label(event) == "y + proxy x"
    assert _pretty_event_text(event) == "Y + PROXY X"


@pytest.mark.parametrize(
    "algorithm",
    [
        "fifo",
        "des_link_fifo",
        "des_link_shortest_duration",
        "des_link_critical_path",
    ],
)
def test_independent_corrected_groups_cannot_reuse_live_pair(
    tmp_path, three_comp_one_comm_x2_network_path, algorithm
):
    compiler, _ = _compile(tmp_path, three_comp_one_comm_x2_network_path)
    source = tmp_path / "two_groups.qasm"
    source.write_text(
        'OPENQASM 3.0;\ninclude "stdgates.inc";\nqubit[4] q;\n'
        "h q[0]; h q[1];\n"
        "cx q[0], q[2]; y q[0]; cx q[0], q[2];\n"
        "cx q[1], q[3]; x q[1]; cx q[1], q[3];\n",
        encoding="utf-8",
    )
    compiler = Compiler(
        source, compiler.partitioner.network, algo=_FixedPartitioner
    )
    compiler.compile(ebit_assignment=False)
    distributed = compiler.distributed_circuit
    candidates = distributed.ebit_candidates_by_op_id
    assert candidates is not None
    for op in distributed.ops:
        if op.name == "catent":
            candidates[op.op_id] = candidates[op.op_id][1:]
    scheduler = Scheduler(
        compiler,
        algo=algorithm,
        profile=_PROFILE,
        algo_kwargs={} if algorithm == "fifo" else {"seed": 0},
    )
    scheduler.run()
    schedule = scheduler.schedule
    assert schedule is not None
    eprs = sorted(
        (event for event in schedule.operations if event.name == "epr"),
        key=lambda event: event.start_time,
    )
    closes = sorted(
        (event for event in schedule.operations if event.name == "catdisent"),
        key=lambda event: event.start_time,
    )
    assert len(eprs) == len(closes) == 2
    assert eprs[0].qubits == eprs[1].qubits == ("c0[1]", "c1[1]")
    assert eprs[1].start_time >= closes[0].end_time
    np.testing.assert_allclose(
        _scheduled_data_state(compiler, schedule).data,
        DensityMatrix.from_instruction(qasm3.loads(source.read_text())).data,
        atol=1e-12,
    )
