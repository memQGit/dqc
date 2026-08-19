<p align="center">
    <picture>
        <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/memQGit/dqc/main/docs/assets/memq-logo-white.png">
        <img src="https://raw.githubusercontent.com/memQGit/dqc/main/docs/assets/memq-logo.png" alt="memQ" width="200">
    </picture>
</p>

# DQC — Distributed Quantum Compiler


<p align="center">
    <a href="https://github.com/memQGit/dqc/actions/workflows/ci.yml">
        <img src="https://github.com/memQGit/dqc/actions/workflows/ci.yml/badge.svg" alt="CI Status">
    </a>
    <a href="https://memq-dqc.readthedocs.io/en/latest/">
        <img src="https://readthedocs.org/projects/memq-dqc/badge/?version=latest" alt="Documentation Status">
    </a>
    <a href="https://codecov.io/gh/memQGit/dqc" > 
        <img src="https://codecov.io/gh/memQGit/dqc/graph/badge.svg?token=ZCPU4YYJ8B"/> 
    </a>
    <a href="https://github.com/memQGit/dqc/blob/main/pyproject.toml">
        <img src="https://img.shields.io/badge/python-3.11%20%7C%203.12%20%7C%203.13-blue" alt="Python versions">
    </a>
    <a href="https://github.com/astral-sh/ruff">
        <img src="https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json" alt="Ruff">
    </a>
    <a href="https://github.com/memQGit/dqc/blob/main/LICENSE">
      <img src="https://img.shields.io/badge/license-Apache--2.0-blue" alt="License">
    </a>
    <a href="https://github.com/memQGit/dqc/blob/main/CHANGELOG.md">
      <img src="https://img.shields.io/badge/version-0.1.0-blue" alt="Version 0.1.0">
    </a>
    <a href="https://github.com/memQGit/dqc/blob/main/CHANGELOG.md">
      <img src="https://img.shields.io/badge/status-beta%20%C2%B7%20experimental-orange" alt="Status: beta, experimental">
    </a>
</p>

> [!WARNING]
> **DQC is at `0.1.0` — a beta, experimental release.** It is usable for
> research and benchmarking, but the public API may change in any minor
> release before `1.0.0`. Pin an exact version if you depend on it, and see
> the [CHANGELOG](CHANGELOG.md) for what moved.

**DQC** (*Distributed Quantum Compiler*) is an open-source Python library for distributed quantum compilation. Given a quantum circuit and a network topology, it partitions the circuit across QPUs, routes inter-QPU gates, and reconstructs a distributed circuit ready for execution or further analysis.

It is built around one design goal: every stage of the pipeline — partitioning, routing, scheduling, visualization — is a swappable component, so researchers can extend the compiler with their own algorithms rather than work around it.

The library is designed to be modular and plug-and-play: researchers can run the full compilation workflow in a few lines of code, swap in different partitioning algorithms, and benchmark them against each other across circuits and network topologies.

📖 **Full documentation: [memq-dqc.readthedocs.io](https://memq-dqc.readthedocs.io/en/latest/)** — guides, API reference, and runnable demos.

---

## Installation

    uv sync

---

## Quick start

No circuit or network to use? The library ships a reference set, so the
shortest complete run is:

```python
from memq_dqc import Compiler
from memq_dqc.assets import circuit_path, network_path

compiler = Compiler(circuit_path("qft_n10"), network_path("10_qubits/n2_pair_nn"))
compiler.compile()

print("verified:", compiler.verify(shots=20000))
```

With your own files:

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

For one-call access to both circuits and their DAGs:

```python
from memq_dqc import get_verification_artifacts
from memq_dqc.verify import verify_distributed_circuit

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

## Bundled networks and circuits

`memq_dqc.assets` exposes a reference suite that ships inside the installed
package — 40 network topologies and 10 circuits — so the full workflow runs
without writing a topology first. Both accessors return a `Path`, which is what
`Compiler`, `Partitioner`, and `NetworkGraph` already accept.

```python
from memq_dqc.assets import circuit_path, list_circuits, list_networks, network_path

list_circuits()  # ['adder_n28', 'multiply_n13', 'qft_n10', ...]  4-60 qubits
list_networks()  # ['10_qubits/n2_pair_a2a', '10_qubits/n2_pair_nn', ...]
```

Circuits are transpiled OpenQASM 3.0 programs named `<algorithm>_n<qubits>`,
spanning 4 to 60 qubits. Each is fully measured — a `bit[n] c` register and one
explicit `c[i] = measure q[i];` per qubit — so they work as verification inputs
as well as compilation inputs. Sampling-based `verify()` is practical up to
`multiply_n13` plus `adder_n28`; the wide QFTs starve it, and verify exactly
via `method="statevector"` instead. See the guide for which method covers
which circuit.

Networks are grouped by the circuit size they host (10, 20, 30, 40, 60 qubits)
and named `n<QPUs>_<arrangement>_<variant>` — for example
`30_qubits/n4_hub_nn`. The size is a capacity, not an exact match: a 30-qubit
network hosts any circuit of 30 qubits or fewer. Arrangements cover `pair`,
`chain`, `ring`, and `hub`; each comes in a nearest-neighbour (`_nn`) and an
all-to-all (`_a2a`) intra-QPU variant, so you can isolate the effect of local
connectivity while holding the inter-QPU arrangement fixed. Every network has a
same-named Markdown file documenting it in full, reachable via
`network_doc_path()`.

See the [Bundled Networks & Circuits guide](https://memq-dqc.readthedocs.io/en/latest/guide/bundled-assets/) for the full catalogue.

---

## Network builder

Topology JSON gets tedious to write by hand past a few QPUs. The network builder is a local web app, shipped with the library, for drawing a network in the browser and exporting it as a topology file:

    uv run network-builder

That starts a server on `http://127.0.0.1:8010` and opens it in your browser. Add `--port 8020` to serve somewhere else (8010 is the default so the builder does not collide with `mkdocs serve` on 8000), or `--no-browser` to start the server without opening a tab.

Draw QPUs, qubits, and links by hand, or use the generator panel to produce ring, hub, grid, all-to-all, and homogeneous-line topologies from a QPU count. *Save As* downloads a `.json` file that drops straight into the workflow:

```python
network = NetworkGraph("my_network.json")
```

Installing from PyPI rather than a clone? The builder needs Flask, which ships as an optional extra:

    pip install "memq-dqc[builder]"

The builder also records per-qubit `coherenceTime` and per-link `fidelity`. No current partitioner or scheduler reads these — they are carried in the format so networks built today stay useful to coherence- and fidelity-aware algorithms later.

See the [Network Builder guide](https://memq-dqc.readthedocs.io/en/latest/guide/network-builder/) for details.

---

## Visualization

`memq_dqc.visualization` provides SVG-based views of the compilation output:

```python
from memq_dqc.visualization import (
    plot_distributed_circuit,  # gate layout across QPUs
    plot_partition_flow,  # qubit migration across QPUs
    plot_partition_heatmap,  # QPU assignment heatmap per window
    plot_migration_timeline,  # qubit movement timeline with EPR cost
    plot_circuit_dag,  # circuit DAG
    plot_operation_gantt,  # operation Gantt chart
    write_svg_dashboard_html,  # bundle panels into an HTML viewer
)
```

### Animated execution playback

`animate_circuit_execution` plays a schedule back over the network graph,
highlighting the physical qubits and links carrying each operation as the
distributed circuit executes:

```python
from memq_dqc.visualization import animate_circuit_execution

animation = animate_circuit_execution(network, scheduler.schedule)
animation.show()  # interactive window with play/pause and a scrubber
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

### Docs

The docs site (config, API reference generation, demo notebooks) lives under `docs/`.

    uv sync --group docs                              # install docs dependencies
    uv run mkdocs serve -f docs/mkdocs.yml             # live preview at http://127.0.0.1:8000
    uv run mkdocs build -f docs/mkdocs.yml --strict    # build to ./site (fails on warnings)
