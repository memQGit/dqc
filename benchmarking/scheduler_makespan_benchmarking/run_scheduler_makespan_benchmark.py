"""Benchmark makespan for the DES-based schedulers.

Discovers QASM circuits and network topologies from the
``benchmarking/benchmark_circuits`` and ``benchmarking/benchmark_networks``
directories (the same suite the compiler benchmark uses), compiles each
(circuit, topology) pair into a distributed circuit with the fixed
``interaction`` partitioner, then runs each DES scheduler on that circuit
and reports the results as a terminal table, CSV file, and an interactive
HTML dashboard.

The only metric in scope is **makespan**. Because the DES schedulers are
stochastic, each (case, algorithm) pair is run over several seeds and the
mean, standard deviation, min, and max makespan are reported. The
distributed circuit is compiled once per case and reused across all seeds
and all schedulers.

Usage (run from repo root)::

    uv run python benchmarking/scheduler_makespan_benchmarking/run_scheduler_makespan_benchmark.py
    uv run python benchmarking/scheduler_makespan_benchmarking/run_scheduler_makespan_benchmark.py --seeds 20
    uv run python benchmarking/scheduler_makespan_benchmarking/run_scheduler_makespan_benchmark.py --algo des_link_fifo --algo des_link_critical_path
    uv run python benchmarking/scheduler_makespan_benchmarking/run_scheduler_makespan_benchmark.py --list-cases
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import logging
import re
import signal
import statistics
from collections import defaultdict
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from statistics import mean
from types import FrameType

from memq_dqc.circuit import DistributedCircuit
from memq_dqc.network import NetworkGraph
from memq_dqc.partition import Partitioner
from memq_dqc.preprocessing.qasm.io import load_qasm_program
from memq_dqc.scheduler import Scheduler, SchedulerHardwareProfile
from memq_dqc.settings import load_settings

_BENCHMARKING_ROOT = Path(__file__).resolve().parents[1]
_BENCHMARK_CIRCUITS_DIR = _BENCHMARKING_ROOT / "benchmark_circuits"
_BENCHMARK_NETWORKS_DIR = _BENCHMARKING_ROOT / "benchmark_networks"
_RESULTS_DIR = Path(__file__).resolve().parent / "results"

# The compiler stage is held constant; it is not what we are benchmarking.
DEFAULT_COMPILER_ALGO = "interaction"

DEFAULT_DES_ALGORITHMS: tuple[str, ...] = (
    "des_link_fifo",
    "des_link_shortest_duration",
    "des_link_critical_path",
)

# Default number of stochastic seeds per (case, algorithm) pair.
DEFAULT_NUM_SEEDS: int = 10
DEFAULT_BASE_SEED: int = 0

# Per-run wall-clock limit for a single compile or a single scheduler run.
DEFAULT_TIMEOUT_SECONDS: float = 300.0

logger = logging.getLogger(__name__)


@contextmanager
def _time_limit(seconds: float) -> Iterator[None]:
    """Raise TimeoutError if the wrapped block runs longer than ``seconds``.

    Implemented with ``SIGALRM``, so it only interrupts code running on the
    main thread of a Unix-like platform. A long-running C extension call that
    never returns to the Python interpreter may delay the interrupt until it
    completes. A non-positive ``seconds`` (or a platform without ``SIGALRM``)
    disables the limit.

    Args:
        seconds: Wall-clock limit in seconds. Values <= 0 disable the limit.

    Yields:
        Control to the wrapped block.

    Raises:
        TimeoutError: If the block runs longer than ``seconds``.
    """
    if seconds <= 0 or not hasattr(signal, "SIGALRM"):
        yield
        return

    def _handler(signum: int, frame: FrameType | None) -> None:
        raise TimeoutError(f"exceeded {seconds:.0f}s time limit")

    previous_handler = signal.signal(signal.SIGALRM, _handler)
    signal.setitimer(signal.ITIMER_REAL, seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


@dataclass(frozen=True, slots=True)
class MakespanStats:
    """Summary statistics for a set of makespan samples.

    Attributes:
        mean: Mean makespan across seeds (primary displayed value).
        std: Sample standard deviation across seeds (0.0 for one sample).
        min: Smallest observed makespan.
        max: Largest observed makespan.
    """

    mean: float
    std: float
    min: float
    max: float


@dataclass(frozen=True, slots=True)
class MakespanBenchmarkResult:
    """Aggregated makespan metrics for one (case, algorithm) pair.

    Attributes:
        circuit_name: Filename stem of the benchmark circuit.
        circuit_num_qubits: Qubit count extracted from the circuit filename.
        network_topology: Network topology filename stem (e.g. ``ring_3qpu``).
        num_qpus: Number of QPUs in the benchmark network.
        algorithm: DES scheduler registry name.
        num_seeds: Number of seeds that produced a makespan.
        makespan_mean: Mean makespan across seeds (primary metric).
        makespan_std: Sample standard deviation of makespan across seeds.
        makespan_min: Smallest observed makespan.
        makespan_max: Largest observed makespan.
        seed_makespans: Per-seed makespans paired with their seed value.
    """

    circuit_name: str
    circuit_num_qubits: int
    network_topology: str
    num_qpus: int
    algorithm: str
    num_seeds: int
    makespan_mean: float
    makespan_std: float
    makespan_min: float
    makespan_max: float
    seed_makespans: tuple[tuple[int, float], ...]


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One named scheduler makespan benchmark input.

    Attributes:
        name: Short identifier combining circuit stem and topology.
        circuit_path: Path to the OpenQASM input circuit.
        network_path: Path to the JSON network topology.
        circuit_num_qubits: Qubit count implied by the circuit filename.
        network_topology: Network topology name (filename stem).
        description: Plain-text summary of this case.
    """

    name: str
    circuit_path: Path
    network_path: Path
    circuit_num_qubits: int
    network_topology: str
    description: str


# ── Discovery ────────────────────────────────────────────────────────────────


def _extract_qubit_count(stem: str) -> int | None:
    """Return the qubit count embedded in a circuit filename stem.

    Tries ``_nN`` first (e.g. ``qft_n18_transpiled`` → 18), then falls
    back to a trailing ``_N`` pattern (e.g. ``qv_100`` → 100).

    Args:
        stem: Circuit filename without extension.

    Returns:
        Extracted qubit count, or ``None`` if no pattern matched.
    """
    m = re.search(r"_n(\d+)", stem)
    if m:
        return int(m.group(1))
    m = re.search(r"_(\d+)$", stem)
    if m:
        return int(m.group(1))
    return None


def discover_benchmark_cases(
    circuits_dir: Path = _BENCHMARK_CIRCUITS_DIR,
    networks_dir: Path = _BENCHMARK_NETWORKS_DIR,
) -> list[BenchmarkCase]:
    """Discover benchmark cases by pairing circuits with matching networks.

    Scans ``circuits_dir`` for ``.qasm`` files, extracts the qubit count
    from each filename, and looks up the corresponding
    ``{N}_qubits/`` subdirectory in ``networks_dir``.

    Args:
        circuits_dir: Directory containing benchmark QASM circuits.
        networks_dir: Root directory of per-qubit-count network folders.

    Returns:
        One :class:`BenchmarkCase` per (circuit, network topology) pair,
        sorted by circuit name then topology name.
    """
    cases: list[BenchmarkCase] = []
    for circuit_path in sorted(circuits_dir.glob("*.qasm")):
        num_qubits = _extract_qubit_count(circuit_path.stem)
        if num_qubits is None:
            logger.warning(
                "Skipping %s: could not extract qubit count.",
                circuit_path.name,
            )
            continue
        network_dir = networks_dir / f"{num_qubits}_qubits"
        if not network_dir.is_dir():
            logger.warning(
                "Skipping %s: no network directory at %s.",
                circuit_path.name,
                network_dir,
            )
            continue
        for network_path in sorted(network_dir.glob("*.json")):
            topology = network_path.stem
            cases.append(
                BenchmarkCase(
                    name=f"{circuit_path.stem}__{topology}",
                    circuit_path=circuit_path,
                    network_path=network_path,
                    circuit_num_qubits=num_qubits,
                    network_topology=topology,
                    description=(
                        f"{circuit_path.stem} ({num_qubits}q) on {topology}"
                    ),
                )
            )
    return cases


# ── Aggregation ───────────────────────────────────────────────────────────────


def aggregate_makespans(makespans: Sequence[float]) -> MakespanStats:
    """Return mean, std, min, and max for a set of makespan samples.

    The standard deviation is the sample standard deviation; it is reported
    as ``0.0`` when only a single sample is provided (no variability).

    Args:
        makespans: One makespan per seed. Must be non-empty.

    Returns:
        Summary statistics across the provided samples.

    Raises:
        ValueError: If ``makespans`` is empty.
    """
    if not makespans:
        raise ValueError("Cannot aggregate an empty makespan sequence.")
    values = list(makespans)
    std = statistics.stdev(values) if len(values) > 1 else 0.0
    return MakespanStats(
        mean=mean(values),
        std=std,
        min=min(values),
        max=max(values),
    )


# ── Execution ────────────────────────────────────────────────────────────────


def _seed_sequence(num_seeds: int, base_seed: int) -> list[int]:
    """Return a deterministic seed sequence for one benchmark run.

    Args:
        num_seeds: Number of seeds to generate.
        base_seed: First seed; subsequent seeds increment by one.

    Returns:
        The list ``[base_seed, base_seed + 1, ...]`` of length ``num_seeds``.
    """
    return [base_seed + offset for offset in range(num_seeds)]


def compile_distributed_circuit(
    case: BenchmarkCase,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> tuple[DistributedCircuit, int] | None:
    """Compile one benchmark case into a distributed circuit.

    The circuit is compiled once with the fixed ``interaction`` partitioner
    so the same distributed circuit can be reused across every seed and
    every DES scheduler.

    Args:
        case: Benchmark circuit / network pair.
        timeout_seconds: Wall-clock limit for the compile. Values <= 0
            disable it.

    Returns:
        A ``(distributed_circuit, num_qpus)`` tuple, or ``None`` if the
        compile exceeded the time limit or raised an exception.
    """
    try:
        with _time_limit(timeout_seconds):
            qasm_program = load_qasm_program(str(case.circuit_path))
            network_graph = NetworkGraph(str(case.network_path))
            partitioner = Partitioner(
                network_graph,
                qasm_program,
                algo=DEFAULT_COMPILER_ALGO,
            )
            partitioner.run(verbosity="quiet", ebit_assignment=False)
            distributed_circuit = partitioner.circuit.distributed
            if distributed_circuit is None:
                raise RuntimeError("Distributed circuit was not created.")
            return distributed_circuit, network_graph.num_qpus
    except TimeoutError:
        logger.error(
            "TIMEOUT compile %-36s  %-24s: exceeded %.0fs limit",
            case.circuit_path.stem,
            case.network_topology,
            timeout_seconds,
        )
        return None
    except Exception as exc:
        logger.error(
            "FAILED  compile %-36s  %-24s: %s",
            case.circuit_path.stem,
            case.network_topology,
            exc,
        )
        return None


def _collect_makespans(
    distributed_circuit: DistributedCircuit,
    algorithm: str,
    seeds: Sequence[int],
    profile: SchedulerHardwareProfile,
    timeout_seconds: float,
) -> list[tuple[int, float]]:
    """Run one DES scheduler over several seeds and collect makespans.

    Args:
        distributed_circuit: Distributed circuit shared across all seeds.
        algorithm: DES scheduler registry name.
        seeds: Deterministic seed sequence to run.
        profile: Scheduler hardware profile shared across all runs.
        timeout_seconds: Per-seed wall-clock limit. Values <= 0 disable it.

    Returns:
        One ``(seed, makespan)`` tuple per seed that produced a schedule.
        Seeds that time out or raise are logged and omitted.
    """
    seed_makespans: list[tuple[int, float]] = []
    for seed in seeds:
        try:
            with _time_limit(timeout_seconds):
                scheduler = Scheduler(
                    distributed_circuit,
                    algo=algorithm,
                    profile=profile,
                    algo_kwargs={"seed": seed},
                )
                scheduler.run(verbosity="quiet")
                schedule = scheduler.schedule
                if schedule is None:
                    raise RuntimeError(
                        f"Scheduler {algorithm!r} produced no schedule."
                    )
                seed_makespans.append((seed, float(schedule.makespan)))
        except TimeoutError:
            logger.error(
                "TIMEOUT %-28s seed=%d: exceeded %.0fs limit",
                algorithm,
                seed,
                timeout_seconds,
            )
        except Exception as exc:
            logger.error(
                "FAILED  %-28s seed=%d: %s",
                algorithm,
                seed,
                exc,
            )
    return seed_makespans


def run_single_case(
    case: BenchmarkCase,
    algorithms: Sequence[str],
    num_seeds: int,
    base_seed: int,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[MakespanBenchmarkResult]:
    """Compile one case and benchmark every DES scheduler over seeds.

    Args:
        case: Benchmark circuit / network pair.
        algorithms: DES scheduler registry names to benchmark.
        num_seeds: Number of seeds per algorithm.
        base_seed: First seed in the deterministic seed sequence.
        timeout_seconds: Per-run wall-clock limit. Values <= 0 disable it.

    Returns:
        One :class:`MakespanBenchmarkResult` per algorithm that produced at
        least one makespan. Empty if the case failed to compile.
    """
    compiled = compile_distributed_circuit(case, timeout_seconds)
    if compiled is None:
        return []
    distributed_circuit, num_qpus = compiled

    profile = SchedulerHardwareProfile.neutral_atom(
        entanglement_profile="neutral_atom.polarization",
    )
    seeds = _seed_sequence(num_seeds, base_seed)

    results: list[MakespanBenchmarkResult] = []
    for algorithm in algorithms:
        seed_makespans = _collect_makespans(
            distributed_circuit,
            algorithm,
            seeds,
            profile,
            timeout_seconds,
        )
        if not seed_makespans:
            logger.error(
                "No makespans for %s on %s — skipping algorithm.",
                case.name,
                algorithm,
            )
            continue
        stats = aggregate_makespans([m for _, m in seed_makespans])
        results.append(
            MakespanBenchmarkResult(
                circuit_name=case.circuit_path.stem,
                circuit_num_qubits=case.circuit_num_qubits,
                network_topology=case.network_topology,
                num_qpus=num_qpus,
                algorithm=algorithm,
                num_seeds=len(seed_makespans),
                makespan_mean=stats.mean,
                makespan_std=stats.std,
                makespan_min=stats.min,
                makespan_max=stats.max,
                seed_makespans=tuple(seed_makespans),
            )
        )
    return results


def run_benchmark_suite(
    cases: Sequence[BenchmarkCase],
    algorithms: Sequence[str],
    num_seeds: int,
    base_seed: int,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[MakespanBenchmarkResult]:
    """Run every case through every DES scheduler and return all results.

    Args:
        cases: Benchmark cases to run.
        algorithms: DES scheduler registry names to benchmark.
        num_seeds: Number of seeds per (case, algorithm) pair.
        base_seed: First seed in the deterministic seed sequence.
        timeout_seconds: Per-run wall-clock limit. Values <= 0 disable it.

    Returns:
        All successful benchmark results across every case.
    """
    results: list[MakespanBenchmarkResult] = []
    total = len(cases)
    for index, case in enumerate(cases, start=1):
        logger.info("[%d/%d] %s", index, total, case.description)
        results.extend(
            run_single_case(
                case,
                algorithms,
                num_seeds,
                base_seed,
                timeout_seconds,
            )
        )
    return results


# ── Terminal output ───────────────────────────────────────────────────────────


def _time_unit() -> str:
    """Return the configured makespan time unit, or a neutral fallback."""
    return load_settings().global_settings.time_unit or "time units"


def log_terminal_table(results: Sequence[MakespanBenchmarkResult]) -> None:
    """Print all results as a grouped terminal table.

    Groups rows by circuit and topology. Within each group, rows are
    sorted by mean makespan ascending so the best algorithm appears first.

    Args:
        results: Benchmark results to display.
    """
    if not results:
        logger.info("No results to display.")
        return

    unit = _time_unit()
    grouped: dict[tuple[str, str], list[MakespanBenchmarkResult]] = (
        defaultdict(list)
    )
    for r in results:
        grouped[(r.circuit_name, r.network_topology)].append(r)

    col = (
        f"{'Algorithm':<28} | {'Mean':>12} | {'Std':>10} | "
        f"{'Min':>12} | {'Max':>12} | {'Seeds':>5}"
    )
    sep = "-" * len(col)

    for (circuit, topology), group in sorted(grouped.items()):
        logger.info("\n%s", "=" * len(col))
        logger.info("Circuit  : %s", circuit)
        logger.info("Topology : %s  (%d QPUs)", topology, group[0].num_qpus)
        logger.info("Makespan unit : %s", unit)
        logger.info(sep)
        logger.info(col)
        logger.info(sep)
        for r in sorted(group, key=lambda x: x.makespan_mean):
            logger.info(
                "%-28s | %12.3f | %10.3f | %12.3f | %12.3f | %5d",
                r.algorithm,
                r.makespan_mean,
                r.makespan_std,
                r.makespan_min,
                r.makespan_max,
                r.num_seeds,
            )


# ── CSV output ────────────────────────────────────────────────────────────────


_CSV_FIELDNAMES: tuple[str, ...] = (
    "circuit_name",
    "circuit_num_qubits",
    "network_topology",
    "num_qpus",
    "algorithm",
    "num_seeds",
    "makespan_mean",
    "makespan_std",
    "makespan_min",
    "makespan_max",
)


def write_csv(
    results: Sequence[MakespanBenchmarkResult],
    path: Path,
) -> None:
    """Write aggregated makespan results to a CSV file.

    Args:
        results: Results to serialize.
        path: Destination CSV path. Parent directories are created if needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(_CSV_FIELDNAMES))
        writer.writeheader()
        for r in results:
            writer.writerow(
                {
                    "circuit_name": r.circuit_name,
                    "circuit_num_qubits": r.circuit_num_qubits,
                    "network_topology": r.network_topology,
                    "num_qpus": r.num_qpus,
                    "algorithm": r.algorithm,
                    "num_seeds": r.num_seeds,
                    "makespan_mean": r.makespan_mean,
                    "makespan_std": r.makespan_std,
                    "makespan_min": r.makespan_min,
                    "makespan_max": r.makespan_max,
                }
            )
    logger.info("CSV written → %s", path)


def write_per_seed_csv(
    results: Sequence[MakespanBenchmarkResult],
    path: Path,
) -> None:
    """Write raw per-seed makespans to a long-format CSV file.

    One row per (circuit, topology, algorithm, seed) so the makespan
    distributions can be re-plotted later.

    Args:
        results: Results whose per-seed makespans are serialized.
        path: Destination CSV path. Parent directories are created if needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "circuit_name",
        "circuit_num_qubits",
        "network_topology",
        "num_qpus",
        "algorithm",
        "seed",
        "makespan",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            for seed, makespan in r.seed_makespans:
                writer.writerow(
                    {
                        "circuit_name": r.circuit_name,
                        "circuit_num_qubits": r.circuit_num_qubits,
                        "network_topology": r.network_topology,
                        "num_qpus": r.num_qpus,
                        "algorithm": r.algorithm,
                        "seed": seed,
                        "makespan": makespan,
                    }
                )
    logger.info("Per-seed CSV written → %s", path)


# ── HTML dashboard ────────────────────────────────────────────────────────────


def write_html_dashboard(
    results: Sequence[MakespanBenchmarkResult],
    path: Path,
    timestamp: str,
    algorithms: Sequence[str],
) -> None:
    """Write an interactive HTML makespan dashboard.

    The dashboard is self-contained (requires only CDN access for
    Plotly.js) and includes a per-algorithm summary table, an interactive
    per-circuit makespan chart with error bars, and a full sortable
    results table.

    Args:
        results: Benchmark results to visualize.
        path: Destination HTML path. Parent directories are created if needed.
        timestamp: Human-readable run timestamp for the page header.
        algorithms: Algorithm names in display order.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    html = _build_dashboard_html(results, timestamp, algorithms)
    path.write_text(html, encoding="utf-8")
    logger.info("HTML dashboard → %s", path)


def _wins_by_algorithm(
    results: Sequence[MakespanBenchmarkResult],
) -> dict[str, int]:
    """Return a count of cases each algorithm won (lowest mean makespan).

    Ties count as a win for every tied algorithm.

    Args:
        results: All benchmark results.

    Returns:
        Mapping from algorithm name to number of cases won.
    """
    wins: dict[str, int] = defaultdict(int)
    by_case: dict[tuple[str, str], list[MakespanBenchmarkResult]] = (
        defaultdict(list)
    )
    for r in results:
        by_case[(r.circuit_name, r.network_topology)].append(r)
    for case_results in by_case.values():
        if not case_results:
            continue
        best = min(r.makespan_mean for r in case_results)
        for r in case_results:
            if r.makespan_mean == best:
                wins[r.algorithm] += 1
    return wins


def _circuit_makespan_data(
    results: Sequence[MakespanBenchmarkResult],
) -> str:
    """Return JSON of makespan stats keyed by circuit name.

    Each circuit maps to a list of records containing the topology,
    algorithm, mean makespan, and std. Used by the interactive makespan
    explorer in the HTML dashboard.

    Args:
        results: Benchmark results.

    Returns:
        JSON string mapping circuit name to a list of
        ``{topology, algorithm, mean, std}`` dicts.
    """
    data: dict[str, list[dict[str, str | float]]] = {}
    for r in results:
        data.setdefault(r.circuit_name, []).append(
            {
                "topology": r.network_topology,
                "algorithm": r.algorithm,
                "mean": round(r.makespan_mean, 3),
                "std": round(r.makespan_std, 3),
            }
        )
    return json.dumps(data)


def _summary_rows_html(
    results: Sequence[MakespanBenchmarkResult],
    algorithms: Sequence[str],
) -> str:
    """Return HTML ``<tr>`` elements for the per-algorithm summary table.

    Args:
        results: All benchmark results.
        algorithms: Algorithm names in display order.

    Returns:
        HTML string of table rows.
    """
    wins = _wins_by_algorithm(results)
    rows: list[str] = []
    for algo in algorithms:
        ar = [r for r in results if r.algorithm == algo]
        if not ar:
            continue
        rows.append(
            f"<tr>"
            f"<td>{algo}</td>"
            f"<td>{mean(r.makespan_mean for r in ar):.3f}</td>"
            f"<td>{mean(r.makespan_std for r in ar):.3f}</td>"
            f"<td>{wins.get(algo, 0)}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


def _full_table_rows_html(
    results: Sequence[MakespanBenchmarkResult],
) -> str:
    """Return HTML ``<tr>`` elements for all benchmark results.

    Rows are sorted by qubit count, circuit name, topology, then algorithm.

    Args:
        results: All benchmark results.

    Returns:
        HTML string of table rows.
    """
    sorted_results = sorted(
        results,
        key=lambda r: (
            r.circuit_num_qubits,
            r.circuit_name,
            r.network_topology,
            r.algorithm,
        ),
    )
    rows = []
    for r in sorted_results:
        rows.append(
            f"<tr>"
            f"<td>{r.circuit_name}</td>"
            f"<td>{r.circuit_num_qubits}</td>"
            f"<td>{r.network_topology}</td>"
            f"<td>{r.num_qpus}</td>"
            f"<td>{r.algorithm}</td>"
            f"<td>{r.num_seeds}</td>"
            f"<td><strong>{r.makespan_mean:.3f}</strong></td>"
            f"<td>{r.makespan_std:.3f}</td>"
            f"<td>{r.makespan_min:.3f}</td>"
            f"<td>{r.makespan_max:.3f}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


def _build_dashboard_html(
    results: Sequence[MakespanBenchmarkResult],
    timestamp: str,
    algorithms: Sequence[str],
) -> str:
    """Build a complete self-contained HTML dashboard string.

    Args:
        results: All benchmark results.
        timestamp: Run timestamp for the page header.
        algorithms: Algorithm names in display order.

    Returns:
        Complete HTML document as a string.
    """
    summary_html = _summary_rows_html(results, algorithms)
    full_rows_html = _full_table_rows_html(results)

    circuit_makespan_json = _circuit_makespan_data(results)
    circuits_json = json.dumps(sorted({r.circuit_name for r in results}))
    unit = _time_unit()

    n_runs = len(results)
    n_circuits = len({r.circuit_name for r in results})
    n_topologies = len({r.network_topology for r in results})
    algos_str = ", ".join(algorithms)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>memQ-DQC Scheduler Makespan Benchmark</title>
  <script src="https://cdn.plot.ly/plotly-2.35.2.min.js"></script>
  <style>
    *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      background: #f5f6fa; color: #1a1d23; padding: 2rem 2.5rem;
      max-width: 1400px; margin: 0 auto;
    }}
    h1 {{ font-size: 1.5rem; font-weight: 700; margin-bottom: 0.2rem; }}
    h2 {{ font-size: 1rem; font-weight: 600; text-transform: uppercase;
          letter-spacing: 0.05em; color: #555; margin: 2rem 0 0.6rem; }}
    .meta {{
      display: flex; flex-wrap: wrap; gap: 1.2rem;
      color: #666; font-size: 0.82rem; margin-bottom: 1.8rem;
      padding-bottom: 1rem; border-bottom: 1px solid #e0e3ea;
    }}
    .meta-item {{ display: flex; align-items: center; gap: 0.35rem; }}
    .badge {{
      background: #eef0f7; border-radius: 4px;
      padding: 1px 7px; font-weight: 600; color: #333;
    }}
    .card {{
      background: #fff; border: 1px solid #e0e3ea;
      border-radius: 8px; padding: 1.25rem 1.5rem; margin-bottom: 1.25rem;
      box-shadow: 0 1px 3px rgba(0,0,0,.04);
    }}
    .explorer-controls {{
      display: flex; align-items: center; gap: 1rem;
      margin-bottom: 1rem; font-size: 0.85rem; font-weight: 600;
    }}
    .explorer-controls select {{
      border: 1px solid #d8dce8; border-radius: 4px;
      padding: 4px 8px; font-size: 0.82rem; background: #fff; cursor: pointer;
    }}
    table {{
      width: 100%; border-collapse: collapse; font-size: 0.8rem;
    }}
    thead th {{
      background: #f0f2f8; padding: 7px 10px; text-align: left;
      font-weight: 600; font-size: 0.75rem; text-transform: uppercase;
      letter-spacing: 0.04em; cursor: pointer; user-select: none;
      white-space: nowrap; border-bottom: 2px solid #d8dce8;
    }}
    thead th:hover {{ background: #e2e5f0; }}
    td {{ padding: 5px 10px; border-top: 1px solid #f0f2f5; }}
    tr:hover td {{ background: #f8f9fd; }}
  </style>
</head>
<body>

<h1>memQ-DQC Scheduler Makespan Benchmark Report</h1>
<div class="meta">
  <div class="meta-item">&#128197; <span>{timestamp}</span></div>
  <div class="meta-item">Runs: <span class="badge">{n_runs}</span></div>
  <div class="meta-item">Circuits: <span class="badge">{n_circuits}</span></div>
  <div class="meta-item">Topologies: <span class="badge">{n_topologies}</span></div>
  <div class="meta-item">Algorithms: <span class="badge">{algos_str}</span></div>
  <div class="meta-item">Makespan unit: <span class="badge">{unit}</span></div>
</div>

<h2>Algorithm Summary</h2>
<div class="card">
  <table id="summary-table">
    <thead>
      <tr>
        <th onclick="sortTable('summary-table',0)">Algorithm</th>
        <th onclick="sortTable('summary-table',1)">Avg Mean Makespan &#9652;</th>
        <th onclick="sortTable('summary-table',2)">Avg Std</th>
        <th onclick="sortTable('summary-table',3)">Wins (lowest mean)</th>
      </tr>
    </thead>
    <tbody>{summary_html}</tbody>
  </table>
</div>

<h2>Makespan Explorer &mdash; mean &plusmn; std by topology</h2>
<div class="card">
  <div class="explorer-controls">
    <label for="circuit-select">Circuit:</label>
    <select id="circuit-select" onchange="renderMakespanChart()"></select>
  </div>
  <div id="chart-makespan" style="height:380px"></div>
</div>

<h2>Full Results</h2>
<div class="card">
  <table id="results-table">
    <thead>
      <tr>
        <th onclick="sortTable('results-table',0)">Circuit</th>
        <th onclick="sortTable('results-table',1)">Qubits</th>
        <th onclick="sortTable('results-table',2)">Topology</th>
        <th onclick="sortTable('results-table',3)">QPUs</th>
        <th onclick="sortTable('results-table',4)">Algorithm</th>
        <th onclick="sortTable('results-table',5)">Seeds</th>
        <th onclick="sortTable('results-table',6)">Mean Makespan &#9652;</th>
        <th onclick="sortTable('results-table',7)">Std</th>
        <th onclick="sortTable('results-table',8)">Min</th>
        <th onclick="sortTable('results-table',9)">Max</th>
      </tr>
    </thead>
    <tbody>{full_rows_html}</tbody>
  </table>
</div>

<script>
  const _layout = {{
    barmode: "group",
    margin: {{t: 10, r: 10, b: 110, l: 65}},
    legend: {{orientation: "h", y: -0.28, x: 0.5, xanchor: "center"}},
    plot_bgcolor: "#fff",
    paper_bgcolor: "#fff",
    font: {{size: 11, family: "-apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif"}},
    xaxis: {{tickangle: -38}},
  }};

  const _CIRCUIT_MAKESPAN = {circuit_makespan_json};
  const _CIRCUITS = {circuits_json};
  const _UNIT = {json.dumps(unit)};

  (function () {{
    const sel = document.getElementById("circuit-select");
    _CIRCUITS.forEach(c => {{
      const o = document.createElement("option");
      o.value = o.textContent = c;
      sel.appendChild(o);
    }});
    renderMakespanChart();
  }})();

  function renderMakespanChart() {{
    const circuit = document.getElementById("circuit-select").value;
    const rows = _CIRCUIT_MAKESPAN[circuit] || [];
    const algos = [...new Set(rows.map(r => r.algorithm))].sort();
    const topos = [...new Set(rows.map(r => r.topology))].sort();
    const traces = algos.map(a => ({{
      name: a,
      x: topos,
      y: topos.map(t => {{
        const m = rows.find(r => r.algorithm === a && r.topology === t);
        return m ? m.mean : null;
      }}),
      error_y: {{
        type: "data",
        array: topos.map(t => {{
          const m = rows.find(r => r.algorithm === a && r.topology === t);
          return m ? m.std : 0;
        }}),
        visible: true,
      }},
      type: "bar",
    }}));
    Plotly.react("chart-makespan", traces,
      {{..._layout, yaxis: {{title: "Makespan (" + _UNIT + ")"}}}},
      {{responsive: true}});
  }}

  function sortTable(id, col) {{
    const tbl = document.getElementById(id);
    const body = tbl.querySelector("tbody");
    const rows = [...body.querySelectorAll("tr")];
    const asc = tbl.dataset.col == col && tbl.dataset.dir !== "asc";
    rows.sort((a, b) => {{
      const av = a.cells[col].textContent.trim();
      const bv = b.cells[col].textContent.trim();
      const an = parseFloat(av), bn = parseFloat(bv);
      if (!isNaN(an) && !isNaN(bn)) return asc ? an - bn : bn - an;
      return asc ? av.localeCompare(bv) : bv.localeCompare(av);
    }});
    rows.forEach(r => body.appendChild(r));
    tbl.dataset.col = col;
    tbl.dataset.dir = asc ? "asc" : "desc";
  }}
</script>
</body>
</html>"""


# ── CLI ───────────────────────────────────────────────────────────────────────


def _parse_args() -> argparse.Namespace:
    """Return parsed CLI arguments for the benchmark runner."""
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark makespan for the DES scheduler variants across "
            "distributed circuits. Writes a terminal table, CSV, and HTML "
            "dashboard to results/ by default."
        )
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        metavar="NAME",
        help=(
            "Benchmark case name to run. Use --list-cases to see all. "
            "Can be repeated. Defaults to all discovered cases."
        ),
    )
    parser.add_argument(
        "--algo",
        action="append",
        dest="algos",
        metavar="ALGO",
        help=(
            "DES scheduler to benchmark. Can be repeated. "
            "Defaults to: " + ", ".join(DEFAULT_DES_ALGORITHMS)
        ),
    )
    parser.add_argument(
        "--seeds",
        type=int,
        default=DEFAULT_NUM_SEEDS,
        metavar="N",
        help=(
            "Number of seeds per case/algorithm. "
            f"Defaults to {DEFAULT_NUM_SEEDS}."
        ),
    )
    parser.add_argument(
        "--base-seed",
        type=int,
        default=DEFAULT_BASE_SEED,
        metavar="N",
        help=(
            "First seed in the deterministic seed sequence. "
            f"Defaults to {DEFAULT_BASE_SEED}."
        ),
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List all discovered benchmark cases and exit.",
    )
    parser.add_argument(
        "--output-csv",
        metavar="PATH",
        help="Write CSV results to PATH instead of the default results/ file.",
    )
    parser.add_argument(
        "--output-html",
        metavar="PATH",
        help="Write HTML dashboard to PATH instead of the default results/ file.",
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
            "Per-run wall-clock limit for a single compile or scheduler run. "
            f"Defaults to {DEFAULT_TIMEOUT_SECONDS:.0f}s "
            "(5 minutes). Use 0 to disable."
        ),
    )
    return parser.parse_args()


def _configure_logging() -> None:
    """Configure terminal logging for the benchmark run."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def _resolve_cases(
    selected: list[str] | None,
    all_cases: list[BenchmarkCase],
) -> list[BenchmarkCase]:
    """Return the requested subset of discovered benchmark cases.

    Args:
        selected: Case names to run, or ``None`` to run all.
        all_cases: Full list of discovered cases.

    Returns:
        Filtered list of cases matching the requested names.
    """
    if not selected:
        return all_cases
    by_name = {c.name: c for c in all_cases}
    chosen = [by_name[n] for n in selected if n in by_name]
    for name in selected:
        if name not in by_name:
            logger.warning("Unknown case %r — skipping.", name)
    return chosen


def main() -> None:
    """Run the scheduler makespan benchmark from the command line."""
    args = _parse_args()
    _configure_logging()

    all_cases = discover_benchmark_cases()

    if args.list_cases:
        for case in all_cases:
            print(f"{case.name}: {case.description}")
        return

    cases = _resolve_cases(args.cases, all_cases)
    algos = args.algos or list(DEFAULT_DES_ALGORITHMS)
    num_seeds = max(1, args.seeds)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    slug = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("=" * 72)
    logger.info("memQ-DQC Scheduler Makespan Benchmark")
    logger.info("Timestamp  : %s", timestamp)
    logger.info(
        "Cases      : %d  (%d circuits × topologies)",
        len(cases),
        len({c.circuit_path for c in cases}),
    )
    logger.info("Algorithms : %s", ", ".join(algos))
    logger.info("Seeds      : %d (base seed %d)", num_seeds, args.base_seed)
    logger.info("Compiler   : %s (held constant)", DEFAULT_COMPILER_ALGO)
    logger.info(
        "Timeout    : %s",
        f"{args.timeout:.0f}s per run" if args.timeout > 0 else "disabled",
    )
    logger.info("=" * 72)

    results = run_benchmark_suite(
        cases,
        algos,
        num_seeds,
        args.base_seed,
        args.timeout,
    )

    if not results:
        logger.error("No successful results. Check errors above.")
        return

    log_terminal_table(results)

    csv_path = (
        Path(args.output_csv)
        if args.output_csv
        else _RESULTS_DIR / f"makespan_benchmark_{slug}.csv"
    )
    write_csv(results, csv_path)
    write_per_seed_csv(
        results,
        csv_path.with_name(f"{csv_path.stem}_per_seed.csv"),
    )

    if not args.no_html:
        html_path = (
            Path(args.output_html)
            if args.output_html
            else _RESULTS_DIR / f"makespan_benchmark_{slug}.html"
        )
        write_html_dashboard(results, html_path, timestamp, algos)


if __name__ == "__main__":
    main()
