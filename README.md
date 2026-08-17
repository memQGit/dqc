<p align="center">
    <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/memQGit/xdqc/main/docs/assets/memq-logo-white.png">
        <img src="https://raw.githubusercontent.com/memQGit/xdqc/main/docs/assets/memq-logo.png" alt="memQ" width="200">
    </picture>
</p>

# xDQC — Extensible Distributed Quantum Compiler


<p align="center">
    <a href="https://github.com/memQGit/xdqc/actions/workflows/ci.yml">
        <img src="https://github.com/memQGit/xdqc/actions/workflows/ci.yml/badge.svg" alt="CI Status">
    </a>
    <a href="https://xdqc.readthedocs.io/en/latest/">
        <img src="https://readthedocs.org/projects/xdqc/badge/?version=latest" alt="Documentation Status">
    </a>
    <a href="https://codecov.io/gh/memQGit/xdqc">
        <img src="https://codecov.io/gh/memQGit/xdqc/branch/main/graph/badge.svg" alt="Coverage">
    </a>
    <a href="https://github.com/memQGit/xdqc/blob/main/pyproject.toml">
        <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue" alt="Python versions">
    </a>
    <a href="https://github.com/astral-sh/ruff">
        <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff">
    </a>
    <a href="https://github.com/memQGit/xdqc/blob/main/LICENSE">
      <img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License">
    </a>
</p>

**xDQC** (*Extensible Distributed Quantum Compiler*) is an open-source Python library for distributed quantum compilation. Given a quantum circuit and a network topology, it partitions the circuit across QPUs, routes inter-QPU gates, and reconstructs a distributed circuit ready for execution or further analysis.

The name reflects the design goal: every stage of the pipeline — partitioning, routing, scheduling, visualization — is a swappable component, so researchers can extend the compiler with their own algorithms rather than work around it.

The library is designed to be modular and plug-and-play: researchers can run the full compilation workflow in a few lines of code, swap in different partitioning algorithms, and benchmark them against each other across circuits and network topologies.

---

## Installation

    uv sync

---

## Quick start

```python
from xdqc.partition import Partitioner
from xdqc.builder import extract_distributed_circuit
from xdqc.verify import verify_distributed_circuit

# Compile
partitioner = Partitioner("network.json", "circuit.qasm")
partitioner.run()

# Extract the distributed circuit
distributed = extract_distributed_circuit(partitioner)

# Verify correctness against the original
is_valid = verify_distributed_circuit("circuit.qasm", "distributed.qasm")
```

For one-call access to both circuits and their DAGs:

```python
from xdqc import get_verification_artifacts
from xdqc.verify import verify_distributed_circuit

artifacts = get_verification_artifacts("circuit.qasm", "network.json")

is_valid = verify_distributed_circuit(
    artifacts.original_program,
    artifacts.distributed_program,
)

original_qasm = artifacts.original_qasm
original_dag = artifacts.original_dag
distributed_qasm = artifacts.distributed_qasm
distributed_dag = artifacts.distributed_dag
```

`Partitioner` accepts either file paths or pre-loaded objects:

```python
from xdqc.network import NetworkGraph
from xdqc.preprocessing.qasm.io import load_qasm_program

network = NetworkGraph("network.json")
program = load_qasm_program("circuit.qasm")
partitioner = Partitioner(network, program)
```

---

## Partitioning algorithms

Pass `algo=` to `Partitioner` to select a partitioning strategy. The default is `"interaction"`.

| Algorithm | Description |
|---|---|
| `interaction` | Interaction-graph based partitioning (default) |
| `hypergraph` | Hypergraph partitioning |
| `benchmark_static` | Static baseline — deterministic reference |
| `benchmark_random` | Random baseline — stochastic reference |

```python
partitioner = Partitioner("network.json", "circuit.qasm", algo="hypergraph")
```

---

## Visualization

`xdqc.visualization` provides SVG-based views of the compilation output:

```python
from xdqc.visualization import (
    plot_distributed_circuit,   # gate layout across QPUs
    plot_partition_flow,        # qubit migration across QPUs
    plot_partition_heatmap,     # QPU assignment heatmap per window
    plot_migration_timeline,    # qubit movement timeline with EPR cost
    plot_circuit_dag,           # circuit DAG
    plot_operation_gantt,       # operation Gantt chart
    write_svg_dashboard_html,   # bundle panels into an HTML viewer
)
```

### Animated execution playback

`animate_circuit_execution` plays a schedule back over the network graph,
highlighting the physical qubits and links carrying each operation as the
distributed circuit executes:

```python
from xdqc.visualization import animate_circuit_execution

animation = animate_circuit_execution(network, scheduler.schedule)
animation.show()          # interactive window with play/pause and a scrubber
animation.save("run.gif")  # or export to .gif / .mp4 / .html
```

In a notebook, displaying the returned object renders an inline player.

---

## Logging and verbosity

The main workflow APIs support per-call verbosity control:

- `quiet` (default): returns results without progress logging
- `info`: logs major phase start/completion messages and elapsed time
- `debug`: adds intermediate diagnostics such as chosen parameters,
  per-phase summaries, and mapping details

```python
partitioner = Partitioner("network.json", "circuit.qasm")
partitioner.run(verbosity="info")

distributed = extract_distributed_circuit(partitioner, verbosity="debug")

is_valid = verify_distributed_circuit(
    "original.qasm",
    "distributed.qasm",
    verbosity="info",
)
```

For advanced control, configure the standard Python logger named `xdqc`:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("xdqc").setLevel(logging.DEBUG)
```

---

## Development

This repository uses **Ruff** for linting and formatting and **pytest** for tests. All checks are wrapped via tox.

### Run all checks

    uv run tox

### Run checks individually

    uv run ruff check .          # lint
    uv run ruff format --check . # format check (no modifications)
    uv run ruff format .          # auto-format
    uv run pytest -q              # tests

### Docs

The docs site (config, API reference generation, demo notebooks) lives under `docs/`.

    uv sync --group docs                              # install docs dependencies
    uv run mkdocs serve -f docs/mkdocs.yml             # live preview at http://127.0.0.1:8000
    uv run mkdocs build -f docs/mkdocs.yml --strict    # build to ./site (fails on warnings)
