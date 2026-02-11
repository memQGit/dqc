# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import pytest

from memq_dqc.circuit import CircuitDAG
from memq_dqc.graph import NetworkGraph
from memq_dqc.io.qasm import load_qasm_program
from memq_dqc.partition import Partitioner
from memq_dqc.utils import get_windows


def test_partitioner_cisco_default(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    algo_args = {"window_length": 2}
    partitioner = Partitioner(network, program, algo_kwargs=algo_args)
    partitioner.run()
    cost = partitioner.cost
    schedule = partitioner.schedule
    windows = partitioner.windows

    assert isinstance(cost, float)
    assert schedule
    assert windows
    assert len(schedule) == len(
        get_windows(CircuitDAG(program), window_length=2)
    )
    assert len(windows) == len(schedule)


def test_partitioner_large_circuit(
    qv_100_circuit_path,
    hundred_qubit_network_path,
) -> None:
    program = load_qasm_program(str(qv_100_circuit_path), from_cache=True)
    network = NetworkGraph(str(hundred_qubit_network_path))
    partitioner = Partitioner(network, program)
    partitioner.run()
    cost = partitioner.cost
    schedule = partitioner.schedule
    # For now, just confirm it runs without error
    assert isinstance(cost, float)
    assert schedule
    # Make sure each window of schedule has correct number of qubits
    for window in schedule:
        total_qubits = sum(len(part) for part in window.values())
        assert total_qubits == network.num_comp_qubits


def test_partitioner_supports_extra_comp_capacity(
    simple1_circuit_path,
    simple1_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network_path = simple1_network_path.parent / "simple_8comp_4comm.json"
    network = NetworkGraph(str(network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    assert partitioner.schedule
    for window in partitioner.schedule:
        total_qubits = sum(len(part) for part in window.values())
        assert total_qubits == 6


def test_partitioner_raises_on_insufficient_comp_capacity(
    simple1_circuit_path,
    simple1_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(simple1_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )

    with pytest.raises(
        ValueError, match="Insufficient computation-qubit capacity"
    ):
        partitioner.run()
