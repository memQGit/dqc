# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from collections import Counter
from pathlib import Path

from memq_dqc.network import NetworkGraph
from memq_dqc.partition import Partitioner
from memq_dqc.partition.hypergraph import hypergraph as hypergraph_module
from memq_dqc.preprocessing.qasm.io import load_qasm_program


def test_packets_to_hypergraph_counts_group_qubit_sets() -> None:
    packets = [
        [{0, 1}, {0, 2}],
        [{2, 0}, {1}],
        [{3, 4}],
    ]

    assert hypergraph_module.packets_to_hypergraph(packets) == Counter(
        {
            ("0", "1", "2"): 2,
            ("3", "4"): 1,
        }
    )


def test_partition_result_to_assignment_uses_network_qpu_ids() -> None:
    assignment = hypergraph_module.partition_result_to_assignment(
        {"0": 1, "10": 0},
        [4, 7],
    )

    assert assignment == {
        4: {10},
        7: {0},
    }


def test_resolve_kahypar_config_path_uses_packaged_file() -> None:
    config_path = hypergraph_module.resolve_kahypar_config_path()

    assert config_path.name == "kahypar_config.ini"
    assert config_path.is_file()


def test_hypergraph_partitioner_builds_static_schedule(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
    monkeypatch,
) -> None:
    def fake_partition_hypergraph(
        packet_counter: hypergraph_module.PacketCounter,
        *,
        k: int,
        config_path: str | Path,
        epsilon: float,
    ) -> dict[str, int]:
        assert packet_counter
        assert k == 2
        assert Path(config_path).name == "kahypar_config.ini"
        assert Path(config_path).is_file()
        assert epsilon == 0.03
        return {
            "0": 0,
            "1": 0,
            "2": 0,
            "3": 1,
            "4": 1,
            "5": 1,
        }

    monkeypatch.setattr(
        hypergraph_module,
        "partition_hypergraph",
        fake_partition_hypergraph,
    )
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo="hypergraph",
    )

    partitioner.run()

    assert partitioner.windows
    assert len(partitioner.windows) == 1
    assert partitioner.schedule
    assert len(partitioner.schedule) == 1
    by_qpu_id = {
        qpu.id: qubits for qpu, qubits in partitioner.schedule[0].items()
    }
    assert by_qpu_id == {
        0: {0, 1, 2},
        1: {3, 4, 5},
    }
    assert isinstance(partitioner.cost, float)
