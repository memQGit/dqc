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

import importlib
from collections import Counter
from pathlib import Path

import pytest
from openqasm3 import ast

from memq_dqc.circuit.op import Op
from memq_dqc.network import NetworkGraph
from memq_dqc.partition import Partitioner
from memq_dqc.partition.hypergraph import hypergraph as hypergraph_module
from memq_dqc.preprocessing.qasm.io import load_qasm_program
from memq_dqc.preprocessing.qasm.types import CircuitQubit


def _op(op_id: int, name: str, *qubit_indices: int) -> Op:
    return Op(
        op_id=op_id,
        statement_id=op_id,
        name=name,
        is_remote=False,
        qubits=tuple(
            CircuitQubit(register_name="q", index=index)
            for index in qubit_indices
        ),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier(name),
            arguments=[],
            qubits=[],
        ),
    )


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


def test_build_gate_packets_consumes_ignored_ops_before_commuted_gate() -> (
    None
):
    ops = [
        _op(0, "cx", 0, 1),
        _op(1, "h", 5),
        _op(2, "cx", 2, 3),
        _op(3, "cx", 0, 4),
    ]

    packets = hypergraph_module.build_gate_packets(ops)

    assert packets == [[{0, 1}, {0, 4}]]


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
        block_capacities: list[int] | None = None,
        seed: int | None = None,
    ) -> dict[str, int]:
        assert packet_counter
        assert k == 2
        assert Path(config_path).name == "kahypar_config.ini"
        assert Path(config_path).is_file()
        assert epsilon == 0.03
        # Default flag is ON, so real per-QPU capacities are forwarded.
        assert block_capacities == [3, 3]
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


class _FakeHypergraph:
    def __init__(self, *args) -> None:
        self._args = args

    def blockID(self, idx: int) -> int:  # noqa: N802 (KaHyPar API name)
        return 0


class _FakeContext:
    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def loadINIconfiguration(self, path) -> None:  # noqa: N802
        self.calls.append(("loadINIconfiguration", path))

    def setK(self, k) -> None:  # noqa: N802
        self.calls.append(("setK", k))

    def setEpsilon(self, eps) -> None:  # noqa: N802
        self.calls.append(("setEpsilon", eps))

    def setCustomTargetBlockWeights(self, weights) -> None:  # noqa: N802
        self.calls.append(("setCustomTargetBlockWeights", list(weights)))

    def suppressOutput(self, flag) -> None:  # noqa: N802
        self.calls.append(("suppressOutput", flag))


class _FakeKahypar:
    def __init__(self) -> None:
        self.context = _FakeContext()

    def Hypergraph(self, *args):  # noqa: N802
        return _FakeHypergraph(*args)

    def Context(self):  # noqa: N802
        return self.context

    def partition(self, hypergraph, context) -> None:
        pass


def _install_fake_kahypar(monkeypatch) -> _FakeKahypar:
    fake = _FakeKahypar()
    real_import = importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "kahypar":
            return fake
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(
        hypergraph_module.importlib, "import_module", fake_import
    )
    return fake


def _sample_packet_counter() -> hypergraph_module.PacketCounter:
    return Counter({("0", "1", "2"): 2, ("3", "4"): 1})


def test_partition_hypergraph_import_error_explains_windows(
    monkeypatch,
) -> None:
    real_import = importlib.import_module

    def failing_import(name, *args, **kwargs):
        if name == "kahypar":
            raise ImportError("No module named 'kahypar'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(
        hypergraph_module.importlib, "import_module", failing_import
    )

    # KaHyPar is intentionally absent on Windows, so this is a supported
    # configuration rather than a broken install: the message has to say so.
    with pytest.raises(ImportError, match="Windows"):
        hypergraph_module.partition_hypergraph(
            _sample_packet_counter(),
            k=2,
            config_path=hypergraph_module.resolve_kahypar_config_path(),
        )


def test_partition_hypergraph_sets_custom_block_weights_in_order(
    monkeypatch,
) -> None:
    fake = _install_fake_kahypar(monkeypatch)
    config_path = hypergraph_module.resolve_kahypar_config_path()

    hypergraph_module.partition_hypergraph(
        _sample_packet_counter(),
        k=3,
        config_path=config_path,
        block_capacities=[34, 34, 32],
    )

    names = [name for name, _ in fake.context.calls]
    assert ("setCustomTargetBlockWeights", [34, 34, 32]) in fake.context.calls
    # Custom weights must be set after setK/setEpsilon, before partition.
    assert names.index("setCustomTargetBlockWeights") > names.index("setK")
    assert names.index("setCustomTargetBlockWeights") > names.index(
        "setEpsilon"
    )


def test_partition_hypergraph_omits_block_weights_when_none(
    monkeypatch,
) -> None:
    fake = _install_fake_kahypar(monkeypatch)
    config_path = hypergraph_module.resolve_kahypar_config_path()

    hypergraph_module.partition_hypergraph(
        _sample_packet_counter(),
        k=2,
        config_path=config_path,
    )

    names = [name for name, _ in fake.context.calls]
    assert "setCustomTargetBlockWeights" not in names


def test_partition_hypergraph_rejects_mismatched_capacity_length(
    monkeypatch,
) -> None:
    _install_fake_kahypar(monkeypatch)
    config_path = hypergraph_module.resolve_kahypar_config_path()

    with pytest.raises(ValueError, match="block_capacities length"):
        hypergraph_module.partition_hypergraph(
            _sample_packet_counter(),
            k=3,
            config_path=config_path,
            block_capacities=[34, 34],
        )


def _capturing_fake(captured: dict) -> object:
    def fake_partition_hypergraph(
        packet_counter,
        *,
        k,
        config_path,
        epsilon,
        block_capacities=None,
        seed=None,
    ) -> dict[str, int]:
        captured["block_capacities"] = block_capacities
        captured["seed"] = seed
        return {"0": 0, "1": 0, "2": 0, "3": 1, "4": 1, "5": 1}

    return fake_partition_hypergraph


def test_partitioner_passes_qpu_capacities_by_default(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
    monkeypatch,
) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        hypergraph_module, "partition_hypergraph", _capturing_fake(captured)
    )
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))

    Partitioner(network, program, algo="hypergraph").run()

    assert captured["block_capacities"] == network.comp_qubits_per_qpu()


def test_partitioner_forwards_the_seed_to_kahypar(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
    monkeypatch,
) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        hypergraph_module, "partition_hypergraph", _capturing_fake(captured)
    )
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))

    Partitioner(
        network, program, algo="hypergraph", algo_kwargs={"seed": 7}
    ).run()

    assert captured["seed"] == 7


def test_partitioner_without_a_seed_leaves_the_ini_seed_alone(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
    monkeypatch,
) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        hypergraph_module, "partition_hypergraph", _capturing_fake(captured)
    )
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))

    Partitioner(network, program, algo="hypergraph").run()

    assert captured["seed"] is None


def test_partitioner_respect_capacities_false_passes_none(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
    monkeypatch,
) -> None:
    captured: dict = {}
    monkeypatch.setattr(
        hypergraph_module, "partition_hypergraph", _capturing_fake(captured)
    )
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))

    Partitioner(
        network,
        program,
        algo="hypergraph",
        algo_kwargs={"respect_qpu_capacities": False},
    ).run()

    assert captured["block_capacities"] is None


def test_validate_assignment_accepts_uneven_full_capacities() -> None:
    qpu_capacities = {0: 34, 1: 34, 2: 32}
    assignment = {
        0: set(range(0, 34)),
        1: set(range(34, 68)),
        2: set(range(68, 100)),
    }

    # Perfect packing of an uneven, fully-packed network must validate.
    hypergraph_module._validate_assignment(
        assignment,
        logical_qubits=set(range(100)),
        qpu_capacities=qpu_capacities,
    )
