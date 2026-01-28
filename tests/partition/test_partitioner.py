# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from memq_dqc.circuit import CircuitDAG
from memq_dqc.graph import NetworkGraph
from memq_dqc.partition import Partitioner
from memq_dqc.utils import get_windows, load_qasm_program


def test_partitioner_cisco_default(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    algo_args = {"window_length": 2}
    partitioner = Partitioner(network, program, algo_kwargs=algo_args)
    cost, schedule = partitioner.run()

    assert isinstance(cost, float)
    assert schedule
    assert len(schedule) == len(
        get_windows(CircuitDAG(program), window_length=2)
    )


def test_partitioner_large_circuit(
    qv_100_circuit_path,
    hundred_qubit_network_path,
) -> None:
    program = load_qasm_program(str(qv_100_circuit_path), from_cache=True)
    network = NetworkGraph(str(hundred_qubit_network_path))
    partitioner = Partitioner(network, program)
    cost, schedule = partitioner.run()
    # For now, just confirm it runs without error
    assert isinstance(cost, float)
    assert schedule
    # Make sure each window of schedule has correct number of qubits
    for window in schedule:
        total_qubits = sum(len(part) for part in window)
        assert total_qubits == network.num_comp_qubits
