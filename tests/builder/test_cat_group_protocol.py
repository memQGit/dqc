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

import json
from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pytest
from openqasm3 import ast, dumps, parse
from qiskit import QuantumCircuit, qasm3, transpile
from qiskit.circuit.library import XGate, YGate
from qiskit.quantum_info import DensityMatrix, partial_trace
from qiskit_aer import AerSimulator
from qiskit_aer.library import SaveDensityMatrix

from memq_dqc import Compiler
from memq_dqc.circuit.circuit import extract_ops, extract_program_statements
from memq_dqc.circuit.dag import DistributedCircuitDAG, build_annotated_dag
from memq_dqc.circuit.dag.annotated import annotated_dag_to_json
from memq_dqc.network import generate_network
from memq_dqc.partition import QPU, BasePartitioner
from memq_dqc.preprocessing.qasm.types import CircuitQubit


class _FixedPartitioner(BasePartitioner):
    def run(self):
        self.schedule = [{QPU(id=0): {0, 1}, QPU(id=1): {2, 3}}]
        self.windows = [self.circuit.mono.ops]


_INTERLUDES = [
    pytest.param("x q[0];", "x", (0,), (), 1, id="x-control"),
    pytest.param("y q[0];", "y", (0,), (), 1, id="y-control"),
    pytest.param("h q[0];", "h", (0,), (), 2, id="h-control"),
    pytest.param("rx(0.3) q[0];", "rx", (0,), (0.3,), 2, id="rx-control"),
    pytest.param("ry(0.3) q[0];", "ry", (0,), (0.3,), 2, id="ry-control"),
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


def _materialized_ops(compiler, candidate_index=0):
    """Bind deferred operands to one advertised candidate, without rewriting gates."""
    ops = compiler.distributed_circuit.ops
    candidates = compiler.distributed_circuit.ebit_candidates_by_op_id
    if candidates is None:
        return ops
    materialized = []
    active_pair = ()
    for op in ops:
        if op.name == "catent":
            active_pair = tuple(
                CircuitQubit(f"c{q.qpu_id}", q.qubit_id)
                for pair in candidates[op.op_id][candidate_index]
                for q in pair
            )
        if op.name in {"catent", "catdisent", "rcx", "rcp", "rcry", "rcz"}:
            assert len(active_pair) == 2
            op = replace(op, qubits=(*op.qubits, *active_pair))
        materialized.append(op)
        if op.name == "catdisent":
            active_pair = ()
    return materialized


def _protocol_circuit(
    compiler,
    *,
    measured_feedforward=False,
    data_qubits=None,
    candidate_index=0,
):
    # Map the emitted physical operands directly, independent of QASM register
    # declaration sizes. These tests check the protocol, not serialization.
    if data_qubits is None:
        data_qubits = [
            CircuitQubit("q0", 0),
            CircuitQubit("q0", 1),
            CircuitQubit("q1", 0),
            CircuitQubit("q1", 1),
        ]
    indices = {qubit: index for index, qubit in enumerate(data_qubits)}
    ops = _materialized_ops(compiler, candidate_index)
    for op in ops:
        for qubit in op.qubits:
            if qubit not in indices:
                indices[qubit] = len(indices)
    circuit = QuantumCircuit(len(indices), 2 if measured_feedforward else 0)
    active_control = active_proxy = None
    for op in ops:
        qubits = [indices[qubit] for qubit in op.qubits]
        assert isinstance(op.node, ast.QuantumGate)
        arguments = []
        for argument in op.node.arguments:
            assert isinstance(argument, (ast.FloatLiteral, ast.IntegerLiteral))
            arguments.append(argument.value)
        if op.name == "catent":
            control, _, local_comm, remote_comm = qubits
            active_control, active_proxy = control, remote_comm
            circuit.reset([local_comm, remote_comm])
            circuit.h(local_comm)
            circuit.cx(local_comm, remote_comm)
            circuit.cx(control, local_comm)
            # Coherent feed-forward followed by discarding the measured qubit
            # is the exact channel of measure(local_comm); if 1: X(remote_comm).
            if measured_feedforward:
                circuit.measure(local_comm, 0)
                with circuit.if_test((circuit.clbits[0], 1)):
                    circuit.x(remote_comm)
            else:
                circuit.cx(local_comm, remote_comm)
            circuit.reset(local_comm)
        elif op.name == "catdisent":
            control, _, _, remote_comm = qubits
            circuit.h(remote_comm)
            # Likewise, measure(remote_comm); if 1: Z(control), then discard.
            if measured_feedforward:
                circuit.measure(remote_comm, 1)
                with circuit.if_test((circuit.clbits[1], 1)):
                    circuit.z(control)
            else:
                circuit.cz(remote_comm, control)
            circuit.reset(remote_comm)
            active_control = active_proxy = None
        elif op.name in {"rcx", "rcp", "rcry", "rcz"}:
            getattr(circuit, op.name[1:])(*arguments, qubits[3], qubits[1])
        elif op.node.modifiers:
            assert op.name in {"x", "y"}
            gate = XGate() if op.name == "x" else YGate()
            for modifier in op.node.modifiers:
                assert modifier.modifier == ast.GateModifierName.pow
                assert isinstance(
                    modifier.argument, (ast.FloatLiteral, ast.IntegerLiteral)
                )
                gate = gate.power(modifier.argument.value)
            circuit.append(gate, qubits)
        else:
            getattr(circuit, op.name)(*arguments, *qubits)
        if op.cat_proxy_x:
            # The marker is part of the emitted protocol, not an extra data
            # gate. Resolve it against this group's actual selected e-bit.
            assert op.name in {"x", "y"}
            assert qubits == [active_control]
            assert active_proxy is not None
            circuit.x(active_proxy)

    return circuit


def _protocol_data_state(compiler, **options):
    circuit = _protocol_circuit(compiler, **options)
    return partial_trace(
        DensityMatrix.from_instruction(circuit),
        list(range(4, circuit.num_qubits)),
    )


@pytest.mark.parametrize("interlude,name,qubits,arguments,groups", _INTERLUDES)
@pytest.mark.parametrize(
    "prepare", [False, True], ids=["zero", "superposition"]
)
@pytest.mark.parametrize(
    "group_gates", [True, False], ids=["grouped", "ungrouped"]
)
@pytest.mark.parametrize("remote_gate", ["cx", "cp", "cry", "cz"])
@pytest.mark.parametrize("ebit_assignment", [True, False])
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
    ebit_assignment,
):
    compiler = _compile_interlude(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        interlude,
        prepare,
        remote_gate=remote_gate,
        group_gates=group_gates,
        ebit_assignment=ebit_assignment,
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
def test_control_change_output_respects_ebit_assignment(
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

    names = [op.name for op in compiler.distributed_circuit.ops]
    if interlude.split()[0] in {"x", "y"}:
        assert names == [
            "catent",
            "rcx",
            interlude.split()[0],
            *(["x"] if ebit_assignment else []),
            "rcx",
            "catdisent",
        ]
        ops = compiler.distributed_circuit.ops
        if ebit_assignment:
            assert ops[3].qubits == (ops[0].qubits[3],)
            assert not any(op.cat_proxy_x for op in ops)
        else:
            assert ops[2].cat_proxy_x
            assert all(
                not q.register_name.startswith("c")
                for op in ops
                for q in op.qubits
            )
        assert compiler.cost == 1.0
        return
    assert names == [
        "catent",
        "rcx",
        "catdisent",
        interlude.split()[0],
        "catent",
        "rcx",
        "catdisent",
    ]
    assert compiler.cost == 2.0
    if not ebit_assignment:
        assert all(
            not qubit.register_name.startswith("c")
            for op in compiler.distributed_circuit.ops
            for qubit in op.qubits
        )


def _compile_reference(tmp_path, network_path, expected, **options):
    source = tmp_path / "cat_reference.qasm"
    source.write_text(qasm3.dumps(expected), encoding="utf-8")
    compiler = Compiler(source, network_path, algo=_FixedPartitioner)
    compiler.compile(**options)
    return compiler


def _prepared_reference():
    expected = QuantumCircuit(4)
    expected.h(0)
    expected.p(0.71, 0)
    expected.ry(0.4, 1)
    expected.cx(0, 1)
    expected.ry(0.83, 2)
    expected.p(0.29, 2)
    expected.h(3)
    return expected


@pytest.mark.parametrize("flips", ["x", "y", "xx", "xy", "yx", "yy", "xyx"])
@pytest.mark.parametrize("interleaved", [False, True])
@pytest.mark.parametrize("remote_gate", ["cx", "cp", "cry", "cz"])
@pytest.mark.parametrize("ebit_assignment", [True, False])
def test_repeated_corrections_preserve_entangled_state(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    flips,
    interleaved,
    remote_gate,
    ebit_assignment,
):
    expected = _prepared_reference()
    arguments = (0.43,) if remote_gate in {"cp", "cry"} else ()
    getattr(expected, remote_gate)(*arguments, 0, 2)
    for index, flip in enumerate(flips):
        getattr(expected, flip)(0)
        if interleaved:
            getattr(expected, remote_gate)(*arguments, 0, 2 + index % 2)
    getattr(expected, remote_gate)(*arguments, 0, 3)
    compiler = _compile_reference(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        expected,
        ebit_assignment=ebit_assignment,
    )
    ops = compiler.distributed_circuit.ops
    catent = next(op for op in ops if op.name == "catent")
    corrections = (
        [op for op in ops if op.cat_proxy_x]
        if not ebit_assignment
        else [
            op
            for op in ops
            if op.name == "x" and op.qubits == (catent.qubits[3],)
        ]
    )
    assert len(corrections) == len(flips)
    assert sum(op.name == "catent" for op in ops) == 1
    assert compiler.cost == 1.0
    np.testing.assert_allclose(
        _protocol_data_state(compiler).data,
        DensityMatrix.from_instruction(expected).data,
        atol=1e-12,
    )

    # Also execute real measurements and classical feed-forward in Aer.
    # Both Bell measurement outcomes occur; the final data state must be
    # independent of them, including its off-diagonal coherences.
    measured = _protocol_circuit(compiler, measured_feedforward=True)
    measured.append(SaveDensityMatrix(4), list(range(4)))
    simulator = AerSimulator(method="density_matrix")
    measured = transpile(measured, simulator, optimization_level=0)
    result = simulator.run(measured, shots=128, seed_simulator=134).result()
    assert len(result.get_counts()) == 4
    np.testing.assert_allclose(
        result.data()["density_matrix"].data,
        DensityMatrix.from_instruction(expected).data,
        atol=1e-12,
    )


@pytest.mark.parametrize("ebit_assignment", [True, False])
def test_correction_only_after_live_cat_is_opened(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    ebit_assignment,
):
    expected = _prepared_reference()
    expected.x(0)  # Initial local CX may seed a group, but has no live proxy.
    expected.cx(0, 2)
    expected.y(0)
    expected.cx(0, 3)
    expected.x(0)  # Trailing X is after the group, not a proxy correction.
    compiler = _compile_reference(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        expected,
        ebit_assignment=ebit_assignment,
    )
    ops = compiler.distributed_circuit.ops
    corrections = [
        op
        for op in ops
        if op.cat_proxy_x
        or (op.name == "x" and op.qubits[0].register_name.startswith("c"))
    ]
    assert len(corrections) == 1
    np.testing.assert_allclose(
        _protocol_data_state(compiler).data,
        DensityMatrix.from_instruction(expected).data,
        atol=1e-12,
    )


@pytest.mark.parametrize("boundary", ["h", "rx", "ry", "swap"])
def test_corrections_do_not_cross_unsupported_boundary(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    boundary,
):
    expected = _prepared_reference()
    expected.cx(0, 2)
    expected.x(0)
    expected.cx(0, 3)
    if boundary == "swap":
        expected.swap(0, 1)
    elif boundary in {"rx", "ry"}:
        getattr(expected, boundary)(0.39, 0)
    else:
        expected.h(0)
    expected.cx(0, 2)
    expected.y(0)
    expected.cx(0, 3)
    compiler = _compile_reference(
        tmp_path, three_comp_one_comm_x2_network_path, expected
    )
    assert compiler.cost == 2.0
    np.testing.assert_allclose(
        _protocol_data_state(compiler).data,
        DensityMatrix.from_instruction(expected).data,
        atol=1e-12,
    )


@pytest.mark.parametrize("ebit_assignment", [True, False])
def test_no_stale_proxy_correction_after_partner_changes(
    tmp_path, ebit_assignment
):
    class ThreeQpuPartitioner(BasePartitioner):
        def run(self):
            self.schedule = [
                {QPU(id=0): {0, 1}, QPU(id=1): {2}, QPU(id=2): {3}}
            ]
            self.windows = [self.circuit.mono.ops]

    network = tmp_path / "three_qpus.json"
    network.write_text(
        json.dumps(
            generate_network(
                3, 2, "all_to_all", intra_qpu="all_to_all", links_per_pair=1
            )
        ),
        encoding="utf-8",
    )
    expected = _prepared_reference()
    expected.cx(0, 2)
    expected.x(0)
    expected.cx(0, 3)  # Different partner closes the previous cat region.
    expected.y(0)  # Must not flip that now-disentangled proxy.
    expected.cx(0, 2)
    source = tmp_path / "changed_partner.qasm"
    source.write_text(qasm3.dumps(expected), encoding="utf-8")
    compiler = Compiler(source, network, algo=ThreeQpuPartitioner)
    compiler.compile(ebit_assignment=ebit_assignment)
    corrections = [
        op
        for op in compiler.distributed_circuit.ops
        if op.cat_proxy_x
        or (op.name == "x" and op.qubits[0].register_name.startswith("c"))
    ]
    assert len(corrections) == 1
    assert compiler.cost == 3.0
    np.testing.assert_allclose(
        _protocol_data_state(
            compiler,
            data_qubits=[
                CircuitQubit("q0", 0),
                CircuitQubit("q0", 1),
                CircuitQubit("q1", 0),
                CircuitQubit("q2", 0),
            ],
        ).data,
        DensityMatrix.from_instruction(expected).data,
        atol=1e-12,
    )


@pytest.mark.parametrize("name", ["x", "y"])
@pytest.mark.parametrize("power", [0.5, 2])
def test_modified_paulis_are_boundaries(
    tmp_path, three_comp_one_comm_x2_network_path, name, power
):
    compiler = _compile_interlude(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        f"pow({power}) @ {name} q[0];",
        True,
    )
    expected = QuantumCircuit(4)
    expected.h(0)
    expected.s(0)
    expected.ry(0.4, 1)
    expected.cx(0, 1)
    expected.h(2)
    expected.s(2)
    expected.ry(0.7, 3)
    expected.cx(0, 2)
    gate = XGate() if name == "x" else YGate()
    expected.append(gate.power(power), [0])
    expected.cx(0, 3)
    assert compiler.cost == 2.0
    assert not any(
        op.name == "x" and op.qubits[0].register_name.startswith("c")
        for op in compiler.distributed_circuit.ops
    )
    np.testing.assert_allclose(
        _protocol_data_state(compiler).data,
        DensityMatrix.from_instruction(expected).data,
        atol=1e-12,
    )


@pytest.mark.parametrize("name", ["x", "y"])
def test_deferred_marker_round_trip_binds_each_candidate(tmp_path, name):
    network = tmp_path / "two_links.json"
    network.write_text(
        json.dumps(
            generate_network(
                2, 2, "all_to_all", intra_qpu="all_to_all", links_per_pair=2
            )
        ),
        encoding="utf-8",
    )
    expected = _prepared_reference()
    expected.cx(0, 2)
    getattr(expected, name)(0)
    expected.cx(0, 3)
    compiler = _compile_reference(
        tmp_path, network, expected, ebit_assignment=False
    )
    distributed = compiler.distributed_circuit
    marked = [op for op in distributed.ops if op.cat_proxy_x]
    assert len(marked) == 1
    assert marked[0].name == name
    source = dumps(distributed.program)
    assert f"@memq.cat_proxy_x\n{name} q0[0];" in source
    program = parse(source)
    statements = extract_program_statements(program)
    ops = extract_ops(statements)
    assert [(op.name, op.cat_proxy_x) for op in ops] == [
        (op.name, op.cat_proxy_x) for op in distributed.ops
    ]
    round_trip = replace(
        distributed,
        program=program,
        statements=statements,
        ops=ops,
        dag=DistributedCircuitDAG(ops, ignore_remote_ebit_dependencies=True),
    )
    graph = build_annotated_dag(round_trip)
    serialized = json.loads(annotated_dag_to_json(graph))
    assert serialized["schema_version"] == 2
    correction = next(
        node for node in serialized["nodes"] if node.get("cat_proxy_x", False)
    )
    catent = next(
        node for node in serialized["nodes"] if node["name"] == "catent"
    )
    assert correction["group_id"] == catent["group_id"]
    assert correction["comm_qubits"] == []
    assert len(catent["ebit_candidates"]) == 2
    for candidate_index in (0, 1):
        np.testing.assert_allclose(
            _protocol_data_state(
                SimpleNamespace(distributed_circuit=round_trip),
                candidate_index=candidate_index,
            ).data,
            DensityMatrix.from_instruction(expected).data,
            atol=1e-12,
        )


def test_monolithic_rewrite_drops_only_proxy_marker(
    tmp_path,
    three_comp_one_comm_x2_network_path,
):
    from memq_dqc.verify.verify import dist_to_mono_program

    compiler = _compile_interlude(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        "y q[0];",
        False,
        ebit_assignment=False,
    )
    program = compiler.distributed_circuit.program
    rewritten = dist_to_mono_program(program)
    assert "@memq.cat_proxy_x" not in dumps(rewritten)
    assert "y q0[0];" in dumps(rewritten)
    # Reading the monolithic view must not strip the original protocol action.
    assert "@memq.cat_proxy_x" in dumps(program)


@pytest.mark.parametrize("ebit_assignment", [True, False])
@pytest.mark.parametrize("max_group_size", [1, 2])
def test_proxy_corrections_respect_group_size_boundaries(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    ebit_assignment,
    max_group_size,
):
    expected = _prepared_reference()
    # End the preparation's local-CX group before counting remote groups.
    expected.h(0)
    expected.h(0)
    expected.cx(0, 2)
    expected.x(0)
    expected.cx(0, 3)
    expected.y(0)
    expected.cx(0, 2)
    expected.x(0)
    expected.cx(0, 3)
    compiler = _compile_reference(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        expected,
        ebit_assignment=ebit_assignment,
        max_group_size=max_group_size,
    )
    ops = compiler.distributed_circuit.ops
    assert sum(op.name == "catent" for op in ops) == (
        4 if max_group_size == 1 else 2
    )
    corrections = [
        op
        for op in ops
        if op.cat_proxy_x
        or (op.name == "x" and op.qubits[0].register_name.startswith("c"))
    ]
    assert len(corrections) == (0 if max_group_size == 1 else 2)
    np.testing.assert_allclose(
        _protocol_data_state(compiler).data,
        DensityMatrix.from_instruction(expected).data,
        atol=1e-12,
    )


@pytest.mark.parametrize("ebit_assignment", [True, False])
@pytest.mark.parametrize("remote_gate", ["cx", "cp", "cry", "cz"])
def test_proxy_is_remote_half_with_reversed_qpu_order(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    ebit_assignment,
    remote_gate,
):
    expected = _prepared_reference()
    expected.h(0)
    expected.h(0)
    arguments = (0.43,) if remote_gate in {"cp", "cry"} else ()
    getattr(expected, remote_gate)(*arguments, 2, 0)
    expected.y(2)
    getattr(expected, remote_gate)(*arguments, 2, 1)
    compiler = _compile_reference(
        tmp_path,
        three_comp_one_comm_x2_network_path,
        expected,
        ebit_assignment=ebit_assignment,
    )
    catent = next(
        op for op in _materialized_ops(compiler) if op.name == "catent"
    )
    assert catent.qubits[2].register_name == "c1"
    assert catent.qubits[3].register_name == "c0"
    assert compiler.cost == 1.0
    np.testing.assert_allclose(
        _protocol_data_state(compiler).data,
        DensityMatrix.from_instruction(expected).data,
        atol=1e-12,
    )


def test_deferred_candidates_are_direct_for_every_group_target(tmp_path):
    network_data = generate_network(
        2, 2, "all_to_all", intra_qpu="all_to_all", links_per_pair=2
    )
    # Link 1 is direct for the first target but would need a local SWAP for
    # the second. No such SWAP is emitted inside this shared cat block.
    network_data["qubits"]["q_1_1"]["localConnections"].remove("c_1_1")
    network_data["qubits"]["c_1_1"]["localConnections"].remove("q_1_1")
    network = tmp_path / "asymmetric_links.json"
    network.write_text(json.dumps(network_data), encoding="utf-8")
    expected = _prepared_reference()
    expected.cx(0, 2)
    expected.y(0)
    expected.cx(0, 3)
    compiler = _compile_reference(
        tmp_path, network, expected, ebit_assignment=False
    )
    candidates = compiler.distributed_circuit.ebit_candidates_by_op_id
    assert candidates is not None
    assert all(len(options) == 1 for options in candidates.values())
    assert all(
        pair[1].qubit_id == network_data["qubits"]["c_1_0"]["localIndex"]
        for options in candidates.values()
        for pair in options[0]
    )
    assert compiler.cost == 1.0
    np.testing.assert_allclose(
        _protocol_data_state(compiler).data,
        DensityMatrix.from_instruction(expected).data,
        atol=1e-12,
    )


@pytest.mark.parametrize("name", ["x", "y"])
def test_monolithic_input_rejects_reserved_proxy_marker(
    tmp_path,
    three_comp_one_comm_x2_network_path,
    name,
):
    with pytest.raises(ValueError, match="reserved for emitted distributed"):
        _compile_interlude(
            tmp_path,
            three_comp_one_comm_x2_network_path,
            f"@memq.cat_proxy_x\n{name} q[0];",
            False,
        )
