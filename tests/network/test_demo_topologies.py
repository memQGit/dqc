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
from collections import Counter
from pathlib import Path

import pytest

from memq_dqc.network import NetworkGraph

DEMO_INPUTS = Path(__file__).resolve().parents[2] / "demo" / "inputs"


@pytest.mark.parametrize(
    ("name", "data_counts", "comm_counts", "qpu_links", "route"),
    [
        (
            "ring_4qpu",
            [4, 4, 4, 4],
            [4, 4, 4, 4],
            {(0, 1): 2, (0, 3): 2, (1, 2): 2, (2, 3): 2},
            [1, 0, 3],
        ),
        (
            "chain_3qpu",
            [6, 6, 6],
            [2, 4, 2],
            {(0, 1): 2, (1, 2): 2},
            [0, 1, 2],
        ),
    ],
)
def test_demo_topology(name, data_counts, comm_counts, qpu_links, route):
    path = DEMO_INPUTS / f"{name}.json"
    network = NetworkGraph(str(path))
    remote_edges = [
        (u, v)
        for u, v, data in network.graph.edges(data=True)
        if data["connection_type"] == "remote"
    ]

    assert network.comp_qubits_per_qpu() == data_counts
    assert (
        Counter(tuple(sorted((u.qpu_id, v.qpu_id))) for u, v in remote_edges)
        == qpu_links
    )

    # Every remote link must have its own endpoints. Counting links per
    # QPU pair alone would still allow two neighbors to share a port.
    assert Counter(q for edge in remote_edges for q in edge) == Counter(
        network.communication_qubits()
    )

    assert network.comm_qubits_per_qpu() == comm_counts

    start, _, end = route
    assert network.get_qpu_route(start, end) == route
    assert network.remote_gate_ebit_cost(start, end) == 3


@pytest.mark.parametrize("name", ["ring_4qpu", "chain_3qpu"])
def test_demo_connection_records_match_qubit_connections(name):
    path = DEMO_INPUTS / f"{name}.json"
    topology = json.loads(path.read_text(encoding="utf-8"))

    # NetworkGraph reads the per-qubit adjacency lists. Check the redundant
    # connection records too, and require exactly one declaration per direction.
    expected = Counter()
    for record in topology["connections"]:
        kind = record["type"]
        u, v = record["qubit1"], record["qubit2"]
        expected[(kind, u, v)] += 1
        expected[(kind, v, u)] += 1

    declared = Counter(
        (kind, source, target)
        for source, qubit in topology["qubits"].items()
        for kind in ("local", "remote")
        for target in qubit[f"{kind}Connections"]
    )
    assert all(count == 1 for count in expected.values())
    assert declared == expected
