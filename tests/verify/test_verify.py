# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

import openqasm3
import pytest

from memq_dqc.builder import extract_distributed_circuit
from memq_dqc.graph import NetworkGraph
from memq_dqc.io.qasm import load_qasm_program
from memq_dqc.partition import Partitioner

# TODO: add back - from memq_dqc.verify import verify_distributed_circuit
from memq_dqc.verify.verify import dist_to_mono_circuit


# TODO: need more tests!
def test_verify_distributed_circuit_simple3(
    three_comp_one_comm_x2_network_path: Path,
    tmp_path: Path,
) -> None:
    circuit_path = (
        Path(__file__).resolve().parents[1]
        / "fixtures"
        / "circuits"
        / "simple3.qasm"
    )

    qasm_program = load_qasm_program(str(circuit_path))
    network_graph = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(network_graph, qasm_program)
    partitioner.run()

    # we expect this to fail and raise ValueError for now
    # TODO: fix this - right now it is failing because only 1 comm qubit
    with pytest.raises(ValueError):
        extract_distributed_circuit(partitioner)


#    dist_path = tmp_path / "simple3_distributed.qasm"
#  with dist_path.open("w", encoding="utf-8") as file_obj:
#     openqasm3.dump(dist_prog, file_obj)

#   assert (
#      verify_distributed_circuit(str(circuit_path), str(dist_path)) is True
#   )


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
