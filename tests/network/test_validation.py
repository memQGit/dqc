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
from pathlib import Path

import pytest

from memq_dqc.assets import list_networks, network_path
from memq_dqc.network import generate_network, validate_network

_FIXTURES = sorted(
    (Path(__file__).parents[1] / "fixtures" / "networks").glob("*.json")
)


@pytest.mark.parametrize(
    "path",
    [network_path(name) for name in list_networks()] + _FIXTURES,
    ids=lambda path: path.stem,
)
def test_known_good_networks_are_valid(path):
    validate_network(json.loads(path.read_text()))


def _qubit(network, qubit):
    return network["qubits"][qubit]


def _drop_back_link(network):
    _qubit(network, "c_1_0")["remoteConnections"] = []


def _link_unknown_qubit(network):
    _qubit(network, "c_0_0")["remoteConnections"] = ["c_9_9"]


def _remote_on_computation_qubit(network):
    _qubit(network, "q_0_0")["remoteConnections"] = ["q_1_0"]
    _qubit(network, "q_1_0")["remoteConnections"] = ["q_0_0"]


def _remote_within_one_qpu(network):
    _qubit(network, "c_0_0")["remoteConnections"] = ["c_0_1"]
    _qubit(network, "c_0_1")["remoteConnections"] = ["c_0_0"]


def _local_across_qpus(network):
    _qubit(network, "q_0_0")["localConnections"].append("q_1_0")
    _qubit(network, "q_1_0")["localConnections"].append("q_0_0")


def _drop_processor(network):
    del network["processors"]["1"]


def _mismatched_processor_id(network):
    _qubit(network, "q_0_0")["processorId"] = 1


def _bad_qubit_type(network):
    _qubit(network, "q_0_0")["type"] = "data"


def _non_numeric_qpu_key(network):
    network["processors"]["a"] = network["processors"].pop("1")


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (_drop_back_link, "not listed on 'c_1_0'"),
        (_link_unknown_qubit, "unknown qubit 'c_9_9'"),
        (_remote_on_computation_qubit, "Computation qubit 'q_0_0'"),
        (_remote_within_one_qpu, "same QPU"),
        (_local_across_qpus, "different QPUs"),
        (_drop_processor, "not listed under any QPU"),
        (_mismatched_processor_id, "processorId '1'"),
        (_bad_qubit_type, "type 'data'"),
        (_non_numeric_qpu_key, "not a numeric string"),
    ],
)
def test_rejects_malformed_networks(mutate, message):
    network = generate_network(2, 2)
    mutate(network)

    with pytest.raises(ValueError, match=message):
        validate_network(network)


def test_reports_every_problem_at_once():
    network = generate_network(2, 2)
    _drop_back_link(network)
    _bad_qubit_type(network)

    with pytest.raises(ValueError, match=r"\(2 problems\)"):
        validate_network(network)


@pytest.mark.parametrize("network", [{}, {"processors": {}, "qubits": {}}])
def test_rejects_missing_sections(network):
    with pytest.raises(ValueError, match="non-empty objects"):
        validate_network(network)
