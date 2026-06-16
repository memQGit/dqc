"""Run compiler benchmarks for different partitioning algorithms.

Discovers QASM circuits and network topologies from the
``benchmarking/benchmark_circuits`` and ``benchmarking/benchmark_networks``
directories, runs each circuit through a suite of partitioning algorithms,
and reports the results as a terminal table, CSV file, and an interactive
HTML dashboard.

The primary benchmark metric is **EPR pairs used** (entanglement cost).
Secondary metrics include remote gate count, local swaps added,
two-qubit operations overhead, and wall-clock runtime.

Usage (run from repo root)::

    uv run python benchmarking/compiler_benchmarking/run_compiler_benchmark.py
    uv run python benchmarking/compiler_benchmarking/run_compiler_benchmark.py --algo interaction --algo hypergraph
    uv run python benchmarking/compiler_benchmarking/run_compiler_benchmark.py --output-csv out.csv --output-html report.html
    uv run python benchmarking/compiler_benchmarking/run_compiler_benchmark.py --list-cases
"""

from __future__ import annotations

import argparse
import csv
import datetime
import json
import logging
import re
import signal
from collections import defaultdict
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import mean
from types import FrameType

from memq_dqc._logging import StepTimer
from memq_dqc.partition import Partitioner

_BENCHMARKING_ROOT = Path(__file__).resolve().parents[1]
_BENCHMARK_CIRCUITS_DIR = _BENCHMARKING_ROOT / "benchmark_circuits"
_BENCHMARK_NETWORKS_DIR = _BENCHMARKING_ROOT / "benchmark_networks"
_RESULTS_DIR = Path(__file__).resolve().parent / "results"

DEFAULT_COMPILER_ALGORITHMS: tuple[str, ...] = (
    "interaction",
    "hypergraph",
    "benchmark_static",
    "benchmark_random",
)

# Per-run wall-clock limit for a single algorithm on a single case.
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
class CompilerBenchmarkResult:
    """Full metric set from one compiler benchmark run.

    Attributes:
        circuit_name: Filename stem of the benchmark circuit.
        circuit_num_qubits: Qubit count extracted from the circuit filename.
        network_topology: Network topology filename stem (e.g. ``ring_3qpu``).
        num_qpus: Number of QPUs in the benchmark network.
        algorithm: Partitioning algorithm name.
        epr_pairs: Exact entanglement cost in EPR pairs (primary metric).
        original_2q_gates: Two-qubit gate count in the input circuit.
        remote_gates: Remote gate operations in the distributed circuit.
        local_swaps_added: Local SWAP operations inserted during routing.
        ops_overhead: Extra two-qubit operations vs the original circuit.
        num_windows: Number of partitioning windows produced.
        runtime_seconds: Wall-clock time for partitioning and extraction.
    """

    circuit_name: str
    circuit_num_qubits: int
    network_topology: str
    num_qpus: int
    algorithm: str
    epr_pairs: float
    original_2q_gates: int
    remote_gates: int
    local_swaps_added: int
    ops_overhead: int
    num_windows: int
    runtime_seconds: float


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One named compiler benchmark input.

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


# ── Execution ────────────────────────────────────────────────────────────────


def run_single_case(
    case: BenchmarkCase,
    algorithm: str,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> CompilerBenchmarkResult | None:
    """Partition one benchmark case with one algorithm and collect metrics.

    Args:
        case: Benchmark circuit / network pair.
        algorithm: Partitioning algorithm registry name.
        timeout_seconds: Per-run wall-clock limit. Values <= 0 disable it.

    Returns:
        Populated :class:`CompilerBenchmarkResult`, or ``None`` if the run
        exceeded the time limit or raised an exception.
    """
    try:
        with _time_limit(timeout_seconds):
            partitioner = Partitioner(
                str(case.network_path),
                str(case.circuit_path),
                algo=algorithm,
            )
            timer = StepTimer()
            partitioner.run(ebit_assignment=True, verbosity="quiet")
            runtime = timer.elapsed_seconds()

            cost = partitioner.cost or 0.0
            original_2q = partitioner.circuit.mono.num_two_qubit_gates
            dist = partitioner.distributed_circuit
            ops_overhead = dist.num_two_qubit_gates - original_2q

            return CompilerBenchmarkResult(
                circuit_name=case.circuit_path.stem,
                circuit_num_qubits=case.circuit_num_qubits,
                network_topology=case.network_topology,
                num_qpus=partitioner.network.num_qpus,
                algorithm=algorithm,
                epr_pairs=cost,
                original_2q_gates=original_2q,
                remote_gates=dist.num_remote_gates,
                local_swaps_added=dist.num_local_swaps_added,
                ops_overhead=ops_overhead,
                num_windows=len(partitioner.windows or []),
                runtime_seconds=runtime,
            )
    except TimeoutError:
        logger.error(
            "TIMEOUT %-36s  %-24s  %s: exceeded %.0fs limit",
            case.circuit_path.stem,
            case.network_topology,
            algorithm,
            timeout_seconds,
        )
        return None
    except Exception as exc:
        logger.error(
            "FAILED  %-36s  %-24s  %s: %s",
            case.circuit_path.stem,
            case.network_topology,
            algorithm,
            exc,
        )
        return None


def run_benchmark_suite(
    cases: list[BenchmarkCase],
    algorithms: list[str],
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
) -> list[CompilerBenchmarkResult]:
    """Run every case through every algorithm and return all results.

    Args:
        cases: Benchmark cases to run.
        algorithms: Partitioning algorithm names to benchmark.
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
    return results


# ── Terminal output ───────────────────────────────────────────────────────────


def log_terminal_table(results: list[CompilerBenchmarkResult]) -> None:
    """Print all results as a grouped terminal table.

    Groups rows by circuit and topology. Within each group, rows are
    sorted by EPR pairs ascending so the best algorithm appears first.

    Args:
        results: Benchmark results to display.
    """
    if not results:
        logger.info("No results to display.")
        return

    grouped: dict[tuple[str, str], list[CompilerBenchmarkResult]] = (
        defaultdict(list)
    )
    for r in results:
        grouped[(r.circuit_name, r.network_topology)].append(r)

    col = (
        f"{'Algorithm':<22} | {'EPR Pairs':>10} | "
        f"{'Remote Gates':>12} | {'Local SWAPs':>11} | "
        f"{'Ops Overhead':>12} | {'Windows':>7} | {'Runtime (s)':>11}"
    )
    sep = "-" * len(col)

    for (circuit, topology), group in sorted(grouped.items()):
        logger.info("\n%s", "=" * len(col))
        logger.info("Circuit  : %s", circuit)
        logger.info("Topology : %s  (%d QPUs)", topology, group[0].num_qpus)
        logger.info(
            "Original : %d two-qubit gates", group[0].original_2q_gates
        )
        logger.info(sep)
        logger.info(col)
        logger.info(sep)
        for r in sorted(group, key=lambda x: x.epr_pairs):
            logger.info(
                "%-22s | %10.1f | %12d | %11d | %12d | %7d | %11.3f",
                r.algorithm,
                r.epr_pairs,
                r.remote_gates,
                r.local_swaps_added,
                r.ops_overhead,
                r.num_windows,
                r.runtime_seconds,
            )


# ── CSV output ────────────────────────────────────────────────────────────────


def write_csv(results: list[CompilerBenchmarkResult], path: Path) -> None:
    """Write all benchmark results to a CSV file.

    Args:
        results: Results to serialize.
        path: Destination CSV path. Parent directories are created if needed.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "circuit_name",
        "circuit_num_qubits",
        "network_topology",
        "num_qpus",
        "algorithm",
        "epr_pairs",
        "original_2q_gates",
        "remote_gates",
        "local_swaps_added",
        "ops_overhead",
        "num_windows",
        "runtime_seconds",
    ]
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in results:
            writer.writerow(asdict(r))
    logger.info("CSV written → %s", path)


# ── HTML dashboard ────────────────────────────────────────────────────────────


def write_html_dashboard(
    results: list[CompilerBenchmarkResult],
    path: Path,
    timestamp: str,
    algorithms: list[str],
) -> None:
    """Write an interactive HTML benchmark dashboard.

    The dashboard is self-contained (requires only CDN access for
    Plotly.js) and includes a summary table, three comparison charts,
    and a full sortable results table.

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


def _mean_by(
    results: list[CompilerBenchmarkResult],
    group_attr: str,
    value_attr: str,
) -> dict[tuple[str, str], float]:
    """Return mean of ``value_attr`` grouped by (algorithm, ``group_attr``).

    Args:
        results: Results to aggregate.
        group_attr: Attribute name to use as the secondary grouping key.
        value_attr: Numeric attribute to average.

    Returns:
        Mapping from (algorithm, group_value) to mean of value_attr.
    """
    buckets: dict[tuple[str, str], list[float]] = defaultdict(list)
    for r in results:
        key = (r.algorithm, str(getattr(r, group_attr)))
        buckets[key].append(float(getattr(r, value_attr)))
    return {k: mean(v) for k, v in buckets.items()}


def _plotly_traces(
    results: list[CompilerBenchmarkResult],
    algorithms: list[str],
    x_attr: str,
    y_attr: str,
) -> str:
    """Return a JSON list of Plotly grouped-bar traces.

    Each algorithm becomes one trace. The y value for each x category is
    the mean of ``y_attr`` across all results matching that (algorithm, x).

    Args:
        results: Benchmark results.
        algorithms: Algorithm names defining trace order.
        x_attr: Result attribute name to use as x-axis categories.
        y_attr: Result attribute name to aggregate as y values.

    Returns:
        JSON string of a Plotly traces list.
    """
    agg = _mean_by(results, x_attr, y_attr)
    categories = sorted({str(getattr(r, x_attr)) for r in results})
    traces = [
        {
            "name": algo,
            "x": categories,
            "y": [round(agg.get((algo, cat), 0.0), 2) for cat in categories],
            "type": "bar",
        }
        for algo in algorithms
    ]
    return json.dumps(traces)


def _summary_rows_html(
    results: list[CompilerBenchmarkResult],
    algorithms: list[str],
) -> str:
    """Return HTML ``<tr>`` elements for the per-algorithm summary table.

    Args:
        results: All benchmark results.
        algorithms: Algorithm names in display order.

    Returns:
        HTML string of table rows.
    """
    wins: dict[str, int] = defaultdict(int)
    by_case: dict[tuple[str, str], list[CompilerBenchmarkResult]] = (
        defaultdict(list)
    )
    for r in results:
        by_case[(r.circuit_name, r.network_topology)].append(r)
    for case_results in by_case.values():
        if not case_results:
            continue
        best = min(r.epr_pairs for r in case_results)
        for r in case_results:
            if r.epr_pairs == best:
                wins[r.algorithm] += 1

    rows: list[str] = []
    for algo in algorithms:
        ar = [r for r in results if r.algorithm == algo]
        if not ar:
            continue
        rows.append(
            f"<tr>"
            f"<td>{algo}</td>"
            f"<td>{mean(r.epr_pairs for r in ar):.1f}</td>"
            f"<td>{mean(r.ops_overhead for r in ar):.1f}</td>"
            f"<td>{mean(r.runtime_seconds for r in ar):.3f}s</td>"
            f"<td>{wins.get(algo, 0)}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


def _full_table_rows_html(results: list[CompilerBenchmarkResult]) -> str:
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
        overhead = (
            f"+{r.ops_overhead}"
            if r.ops_overhead >= 0
            else str(r.ops_overhead)
        )
        rows.append(
            f"<tr>"
            f"<td>{r.circuit_name}</td>"
            f"<td>{r.circuit_num_qubits}</td>"
            f"<td>{r.network_topology}</td>"
            f"<td>{r.num_qpus}</td>"
            f"<td>{r.algorithm}</td>"
            f"<td><strong>{r.epr_pairs:.1f}</strong></td>"
            f"<td>{r.original_2q_gates}</td>"
            f"<td>{r.remote_gates}</td>"
            f"<td>{r.local_swaps_added}</td>"
            f"<td>{overhead}</td>"
            f"<td>{r.num_windows}</td>"
            f"<td>{r.runtime_seconds:.3f}</td>"
            f"</tr>"
        )
    return "\n".join(rows)


def _build_dashboard_html(
    results: list[CompilerBenchmarkResult],
    timestamp: str,
    algorithms: list[str],
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

    epr_by_circuit = _plotly_traces(
        results, algorithms, "circuit_name", "epr_pairs"
    )
    epr_by_topology = _plotly_traces(
        results, algorithms, "network_topology", "epr_pairs"
    )
    overhead_by_circuit = _plotly_traces(
        results, algorithms, "circuit_name", "ops_overhead"
    )

    n_runs = len(results)
    n_circuits = len({r.circuit_name for r in results})
    n_topologies = len({r.network_topology for r in results})
    algos_str = ", ".join(algorithms)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>memQ-DQC Compiler Benchmark</title>
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
    .chart-grid {{
      display: grid; grid-template-columns: 1fr 1fr; gap: 1.25rem;
    }}
    @media (max-width: 900px) {{ .chart-grid {{ grid-template-columns: 1fr; }} }}
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

<h1>memQ-DQC Compiler Benchmark Report</h1>
<div class="meta">
  <div class="meta-item">&#128197; <span>{timestamp}</span></div>
  <div class="meta-item">Runs: <span class="badge">{n_runs}</span></div>
  <div class="meta-item">Circuits: <span class="badge">{n_circuits}</span></div>
  <div class="meta-item">Topologies: <span class="badge">{n_topologies}</span></div>
  <div class="meta-item">Algorithms: <span class="badge">{algos_str}</span></div>
</div>

<h2>Algorithm Summary</h2>
<div class="card">
  <table id="summary-table">
    <thead>
      <tr>
        <th onclick="sortTable('summary-table',0)">Algorithm</th>
        <th onclick="sortTable('summary-table',1)">Avg EPR Pairs &#9662;</th>
        <th onclick="sortTable('summary-table',2)">Avg Ops Overhead</th>
        <th onclick="sortTable('summary-table',3)">Avg Runtime</th>
        <th onclick="sortTable('summary-table',4)">Wins (lowest EPR)</th>
      </tr>
    </thead>
    <tbody>{summary_html}</tbody>
  </table>
</div>

<h2>EPR Pairs by Circuit &mdash; mean across topologies</h2>
<div class="card">
  <div id="chart-epr-circuit" style="height:380px"></div>
</div>

<div class="chart-grid">
  <div class="card">
    <h2 style="margin-top:0">EPR Pairs by Topology &mdash; mean across circuits</h2>
    <div id="chart-epr-topology" style="height:320px"></div>
  </div>
  <div class="card">
    <h2 style="margin-top:0">Ops Overhead by Circuit &mdash; mean across topologies</h2>
    <div id="chart-overhead-circuit" style="height:320px"></div>
  </div>
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
        <th onclick="sortTable('results-table',5)">EPR Pairs &#9662;</th>
        <th onclick="sortTable('results-table',6)">Orig 2Q</th>
        <th onclick="sortTable('results-table',7)">Remote Gates</th>
        <th onclick="sortTable('results-table',8)">Local SWAPs</th>
        <th onclick="sortTable('results-table',9)">Ops Overhead</th>
        <th onclick="sortTable('results-table',10)">Windows</th>
        <th onclick="sortTable('results-table',11)">Runtime</th>
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

  Plotly.newPlot("chart-epr-circuit",
    {epr_by_circuit},
    {{..._layout, margin: {{t:10, r:10, b:120, l:65}},
      yaxis: {{title: "EPR Pairs"}}}},
    {{responsive: true}});

  Plotly.newPlot("chart-epr-topology",
    {epr_by_topology},
    {{..._layout, yaxis: {{title: "EPR Pairs"}}}},
    {{responsive: true}});

  Plotly.newPlot("chart-overhead-circuit",
    {overhead_by_circuit},
    {{..._layout, yaxis: {{title: "Ops Overhead"}}}},
    {{responsive: true}});

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
            "Benchmark compiler algorithms across distributed circuits. "
            "Writes a terminal table, CSV, and HTML dashboard to "
            "results/ by default."
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
            "Algorithm to benchmark. Can be repeated. "
            "Defaults to: " + ", ".join(DEFAULT_COMPILER_ALGORITHMS)
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
            "Per-run wall-clock limit for a single algorithm on a single "
            f"case. Defaults to {DEFAULT_TIMEOUT_SECONDS:.0f}s "
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
    """Run the compiler benchmark from the command line."""
    args = _parse_args()
    _configure_logging()

    all_cases = discover_benchmark_cases()

    if args.list_cases:
        for case in all_cases:
            print(f"{case.name}: {case.description}")
        return

    cases = _resolve_cases(args.cases, all_cases)
    algos = args.algos or list(DEFAULT_COMPILER_ALGORITHMS)

    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    slug = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")

    logger.info("=" * 72)
    logger.info("memQ-DQC Compiler Benchmark")
    logger.info("Timestamp  : %s", timestamp)
    logger.info(
        "Cases      : %d  (%d circuits × topologies)",
        len(cases),
        len({c.circuit_path for c in cases}),
    )
    logger.info("Algorithms : %s", ", ".join(algos))
    logger.info("Total runs : %d", len(cases) * len(algos))
    logger.info(
        "Timeout    : %s",
        f"{args.timeout:.0f}s per run" if args.timeout > 0 else "disabled",
    )
    logger.info("=" * 72)

    results = run_benchmark_suite(cases, algos, args.timeout)

    if not results:
        logger.error("No successful results. Check errors above.")
        return

    log_terminal_table(results)

    csv_path = (
        Path(args.output_csv)
        if args.output_csv
        else _RESULTS_DIR / f"benchmark_{slug}.csv"
    )
    write_csv(results, csv_path)

    if not args.no_html:
        html_path = (
            Path(args.output_html)
            if args.output_html
            else _RESULTS_DIR / f"benchmark_{slug}.html"
        )
        write_html_dashboard(results, html_path, timestamp, algos)


if __name__ == "__main__":
    main()
