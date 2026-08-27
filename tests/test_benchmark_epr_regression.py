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

"""Characterization tests pinning EPR-pair cost on representative cases.

WHY THIS EXISTS
---------------
EPR-pair cost is the headline metric of this project and the basis of the
published results tables. It is produced by a long chain -- partitioning,
gate grouping, link selection, remote-gate lowering -- and a change anywhere
in that chain silently moves it. That has already happened twice:

* ``34f06f8`` added equal-cost link balancing. Balancing handed consecutive
  members of a cat-entanglement group different communication qubits, so
  every group closed after its first gate and one e-bit pair was emitted per
  remote gate. QFT-18 on an all-to-all 2-QPU network went from 9 e-bits to
  162 -- an 18x regression that no test caught.
* ``6d3667a`` switched ``Partitioner.cost`` from a partition-time estimate to
  measured usage. For the two weeks between those commits the builder emitted
  162 while ``cost`` still reported 9, so the regression was invisible even to
  someone reading the number.

These tests pin the metric itself on a spread of circuits, topologies, and
partitioners, so any behavioral change shows up as a failing assertion naming
the exact case that moved.

WHEN A TEST HERE FAILS
----------------------
A failure is NOT automatically a bug -- a deliberate compiler improvement will
also move these numbers. It means: work out which change moved the value and
whether the new value is correct. If it is, update ``EXPECTED_EPR_COST`` in the
same commit as the change, and regenerate the results tables and figures that
depend on it. Never update a number here to make a red test green without
establishing why it moved.

WHAT IS COVERED
---------------
Three circuits of different structure (a multiplier, a QFT, an adder) across
all four network topologies and the four deterministic partitioners.
``benchmark_random`` is deliberately excluded: it is unseeded and its cost
swings by tens of percent between runs, so it cannot be pinned.

Fixtures live in ``tests/fixtures/benchmark`` -- copies of the benchmark suite
inputs, which are themselves gitignored. They are duplicated here so this runs
in CI for anyone with a clone.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from memq_dqc.partition.partitioner import Partitioner

_FIXTURES = Path(__file__).parent / "fixtures" / "benchmark"

# Circuit stem -> the per-qubit-count network directory it pairs with.
_NETWORK_DIR_FOR_CIRCUIT = {
    "multiply_n13_transpiled": "q013",
    "qft_n18_transpiled": "q018",
    "adder_n28_transpiled": "q028",
}

# (circuit, network topology, partitioner) -> EPR pairs consumed.
# Regenerate with tests/regenerate_epr_costs.py after an intended change.
EXPECTED_EPR_COST = {
    ("multiply_n13_transpiled", "fully_connected_2qpu", "hypergraph"): 8,
    ("multiply_n13_transpiled", "fully_connected_2qpu", "interaction"): 16,
    (
        "multiply_n13_transpiled",
        "fully_connected_2qpu",
        "interaction-static",
    ): 8,
    (
        "multiply_n13_transpiled",
        "fully_connected_2qpu",
        "benchmark_static",
    ): 16,
    ("multiply_n13_transpiled", "nearest_neighbor_2qpu", "hypergraph"): 14,
    ("multiply_n13_transpiled", "nearest_neighbor_2qpu", "interaction"): 19,
    (
        "multiply_n13_transpiled",
        "nearest_neighbor_2qpu",
        "interaction-static",
    ): 11,
    (
        "multiply_n13_transpiled",
        "nearest_neighbor_2qpu",
        "benchmark_static",
    ): 14,
    ("multiply_n13_transpiled", "ring_3qpu", "hypergraph"): 18,
    ("multiply_n13_transpiled", "ring_3qpu", "interaction"): 18,
    ("multiply_n13_transpiled", "ring_3qpu", "interaction-static"): 14,
    ("multiply_n13_transpiled", "ring_3qpu", "benchmark_static"): 22,
    ("multiply_n13_transpiled", "grid_4qpu", "hypergraph"): 27,
    ("multiply_n13_transpiled", "grid_4qpu", "interaction"): 40,
    ("multiply_n13_transpiled", "grid_4qpu", "interaction-static"): 27,
    ("multiply_n13_transpiled", "grid_4qpu", "benchmark_static"): 34,
    ("qft_n18_transpiled", "fully_connected_2qpu", "hypergraph"): 9,
    ("qft_n18_transpiled", "fully_connected_2qpu", "interaction"): 26,
    ("qft_n18_transpiled", "fully_connected_2qpu", "interaction-static"): 14,
    ("qft_n18_transpiled", "fully_connected_2qpu", "benchmark_static"): 13,
    ("qft_n18_transpiled", "nearest_neighbor_2qpu", "hypergraph"): 162,
    ("qft_n18_transpiled", "nearest_neighbor_2qpu", "interaction"): 141,
    ("qft_n18_transpiled", "nearest_neighbor_2qpu", "interaction-static"): 162,
    ("qft_n18_transpiled", "nearest_neighbor_2qpu", "benchmark_static"): 162,
    ("qft_n18_transpiled", "ring_3qpu", "hypergraph"): 216,
    ("qft_n18_transpiled", "ring_3qpu", "interaction"): 193,
    ("qft_n18_transpiled", "ring_3qpu", "interaction-static"): 214,
    ("qft_n18_transpiled", "ring_3qpu", "benchmark_static"): 216,
    ("qft_n18_transpiled", "grid_4qpu", "hypergraph"): 226,
    ("qft_n18_transpiled", "grid_4qpu", "interaction"): 205,
    ("qft_n18_transpiled", "grid_4qpu", "interaction-static"): 206,
    ("qft_n18_transpiled", "grid_4qpu", "benchmark_static"): 218,
    ("adder_n28_transpiled", "fully_connected_2qpu", "hypergraph"): 7,
    ("adder_n28_transpiled", "fully_connected_2qpu", "interaction"): 23,
    ("adder_n28_transpiled", "fully_connected_2qpu", "interaction-static"): 7,
    ("adder_n28_transpiled", "fully_connected_2qpu", "benchmark_static"): 98,
    ("adder_n28_transpiled", "nearest_neighbor_2qpu", "hypergraph"): 11,
    ("adder_n28_transpiled", "nearest_neighbor_2qpu", "interaction"): 33,
    (
        "adder_n28_transpiled",
        "nearest_neighbor_2qpu",
        "interaction-static",
    ): 13,
    ("adder_n28_transpiled", "nearest_neighbor_2qpu", "benchmark_static"): 106,
    ("adder_n28_transpiled", "ring_3qpu", "hypergraph"): 2,
    ("adder_n28_transpiled", "ring_3qpu", "interaction"): 67,
    ("adder_n28_transpiled", "ring_3qpu", "interaction-static"): 23,
    ("adder_n28_transpiled", "ring_3qpu", "benchmark_static"): 141,
    ("adder_n28_transpiled", "grid_4qpu", "hypergraph"): 33,
    ("adder_n28_transpiled", "grid_4qpu", "interaction"): 117,
    ("adder_n28_transpiled", "grid_4qpu", "interaction-static"): 83,
    ("adder_n28_transpiled", "grid_4qpu", "benchmark_static"): 182,
}


def _compile(circuit: str, topology: str, algorithm: str) -> Partitioner:
    network_dir = _NETWORK_DIR_FOR_CIRCUIT[circuit]
    partitioner = Partitioner(
        str(_FIXTURES / "networks" / network_dir / f"{topology}.json"),
        str(_FIXTURES / "circuits" / f"{circuit}.qasm"),
        algo=algorithm,
    )
    partitioner.run(ebit_assignment=True, verbosity="quiet")
    return partitioner


@pytest.mark.parametrize(
    ("circuit", "topology", "algorithm", "expected"),
    [
        pytest.param(*key, value, id=f"{key[0]}-{key[1]}-{key[2]}")
        for key, value in EXPECTED_EPR_COST.items()
    ],
)
def test_epr_cost_is_unchanged(
    circuit: str, topology: str, algorithm: str, expected: int
) -> None:
    """Pin EPR-pair cost per (circuit, topology, partitioner)."""
    partitioner = _compile(circuit, topology, algorithm)

    assert partitioner.cost == pytest.approx(expected), (
        f"EPR cost for {circuit} / {topology} / {algorithm} moved from "
        f"{expected} to {partitioner.cost:.0f}. Establish which change moved "
        "it and whether the new value is correct before updating this table; "
        "the published results tables depend on these numbers."
    )


def test_epr_cost_is_stable_across_repeated_compiles() -> None:
    """The deterministic partitioners must not vary run to run.

    Guards the assumption that makes the table above meaningful. It excludes
    ``benchmark_random``, which is unseeded and genuinely does vary.
    """
    costs = {
        _compile("qft_n18_transpiled", "ring_3qpu", "hypergraph").cost
        for _ in range(3)
    }

    assert len(costs) == 1


def test_all_to_all_intra_qpu_enables_gate_grouping() -> None:
    """All-to-all groups remote gates; nearest-neighbor cannot.

    This is the property ``34f06f8`` broke, and it is the mechanism behind the
    intra-QPU connectivity comparison in the paper. On an all-to-all QPU one
    cat-entangled communication qubit reaches every target, so a whole group of
    remote gates shares one catent/catdisent pair. On a nearest-neighbor QPU
    most remote gates first need local SWAPs to bring the target adjacent, and
    a gate that adds SWAPs cannot join a group, so each pays its own e-bit
    pair.

    Asserted as a strict inequality plus a SWAP-count check rather than exact
    values, so it keeps testing the mechanism even if the numbers move.
    """
    grouped = _compile(
        "qft_n18_transpiled", "fully_connected_2qpu", "hypergraph"
    )
    ungrouped = _compile(
        "qft_n18_transpiled", "nearest_neighbor_2qpu", "hypergraph"
    )

    remote_gates = grouped.distributed_circuit.num_remote_gates
    assert remote_gates == ungrouped.distributed_circuit.num_remote_gates

    # All-to-all needs no routing, so every group runs its full length.
    assert grouped.distributed_circuit.num_local_swaps_added == 0
    assert grouped.cost < remote_gates / 2

    # Nearest-neighbor routes, which breaks groups at each SWAP-adding gate.
    assert ungrouped.distributed_circuit.num_local_swaps_added > 0
    assert ungrouped.cost == pytest.approx(remote_gates)
