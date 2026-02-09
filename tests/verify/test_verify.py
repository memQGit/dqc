# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

import openqasm3

from memq_dqc.builder import extract_distributed_circuit
from memq_dqc.graph import NetworkGraph
from memq_dqc.io.qasm import load_qasm_program
from memq_dqc.partition import Partitioner
from memq_dqc.verify import verify_distributed_circuit


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

    dist_prog = extract_distributed_circuit(partitioner)
    dist_path = tmp_path / "simple3_distributed.qasm"
    with dist_path.open("w", encoding="utf-8") as file_obj:
        openqasm3.dump(dist_prog, file_obj)

    assert (
        verify_distributed_circuit(str(circuit_path), str(dist_path)) is True
    )
