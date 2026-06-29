"""Run the Experiment 1 EPR sweep: QV100 across 18 network topologies.

Experiment 1 holds the circuit fixed (Quantum Volume, 100 qubits) and varies
the network: **9 QPU counts (n = 2 … 10) × 2 intra-QPU connectivity variants**
(``all_to_all`` and ``nearest_neighbor``), for 18 topologies in total. Each
topology is partitioned with all four compiler strategies and the single
metric of interest — **EPR pairs used** (entanglement cost) — is collected.

Results are reported three ways so the 18 cases can be compared at a glance:

* a terminal **EPR matrix** per connectivity variant (rows = QPU count,
  columns = strategy),
* a flat **CSV** of every (topology, strategy) result, and
* the shared interactive **HTML dashboard** (EPR explorer).

Usage (run from repo root)::

    uv run python benchmarking/experiments/experiment_1/run_experiment_1.py
    uv run python benchmarking/experiments/experiment_1/run_experiment_1.py --qpus 2 --qpus 3
    uv run python benchmarking/experiments/experiment_1/run_experiment_1.py --variant all_to_all
    uv run python benchmarking/experiments/experiment_1/run_experiment_1.py --list-cases
"""

from __future__ import annotations

import argparse
import datetime
import logging
import re
import sys
from pathlib import Path

_EXPERIMENT_DIR = Path(__file__).resolve().parent
_CIRCUIT_PATH = (
    _EXPERIMENT_DIR.parents[1] / "benchmark_circuits" / "qv_100.qasm"
)
_COMPILER_BENCHMARKING_DIR = (
    _EXPERIMENT_DIR.parents[1] / "compiler_benchmarking"
)
_RESULTS_DIR = _EXPERIMENT_DIR / "results"

# Reuse the proven single-case runner and result model from the main
# compiler benchmark rather than duplicating the Partitioner plumbing.
sys.path.insert(0, str(_COMPILER_BENCHMARKING_DIR))
from run_compiler_benchmark import (  # noqa: E402
    DEFAULT_COMPILER_ALGORITHMS,
    DEFAULT_TIMEOUT_SECONDS,
    BenchmarkCase,
    CompilerBenchmarkResult,
    run_single_case,
    write_csv,
    write_html_dashboard,
)

_VARIANTS: tuple[str, ...] = ("all_to_all", "nearest_neighbor")

logger = logging.getLogger(__name__)


def discover_experiment_cases(
    experiment_dir: Path = _EXPERIMENT_DIR,
    circuit_path: Path = _CIRCUIT_PATH,
) -> list[BenchmarkCase]:
    """Discover the 18 Experiment 1 benchmark cases.

    Scans ``experiment_dir`` for ``nNN_*qpu/`` subfolders and pairs the QV100
    circuit with each connectivity-variant JSON found inside.

    Args:
        experiment_dir: Directory holding the ``nNN_*qpu`` topology folders.
        circuit_path: Path to the QV100 OpenQASM circuit.

    Returns:
        One :class:`BenchmarkCase` per (QPU count, connectivity variant),
        sorted by QPU count then variant.
    """
    cases: list[BenchmarkCase] = []
    for qpu_dir in sorted(experiment_dir.glob("n*qpu")):
        match = re.match(r"n0*(\d+)_\d+qpu", qpu_dir.name)
        if match is None:
            continue
        num_qpus = int(match.group(1))
        for variant in _VARIANTS:
            network_path = qpu_dir / f"{variant}.json"
            if not network_path.is_file():
                logger.warning("Missing %s — skipping.", network_path)
                continue
            topology = f"{variant}_n{num_qpus:02d}qpu"
            cases.append(
                BenchmarkCase(
                    name=f"qv_100__{topology}",
                    circuit_path=circuit_path,
                    network_path=network_path,
                    circuit_num_qubits=100,
                    network_topology=topology,
                    description=(f"QV100 on {num_qpus} QPUs ({variant})"),
                )
            )
    return cases


def _variant_of(topology: str) -> str:
    """Return the connectivity variant encoded in a topology name."""
    return topology.rsplit("_n", 1)[0]


def log_epr_matrix(
    results: list[CompilerBenchmarkResult],
    algorithms: list[str],
) -> None:
    """Print one EPR-pairs matrix per connectivity variant.

    Each matrix has one row per QPU count and one column per strategy, so
    scaling trends and cross-strategy comparisons are visible at a glance.
    The lowest EPR count in each row is marked with ``*``.

    Args:
        results: Benchmark results to display.
        algorithms: Strategy names in display (column) order.
    """
    if not results:
        logger.info("No results to display.")
        return

    # (variant, num_qpus, algorithm) -> epr pairs
    epr: dict[tuple[str, int, str], float] = {}
    for r in results:
        epr[(_variant_of(r.network_topology), r.num_qpus, r.algorithm)] = (
            r.epr_pairs
        )

    for variant in _VARIANTS:
        qpu_counts = sorted({q for (v, q, _) in epr if v == variant})
        if not qpu_counts:
            continue

        header = f"{'QPUs':>5} | " + " | ".join(
            f"{algo:>16}" for algo in algorithms
        )
        sep = "-" * len(header)
        logger.info("\n%s", "=" * len(header))
        logger.info("EPR pairs — %s", variant)
        logger.info(sep)
        logger.info(header)
        logger.info(sep)
        for q in qpu_counts:
            row_vals = [epr.get((variant, q, a)) for a in algorithms]
            present = [v for v in row_vals if v is not None]
            best = min(present) if present else None
            cells = []
            for v in row_vals:
                if v is None:
                    cells.append(f"{'—':>16}")
                else:
                    mark = "*" if best is not None and v == best else " "
                    cells.append(f"{v:>15.1f}{mark}")
            logger.info("%5d | %s", q, " | ".join(cells))
        logger.info(sep)
    logger.info("\n(* = lowest EPR cost in that row)")


def _run_suite(
    cases: list[BenchmarkCase],
    algorithms: list[str],
    timeout_seconds: float,
) -> list[CompilerBenchmarkResult]:
    """Run every case through every strategy, logging progress per run.

    Args:
        cases: Benchmark cases to run.
        algorithms: Strategy names to benchmark.
        timeout_seconds: Per-run wall-clock limit. Values <= 0 disable it.

    Returns:
        All successful benchmark results.
    """
    results: list[CompilerBenchmarkResult] = []
    total = len(cases) * len(algorithms)
    done = 0
    for case in cases:
        for algo in algorithms:
            done += 1
            logger.info("[%d/%d] %s — %s", done, total, case.description, algo)
            result = run_single_case(case, algo, timeout_seconds)
            if result is not None:
                results.append(result)
                logger.info("        → EPR pairs: %.1f", result.epr_pairs)
    return results


def _parse_args() -> argparse.Namespace:
    """Return parsed CLI arguments for the Experiment 1 runner."""
    parser = argparse.ArgumentParser(
        description=(
            "Run QV100 across the 18 Experiment 1 topologies for every "
            "compiler strategy and report EPR-pair costs."
        )
    )
    parser.add_argument(
        "--qpus",
        action="append",
        type=int,
        dest="qpus",
        metavar="N",
        help=(
            "Restrict to these QPU counts (2-10). Can be repeated. "
            "Defaults to all."
        ),
    )
    parser.add_argument(
        "--variant",
        action="append",
        dest="variants",
        choices=_VARIANTS,
        help=(
            "Restrict to a connectivity variant. Can be repeated. "
            "Defaults to both."
        ),
    )
    parser.add_argument(
        "--algo",
        action="append",
        dest="algos",
        metavar="ALGO",
        help=(
            "Strategy to benchmark. Can be repeated. "
            "Defaults to: " + ", ".join(DEFAULT_COMPILER_ALGORITHMS)
        ),
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List all discovered cases and exit.",
    )
    parser.add_argument(
        "--no-html",
        action="store_true",
        help="Skip HTML dashboard generation.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=DEFAULT_TIMEOUT_SECONDS,
        metavar="SECONDS",
        help=(
            "Per-run wall-clock limit. Defaults to "
            f"{DEFAULT_TIMEOUT_SECONDS:.0f}s. Use 0 to disable."
        ),
    )
    return parser.parse_args()


def main() -> None:
    """Run the Experiment 1 EPR sweep from the command line."""
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")

    cases = discover_experiment_cases()
    if args.qpus:
        wanted = set(args.qpus)
        cases = [
            c
            for c in cases
            if int(re.search(r"_n(\d+)qpu", c.network_topology).group(1))
            in wanted
        ]
    if args.variants:
        variants = set(args.variants)
        cases = [
            c for c in cases if _variant_of(c.network_topology) in variants
        ]

    if args.list_cases:
        for case in cases:
            print(f"{case.name}: {case.description}")
        return

    if not cases:
        logger.error("No cases matched the given filters.")
        return

    algos = args.algos or list(DEFAULT_COMPILER_ALGORITHMS)
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    slug = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("=" * 72)
    logger.info("memQ-DQC Experiment 1 — QV100 EPR sweep")
    logger.info("Timestamp  : %s", timestamp)
    logger.info("Topologies : %d", len(cases))
    logger.info("Strategies : %s", ", ".join(algos))
    logger.info("Total runs : %d", len(cases) * len(algos))
    logger.info(
        "Timeout    : %s",
        f"{args.timeout:.0f}s per run" if args.timeout > 0 else "disabled",
    )
    logger.info("=" * 72)

    results = _run_suite(cases, algos, args.timeout)
    if not results:
        logger.error("No successful results. Check errors above.")
        return

    log_epr_matrix(results, algos)

    write_csv(results, _RESULTS_DIR / f"experiment_1_{slug}.csv")
    if not args.no_html:
        write_html_dashboard(
            results,
            _RESULTS_DIR / f"experiment_1_{slug}.html",
            timestamp,
            algos,
        )


if __name__ == "__main__":
    main()
