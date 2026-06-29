# memQ Distributed Quantum Compiler (memQ-DQC)


<p align="center">
    <a href="https://github.com/memQGit/DistributedCompiler/actions/workflows/ci.yml">
        <img src="https://github.com/memQGit/DistributedCompiler/actions/workflows/ci.yml/badge.svg" alt="CI Status">
    </a>
    <a href="https://github.com/memQGit/DistributedCompiler/blob/main/LICENSE">
      <img src="https://img.shields.io/badge/license-MIT-blue" alt="License">
    </a>
</p>

memQ-DQC is an open-source Python library for distributed quantum compilation. Given a quantum circuit and a network topology, it partitions the circuit across QPUs, routes inter-QPU gates, and reconstructs a distributed circuit ready for execution or further analysis.

The library is designed to be modular and plug-and-play: researchers can run the full compilation workflow in a few lines of code, swap in different partitioning algorithms, and benchmark them against each other across circuits and network topologies.

---

## Installation

    uv sync

---

## Quick start

```python
from memq_dqc.partition import Partitioner
from memq_dqc.builder import extract_distributed_circuit
from memq_dqc.verify import verify_distributed_circuit

# Compile
partitioner = Partitioner("network.json", "circuit.qasm")
partitioner.run()

# Extract the distributed circuit
distributed = extract_distributed_circuit(partitioner)

# Verify correctness against the original
is_valid = verify_distributed_circuit("circuit.qasm", "distributed.qasm")
```

`Partitioner` accepts either file paths or pre-loaded objects:

```python
from memq_dqc.network import NetworkGraph
from memq_dqc.preprocessing.qasm.io import load_qasm_program

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

`memq_dqc.visualization` provides SVG-based views of the compilation output:

```python
from memq_dqc.visualization import (
    plot_distributed_circuit,   # gate layout across QPUs
    plot_partition_flow,        # qubit migration across QPUs
    plot_partition_heatmap,     # QPU assignment heatmap per window
    plot_migration_timeline,    # qubit movement timeline with EPR cost
    plot_circuit_dag,           # circuit DAG
    plot_operation_gantt,       # operation Gantt chart
    write_svg_dashboard_html,   # bundle panels into an HTML viewer
)
```

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

For advanced control, configure the standard Python logger named `memq_dqc`:

```python
import logging

logging.basicConfig(level=logging.DEBUG)
logging.getLogger("memq_dqc").setLevel(logging.DEBUG)
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
