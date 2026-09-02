"""Regenerate the EXPECTED_EPR_COST table for the EPR regression tests.

Run this ONLY after establishing that a compiler change legitimately moved the
metric, then paste the output into tests/test_benchmark_epr_regression.py in
the same commit as that change.

Usage: uv run python tests/regenerate_epr_costs.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from test_benchmark_epr_regression import (  # noqa: E402
    _NETWORK_DIR_FOR_CIRCUIT,
    EXPECTED_EPR_COST,
    _compile,
)

TOPOLOGIES = [
    "fully_connected_2qpu",
    "nearest_neighbor_2qpu",
    "ring_3qpu",
    "grid_4qpu",
]
ALGORITHMS = [
    "hypergraph",
    "interaction",
    "interaction-static",
    "benchmark_static",
]


def main() -> None:
    print("EXPECTED_EPR_COST = {")
    for circuit in _NETWORK_DIR_FOR_CIRCUIT:
        for topology in TOPOLOGIES:
            for algorithm in ALGORITHMS:
                cost = _compile(circuit, topology, algorithm).cost
                old = EXPECTED_EPR_COST.get((circuit, topology, algorithm))
                mark = "" if old == cost else f"  # was {old}"
                print(
                    f'    ("{circuit}", "{topology}", '
                    f'"{algorithm}"): {cost:.0f},{mark}'
                )
    print("}")


if __name__ == "__main__":
    main()
