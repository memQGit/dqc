# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import pytest
from openqasm3 import ast

from memq_dqc.builder import extract_distributed_circuit, identify_remote_gates
from memq_dqc.graph import NetworkGraph
from memq_dqc.io.qasm import load_qasm_program
from memq_dqc.partition import Partitioner


def test_extract_distributed_circuit_requires_run(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )

    with pytest.raises(ValueError, match=r"partitioner.run\(\)"):
        extract_distributed_circuit(partitioner)


def test_identify_remote_gates_requires_run(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )

    with pytest.raises(ValueError, match=r"partition.run\(\)"):
        identify_remote_gates(partitioner.dag, partitioner)


def test_extract_distributed_circuit_returns_program(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    distributed_program = extract_distributed_circuit(partitioner)

    assert isinstance(distributed_program, ast.Program)
    assert distributed_program.statements
