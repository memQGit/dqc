Run the compiler benchmark suite and surface high-signal results.

Arguments passed by user: $ARGUMENTS

## Step 1 — handle list mode

If `$ARGUMENTS` contains `--list`, run:
```
uv run python benchmarking/compiler_benchmarking/run_compiler_benchmark.py --list-cases 2>&1
```
Print the cases and stop.

## Step 2 — run benchmarks

Otherwise run:
```
uv run python benchmarking/compiler_benchmarking/run_compiler_benchmark.py $ARGUMENTS 2>&1
```

Run from the repo root (`/Users/lukeandreesen/dev/xdqc`). This may take several minutes — report progress as it streams.

## Step 3 — high-signal summary

After the run completes, produce this summary. Parse the terminal output; do NOT re-run anything.

### Winner
State which algorithm achieved the lowest average EPR pairs across all cases, and by what margin over the next-best.

### Per-case ranking
For each (circuit, topology) group, emit a compact table:

| Algorithm | EPR Pairs | Remote Gates | Ops Overhead | Runtime |
|-----------|-----------|--------------|--------------|---------|

Sort rows by EPR pairs ascending. Mark the winner row with ★.

### Signal / noise callouts
- Any algorithm that was best on ≥ 50% of cases: call it out as "dominant"
- Any cases with a large spread (>2× difference between best and worst EPR): flag as "high-variance case — topology may heavily favour one approach"
- Any timeouts or failures: list them with the error summary

### Output files
Print the paths to the generated CSV and HTML dashboard. Note that the HTML file contains interactive Plotly charts (grouped bar charts by circuit and topology, sortable full-results table) — open it in a browser for visual exploration.

If no `$ARGUMENTS` were given, all default algorithms (`interaction`, `hypergraph`, `benchmark_static`, `benchmark_random`) were run on all discovered cases.
