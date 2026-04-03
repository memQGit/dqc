# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import logging
from typing import Any, cast

import networkx as nx
import pytest

from memq_dqc.circuit import Circuit
from memq_dqc.network import NetworkGraph
from memq_dqc.partition import Partitioner
from memq_dqc.partition.partitioner import QPU, BasePartitioner
from memq_dqc.partition.utils import partition_cost
from memq_dqc.preprocessing.qasm.io import load_qasm_program
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
    assert len(schedule) == len(get_windows(Circuit(program), window_length=2))
    assert len(windows) == len(schedule)


def test_partitioner_accepts_network_and_qasm_paths(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    partitioner = Partitioner(
        three_comp_one_comm_x2_network_path,
        simple1_circuit_path,
        algo_kwargs={"window_length": 2},
    )

    partitioner.run()

    assert isinstance(partitioner.network, NetworkGraph)
    assert isinstance(partitioner.circuit, Circuit)
    assert partitioner.schedule
    assert partitioner.windows


def test_partitioner_benchmark_static_schedule_is_stationary(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo="benchmark_static",
        algo_kwargs={"window_length": 2},
    )
    partitioner.run()

    schedule = partitioner.schedule
    windows = partitioner.windows
    cost = partitioner.cost

    assert isinstance(cost, float)
    assert schedule
    assert windows
    assert len(schedule) == len(get_windows(Circuit(program), window_length=2))
    assert len(windows) == len(schedule)

    expected_assignment = {
        0: {0, 1, 2},
        1: {3, 4, 5},
    }
    for window in schedule:
        by_qpu_id = {qpu.id: qubits for qpu, qubits in window.items()}
        assert by_qpu_id == expected_assignment


def test_partitioner_run_quiet_emits_no_logs(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo="benchmark_static",
        algo_kwargs={"window_length": 2},
    )

    caplog.set_level(logging.DEBUG, logger="memq_dqc")
    partitioner.run()

    records = [
        record
        for record in caplog.records
        if record.name.startswith("memq_dqc")
    ]
    assert records == []


def test_partitioner_run_info_logs_summary(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo="benchmark_static",
        algo_kwargs={"window_length": 2},
    )

    caplog.set_level(logging.DEBUG, logger="memq_dqc")
    partitioner.run(verbosity="info")

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("memq_dqc")
    ]
    assert any(
        "Starting partitioning with BenchmarkStaticPartitioner." in msg
        for msg in messages
    )
    assert any("Partitioning completed in" in msg for msg in messages)


def test_partitioner_run_debug_logs_mappings_and_algorithm_details(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo="benchmark_static",
        algo_kwargs={"window_length": 2},
    )

    caplog.set_level(logging.DEBUG, logger="memq_dqc")
    partitioner.run(verbosity="debug")

    assert partitioner.schedule
    final_window_idx = len(partitioner.schedule) - 1

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("memq_dqc")
    ]

    assert (
        "Initial logical->physical mapping (window 0): "
        "{0: (0, 0), 1: (0, 1), 2: (0, 2), 3: (1, 0), 4: (1, 1), 5: (1, 2)}"
    ) in messages
    assert (
        "Final logical->physical mapping "
        f"(window {final_window_idx}): "
        "{0: (0, 0), 1: (0, 1), 2: (0, 2), 3: (1, 0), 4: (1, 1), 5: (1, 2)}"
    ) in messages
    assert any(
        "Benchmark static partitioning parameters:" in msg for msg in messages
    )


def test_partitioner_run_rejects_invalid_verbosity(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo="benchmark_static",
        algo_kwargs={"window_length": 2},
    )

    invalid_verbosity = cast(Any, "loud")
    with pytest.raises(ValueError, match="Unsupported verbosity"):
        partitioner.run(verbosity=invalid_verbosity)


def test_partitioner_benchmark_static_uses_effective_sizes(
    simple1_circuit_path,
    simple1_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network_path = simple1_network_path.parent / "simple_8comp_4comm.json"
    network = NetworkGraph(str(network_path))
    partitioner = Partitioner(
        network,
        program,
        algo="BenchmarkStatic",
        algo_kwargs={"window_length": 2},
    )
    partitioner.run()

    assert partitioner.schedule
    first_window = partitioner.schedule[0]
    by_qpu_id = {
        qpu.id: assigned_qubits
        for qpu, assigned_qubits in first_window.items()
    }
    assert by_qpu_id == {
        1: {0, 1, 2, 3},
        2: {4, 5},
    }


def test_partitioner_benchmark_random_schedule_is_stationary(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo="benchmark_random",
        algo_kwargs={"window_length": 2, "seed": 123},
    )
    partitioner.run()

    schedule = partitioner.schedule
    windows = partitioner.windows

    assert schedule
    assert windows
    assert len(schedule) == len(get_windows(Circuit(program), window_length=2))
    assert len(windows) == len(schedule)

    first_window = {qpu.id: qubits for qpu, qubits in schedule[0].items()}
    for window in schedule[1:]:
        by_qpu_id = {qpu.id: qubits for qpu, qubits in window.items()}
        assert by_qpu_id == first_window

    assert sorted(len(qubits) for qubits in first_window.values()) == [3, 3]
    all_assigned_qubits = set().union(*first_window.values())
    assert all_assigned_qubits == set(range(6))


def test_partitioner_benchmark_random_is_seeded_and_uses_effective_sizes(
    simple1_circuit_path,
    simple1_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network_path = simple1_network_path.parent / "simple_8comp_4comm.json"
    network = NetworkGraph(str(network_path))

    partitioner_a = Partitioner(
        network,
        program,
        algo="BenchmarkRandom",
        algo_kwargs={"window_length": 2, "seed": 99},
    )
    partitioner_b = Partitioner(
        network,
        program,
        algo="BenchmarkRandom",
        algo_kwargs={"window_length": 2, "seed": 99},
    )
    partitioner_a.run()
    partitioner_b.run()

    assert partitioner_a.schedule
    assert partitioner_b.schedule
    by_qpu_a = {
        qpu.id: qubits for qpu, qubits in partitioner_a.schedule[0].items()
    }
    by_qpu_b = {
        qpu.id: qubits for qpu, qubits in partitioner_b.schedule[0].items()
    }
    assert by_qpu_a == by_qpu_b
    assert sorted(len(qubits) for qubits in by_qpu_a.values()) == [2, 4]
    assert set().union(*by_qpu_a.values()) == set(range(6))


def test_partitioner_cost_uses_total_schedule_ebits(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    class _ReportedCostPartitioner(BasePartitioner):
        def run(self) -> None:
            self.windows = [self.circuit.mono.ops]
            self.schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]
            self.cost = 0.0

    qasm_path = tmp_path / "single_remote.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\ncx q[0], q[1];\n",
        encoding="utf-8",
    )
    program = load_qasm_program(str(qasm_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_ReportedCostPartitioner(network, program),
    )

    partitioner.run()

    assert partitioner.cost == 1.0


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


def test_partition_cost_supports_topology_aware_ebit_multiplier(
    simple1_network_path,
) -> None:
    network_path = simple1_network_path.parent / "nonuniform_1.json"
    network = NetworkGraph(str(network_path))
    network_qpu_ids = sorted(
        {qubit.qpu_id for qubit in network.qubit_type_map}
    )

    graph = nx.Graph()
    graph.add_edge(0, 1, weight=2)

    one_hop_partition = [{0}, {1}, set()]
    one_hop_multiplier = float(
        network.remote_gate_ebit_cost(network_qpu_ids[0], network_qpu_ids[1])
    )
    one_hop_cost = partition_cost(
        graph,
        one_hop_partition,
        edge_cost=lambda part_a, part_b: float(
            network.remote_gate_ebit_cost(
                network_qpu_ids[part_a], network_qpu_ids[part_b]
            )
        ),
    )
    assert one_hop_cost == 2.0 * one_hop_multiplier

    two_hop_partition = [{0}, set(), {1}]
    two_hop_multiplier = float(
        network.remote_gate_ebit_cost(network_qpu_ids[0], network_qpu_ids[2])
    )
    two_hop_cost = partition_cost(
        graph,
        two_hop_partition,
        edge_cost=lambda part_a, part_b: float(
            network.remote_gate_ebit_cost(
                network_qpu_ids[part_a], network_qpu_ids[part_b]
            )
        ),
    )
    assert two_hop_cost == 2.0 * two_hop_multiplier
    assert two_hop_cost == 10.0
