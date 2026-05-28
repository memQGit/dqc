"""Run compiler benchmarks for different partitioning algorithms.

This script compares the entanglement cost of different partitioning algorithms
across a selection of circuits and network topologies.

Costs are counted based on the exact catent/disent pairs produced by the
distributed circuit extractor.
"""

from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

from memq_dqc.partition import Partitioner

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPILER_ALGORITHMS: tuple[str, ...] = (
    "interaction",
    "hypergraph",
    "benchmark_static",
    "benchmark_random",
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class CompilerBenchmarkResult:
    """Benchmark output for one compiler run.

    Attributes:
        algorithm: Compiler (partitioner) registry name.
        cost: Final exact entanglement cost (e-bit pairs).
        num_windows: Number of partitioning windows.
        runtime: Time taken by the partitioning algorithm.
    """

    algorithm: str
    cost: float
    num_windows: int
    runtime: float


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One named compiler benchmark input.

    Attributes:
        name: Short terminal-friendly case identifier.
        circuit_path: OpenQASM benchmark input.
        network_path: Network benchmark input.
        description: Plain-text summary of what the case is meant to stress.
    """

    name: str
    circuit_path: Path
    network_path: Path
    description: str


BENCHMARK_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        name="qv_12_line",
        circuit_path=(
            REPO_ROOT / "benchmarking" / "circuits" / "qv_12_line_seed7.qasm"
        ),
        network_path=(
            REPO_ROOT
            / "benchmarking"
            / "networks"
            / "line_4qpu_3qubits_each.json"
        ),
        description=(
            "Seeded 12-qubit quantum volume circuit on a four-QPU line "
            "topology."
        ),
    ),
    BenchmarkCase(
        name="inter_swap_chain",
        circuit_path=(
            REPO_ROOT / "benchmarking" / "circuits" / "inter_swap_test.qasm"
        ),
        network_path=(
            REPO_ROOT / "benchmarking" / "networks" / "3comp_1comm_x2.json"
        ),
        description=("6-qubit chain-like example on a two-QPU network."),
    ),
    BenchmarkCase(
        name="critical_path_contention",
        circuit_path=(
            REPO_ROOT
            / "benchmarking"
            / "circuits"
            / "critical_path_contention.qasm"
        ),
        network_path=(
            REPO_ROOT / "benchmarking" / "networks" / "3comp_1comm_x2.json"
        ),
        description=(
            "Two remote CX branches on a single-link topology, with extra "
            "dependent work on one branch."
        ),
    ),
)


def parse_args() -> argparse.Namespace:
    """Return parsed CLI arguments for the benchmark runner."""
    parser = argparse.ArgumentParser(
        description="Benchmark compiler algorithms across distributed circuits."
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help="Benchmark case name to run. Defaults to all built-in cases.",
    )
    parser.add_argument(
        "--algo",
        action="append",
        dest="algos",
        help="Compiler algorithm to benchmark. Defaults to all built-in algos.",
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List available benchmark cases and exit.",
    )
    return parser.parse_args()


def configure_logging() -> None:
    """Configure terminal logging for the benchmark run."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def _display_path(path: Path) -> str:
    """Return a readable path, relative to the repo when possible."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def resolve_cases(
    selected_case_names: list[str] | None,
) -> list[BenchmarkCase]:
    """Return the requested benchmark cases by name."""
    if not selected_case_names:
        return list(BENCHMARK_CASES)

    available_cases = {case.name: case for case in BENCHMARK_CASES}
    return [
        available_cases[name]
        for name in selected_case_names
        if name in available_cases
    ]


def benchmark_compiler_algorithms(
    case: BenchmarkCase,
    algorithms: list[str],
) -> list[CompilerBenchmarkResult]:
    """Run one benchmark case through the requested compiler algorithms."""
    results: list[CompilerBenchmarkResult] = []

    for algorithm in algorithms:
        logger.info("Running algorithm: %s", algorithm)
        try:
            partitioner = Partitioner(
                str(case.network_path),
                str(case.circuit_path),
                algo=algorithm,
            )
            # Run partitioning and ebit assignment to get exact cost
            from memq_dqc._logging import StepTimer

            timer = StepTimer()
            partitioner.run(ebit_assignment=True, verbosity="quiet")
            runtime = timer.elapsed_seconds()

            cost = partitioner.cost
            if cost is None:
                logger.warning(
                    "Algorithm %s did not report a cost.", algorithm
                )
                cost = 0.0

            results.append(
                CompilerBenchmarkResult(
                    algorithm=algorithm,
                    cost=cost,
                    num_windows=len(partitioner.windows or []),
                    runtime=runtime,
                )
            )
        except Exception as exc:
            logger.error("Algorithm %s failed: %s", algorithm, exc)

    return results


def log_benchmark_results(
    case: BenchmarkCase, results: list[CompilerBenchmarkResult]
) -> None:
    """Print benchmark results in a table format."""
    if not results:
        return

    logger.info("\nResults for case: %s", case.name)
    logger.info(
        "%-20s | %10s | %10s | %10s",
        "Algorithm",
        "Cost",
        "Windows",
        "Runtime (s)",
    )
    logger.info("-" * 60)
    for r in results:
        logger.info(
            "%-20s | %10.1f | %10d | %10.3f",
            r.algorithm,
            r.cost,
            r.num_windows,
            r.runtime,
        )


def main() -> None:
    """Run the compiler benchmark from the command line."""
    args = parse_args()
    if args.list_cases:
        for case in BENCHMARK_CASES:
            print(f"{case.name}: {case.description}")
        return

    configure_logging()
    cases = resolve_cases(args.cases)
    algos = args.algos or list(DEFAULT_COMPILER_ALGORITHMS)

    for case in cases:
        logger.info("\n" + "=" * 72)
        logger.info("Case: %s", case.name)
        logger.info("Description: %s", case.description)
        logger.info("Circuit: %s", _display_path(case.circuit_path))
        logger.info("Network: %s", _display_path(case.network_path))

        results = benchmark_compiler_algorithms(case, algos)
        log_benchmark_results(case, results)


if __name__ == "__main__":
    main()
