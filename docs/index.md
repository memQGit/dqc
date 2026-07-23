# memQ Distributed Quantum Compiler

<div class="memq-hero" markdown>

An open-source Python library for **distributed quantum compilation**. Given a
quantum circuit and a network topology, it partitions the circuit across QPUs,
routes inter-QPU gates, and reconstructs a distributed circuit ready for
execution or further analysis.

</div>

xDQC is designed to be **modular and plug-and-play**: researchers can run
the full compilation workflow in a few lines of code, swap in different
partitioning algorithms, and benchmark them against each other across circuits
and network topologies.

## The workflow

```
OpenQASM circuit + network topology
        │  compile
        ▼
   distributed OpenQASM  ──►  verify  (is it still correct?)
        │  schedule
        ▼
     execution schedule
```

The whole pipeline is driven by two objects — `Compiler` and `Scheduler`:

```python
from xdqc import Compiler, Scheduler

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

- :material-download: **[Installation](getting-started/installation.md)** —
  set up the library with `uv`.
- :material-rocket-launch: **[Quickstart](getting-started/quickstart.md)** —
  compile and verify your first circuit.
- :material-sitemap: **[Workflow & Architecture](guide/workflow.md)** — how the
  compile → verify → schedule pipeline fits together.
- :material-book-open-variant: **[API Reference](reference/xdqc/index.md)** —
  auto-generated from the source docstrings.

</div>
