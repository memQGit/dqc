# DQC — Distributed Quantum Compiler

!!! warning "Version 0.1.2 — beta, experimental"

    DQC is an early release. It is usable for research and benchmarking, but
    the public API may change in any minor release before `1.0.0`. Pin an
    exact version if you depend on it, and check the
    [changelog](https://github.com/memQGit/dqc/blob/main/CHANGELOG.md) for
    what moved between releases.

<div class="memq-hero" markdown>

An open-source Python library for **distributed quantum compilation**. Given a
quantum circuit and a network topology, it partitions the circuit across QPUs,
routes inter-QPU gates, and reconstructs a distributed circuit ready for
execution or further analysis.

</div>

## The workflow

```
OpenQASM circuit + network topology
        │  compile
        ▼
   distributed OpenQASM  ──►  verify  (circuit equivalence)
        │  schedule
        ▼
     execution schedule
```

The whole pipeline is driven by two objects — `Compiler` and `Scheduler`:

```python
from memq_dqc import Compiler, Scheduler

# Compile: partition across QPUs and reconstruct a distributed circuit.
compiler = Compiler("circuit.qasm", "network.json", algo="interaction")
compiler.compile()

# Verify the distributed circuit against the original.
assert compiler.verify()

# Schedule the distributed operations onto a hardware timeline.
scheduler = Scheduler(compiler, algo="des_link_fifo", modality="neutral_atom")
scheduler.run()
print("makespan:", scheduler.schedule.makespan)
```

## Where to go next

<div class="grid cards" markdown>

- :material-puzzle-outline: **[Key Features](key-features.md)** — what goes in
  and comes out, the nine packages, and how few of them a change touches.
- :material-download: **[Installation](getting-started/installation.md)** —
  set up the library with `uv`.
- :material-rocket-launch: **[Quickstart](getting-started/quickstart.md)** —
  compile and verify your first circuit.
- :material-sitemap: **[Workflow & Architecture](guide/workflow.md)** — how the
  compile → verify → schedule pipeline fits together.
- :material-book-open-variant: **[API Reference](reference/memq_dqc/index.md)** —
  auto-generated from the source docstrings.

</div>
