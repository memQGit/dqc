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

import json
from typing import get_args

import pytest

from memq_dqc.assets import circuit_path, network_path
from memq_dqc.mcp_server import tools
from memq_dqc.scheduler.schedule import SchedulerModality

CIRCUIT = "qft_n4"
NETWORK = "10_qubits/n2_pair_nn"


def test_list_algorithms_matches_registered_options():
    options = tools.list_algorithms()

    assert "interaction" in options["partitioners"]
    assert "fifo" in options["schedulers"]
    assert options["modalities"] == list(get_args(SchedulerModality))


def test_list_bundled_assets_includes_known_assets():
    assets = tools.list_bundled_assets()

    assert CIRCUIT in assets["circuits"]
    assert NETWORK in assets["networks"]


def test_describe_network_reports_qpu_layout():
    summary = tools.describe_network(NETWORK)

    assert summary["num_qpus"] == 2
    assert len(summary["computation_qubits_per_qpu"]) == 2
    assert isinstance(summary["is_homogeneous"], bool)


@pytest.mark.parametrize(
    "circuit",
    [
        CIRCUIT,
        str(circuit_path(CIRCUIT)),
        circuit_path(CIRCUIT).read_text(),
    ],
    ids=["bundled-name", "path", "inline-qasm"],
)
def test_compile_circuit_accepts_every_circuit_form(circuit):
    expected = tools.compile_circuit(CIRCUIT, NETWORK)

    result = tools.compile_circuit(circuit, NETWORK)

    assert result == expected


@pytest.mark.parametrize(
    "network",
    [
        str(network_path(NETWORK)),
        network_path(NETWORK).read_text(),
    ],
    ids=["path", "inline-json"],
)
def test_compile_circuit_accepts_every_network_form(network):
    expected = tools.compile_circuit(CIRCUIT, NETWORK)

    result = tools.compile_circuit(CIRCUIT, network)

    assert result == expected


def test_compile_circuit_rejects_malformed_inline_network():
    with pytest.raises(json.JSONDecodeError):
        tools.compile_circuit(CIRCUIT, "{not json")


def test_compile_circuit_returns_distributed_qasm():
    result = tools.compile_circuit(CIRCUIT, NETWORK)

    assert result["num_logical_qubits"] == 4
    assert result["num_qpus"] == 2
    assert result["ebit_cost"] is not None
    assert result["distributed_qasm"].startswith("OPENQASM 3")
    assert "output_path" not in result


def test_compile_circuit_writes_output_file_when_asked(tmp_path):
    destination = tmp_path / "nested" / "out.qasm"

    result = tools.compile_circuit(
        CIRCUIT, NETWORK, output_path=str(destination), include_qasm=False
    )

    assert result["output_path"] == str(destination.resolve())
    assert destination.read_text().startswith("OPENQASM 3")
    assert "distributed_qasm" not in result


def test_verify_compilation_confirms_equivalence():
    result = tools.verify_compilation(CIRCUIT, NETWORK)

    assert result["method"] == "statevector"
    assert result["equivalent"] is True


def test_schedule_circuit_reports_makespan_and_writes_json(tmp_path):
    destination = tmp_path / "schedule.json"

    result = tools.schedule_circuit(
        "qft_n10", NETWORK, output_path=str(destination)
    )

    assert result["makespan"] > 0
    assert result["num_operations"] >= result["num_remote_operations"] > 0
    assert json.loads(destination.read_text())


def test_compare_partitioners_sorts_best_first():
    result = tools.compare_partitioners(
        "qft_n10", NETWORK, partitioners=["interaction", "benchmark_random"]
    )

    costs = [row["ebit_cost"] for row in result["results"]]
    assert result["sorted_by"] == "ebit_cost"
    assert costs == sorted(costs)
    assert {row["partitioner"] for row in result["results"]} == {
        "interaction",
        "benchmark_random",
    }


def test_compare_partitioners_reports_failures_last(monkeypatch):
    real_compile = tools._compile

    def flaky_compile(circuit, network, partitioner, kwargs):
        if partitioner == "benchmark_random":
            raise RuntimeError("boom")
        return real_compile(circuit, network, partitioner, kwargs)

    monkeypatch.setattr(tools, "_compile", flaky_compile)

    result = tools.compare_partitioners(
        CIRCUIT,
        NETWORK,
        partitioners=["benchmark_random", "interaction"],
        scheduler="fifo",
    )

    first, last = result["results"]
    assert result["sorted_by"] == "makespan"
    assert first["partitioner"] == "interaction"
    assert "makespan" in first
    assert last == {
        "partitioner": "benchmark_random",
        "error": "RuntimeError: boom",
    }


def test_describe_network_rejects_malformed_network():
    network = json.loads(network_path(NETWORK).read_text())
    network["qubits"]["c_1_0"]["remoteConnections"] = []

    with pytest.raises(ValueError, match="list it on both qubits"):
        tools.describe_network(json.dumps(network))


def test_build_network_returns_json_usable_by_other_tools():
    built = tools.build_network(3, computation_qubits_per_qpu=2)

    result = tools.compile_circuit(CIRCUIT, built["network_json"])

    assert built["num_qpus"] == 3
    assert built["communication_qubits_per_qpu"] == [2, 4, 2]
    assert result["num_qpus"] == 3


def test_build_network_sizes_qpus_from_circuit_qubits():
    built = tools.build_network(3, circuit_qubits=10, arrangement="ring")

    assert built["computation_qubits_per_qpu"] == [4, 4, 4]


def test_build_network_explicit_links_override_arrangement():
    built = tools.build_network(
        3,
        computation_qubits_per_qpu=2,
        arrangement="ring",
        qpu_links=[(0, 1), (0, 2)],
    )

    assert built["communication_qubits_per_qpu"] == [4, 2, 2]


def test_build_network_writes_output_file(tmp_path):
    destination = tmp_path / "net.json"

    built = tools.build_network(
        2, computation_qubits_per_qpu=3, output_path=str(destination)
    )

    assert built["output_path"] == str(destination.resolve())
    assert "network_json" not in built
    assert tools.describe_network(str(destination)) == {
        key: value for key, value in built.items() if key != "output_path"
    }


@pytest.mark.parametrize(
    "sizes",
    [{}, {"computation_qubits_per_qpu": 2, "circuit_qubits": 4}],
    ids=["neither", "both"],
)
def test_build_network_needs_exactly_one_size(sizes):
    with pytest.raises(ValueError, match="exactly one"):
        tools.build_network(2, **sizes)
