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
import math
import re

import pytest

from memq_dqc import Compiler
from memq_dqc.assets import list_networks, network_path
from memq_dqc.network import NetworkGraph, generate_network, validate_network

FOUR_QUBIT_CIRCUIT = """OPENQASM 3.0;
include "stdgates.inc";
qubit[4] q;
bit[4] c;
h q[0];
cx q[0], q[3];
cx q[1], q[2];
cx q[0], q[1];
cx q[2], q[3];
c[0] = measure q[0];
c[1] = measure q[1];
c[2] = measure q[2];
c[3] = measure q[3];
"""

_BUNDLED_ARRANGEMENTS = {
    "pair": "chain",
    "chain": "chain",
    "ring": "ring",
    "hub": "hub",
}
_BUNDLED_INTRA = {"nn": "nearest_neighbor", "a2a": "all_to_all"}


def _comm_counts(network):
    return [
        len(processor["qubits"]["communication"])
        for processor in network["processors"].values()
    ]


@pytest.mark.parametrize("name", list_networks())
def test_reproduces_every_bundled_network(name):
    size, stem = name.split("/")
    circuit_qubits = int(size.split("_")[0])
    match = re.fullmatch(r"n(\d+)_(\w+)_(nn|a2a)", stem)
    assert match is not None
    num_qpus = int(match[1])

    network = generate_network(
        num_qpus,
        math.ceil(circuit_qubits / num_qpus),
        _BUNDLED_ARRANGEMENTS[match[2]],
        intra_qpu=_BUNDLED_INTRA[match[3]],
    )

    assert network == json.loads(network_path(name).read_text())


@pytest.mark.parametrize(
    ("num_qpus", "arrangement", "expected"),
    [
        (1, "chain", [0]),
        (3, "chain", [2, 4, 2]),
        (4, "ring", [4, 4, 4, 4]),
        (4, "hub", [6, 2, 2, 2]),
        (4, "all_to_all", [6, 6, 6, 6]),
        (3, [(0, 2), (2, 1)], [2, 2, 4]),
    ],
)
def test_allocates_links_per_pair_comm_qubits_per_neighbour(
    num_qpus, arrangement, expected
):
    network = generate_network(num_qpus, 3, arrangement)

    assert _comm_counts(network) == expected


def test_links_per_pair_scales_comm_qubits():
    network = generate_network(3, 3, "chain", links_per_pair=3)

    assert _comm_counts(network) == [3, 6, 3]


def test_explicit_links_in_walk_order_match_named_arrangement():
    assert generate_network(4, 3, [(0, 1), (1, 2), (2, 3), (3, 0)]) == (
        generate_network(4, 3, "ring")
    )


def test_duplicate_explicit_links_are_ignored():
    assert generate_network(2, 3, [(0, 1), (1, 0)]) == generate_network(2, 3)


@pytest.mark.parametrize("arrangement", ["chain", "ring", "hub", "all_to_all"])
@pytest.mark.parametrize("intra_qpu", ["nearest_neighbor", "all_to_all"])
def test_generated_networks_are_valid(arrangement, intra_qpu):
    network = generate_network(5, 7, arrangement, intra_qpu=intra_qpu)

    validate_network(network)


@pytest.mark.parametrize("arrangement", ["chain", "ring", "hub", "all_to_all"])
def test_generated_networks_compile_correctly(tmp_path, arrangement):
    path = tmp_path / "network.json"
    path.write_text(json.dumps(generate_network(4, 2, arrangement)))
    compiler = Compiler(FOUR_QUBIT_CIRCUIT, NetworkGraph(str(path)))

    compiler.compile()

    assert compiler.verify(shots=20000)


@pytest.mark.parametrize(
    ("args", "kwargs", "message"),
    [
        ((0, 3), {}, "num_qpus"),
        ((2, 0), {}, "computation_qubits_per_qpu"),
        ((2, 3), {"links_per_pair": 0}, "links_per_pair"),
        ((2, 3, "ring"), {}, "at least 3 QPUs"),
        ((2, 3, "star"), {}, "Unknown arrangement"),
        ((2, 3), {"intra_qpu": "grid"}, "Unknown intra_qpu"),
        ((2, 3, [(0, 0)]), {}, "to itself"),
        ((2, 3, [(0, 2)]), {}, "outside"),
        ((3, 3, [(0, 1)]), {}, "unreachable"),
    ],
)
def test_rejects_invalid_parameters(args, kwargs, message):
    with pytest.raises(ValueError, match=message):
        generate_network(*args, **kwargs)
