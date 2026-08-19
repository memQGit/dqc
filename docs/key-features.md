# Key Features

## 1. A complete compilation pipeline, in standard formats

DQC takes an **OpenQASM 3 circuit** and a **JSON network topology**, and
returns an **OpenQASM 3 circuit** — no proprietary IR to learn, and no lock-in
at either end. In between, it partitions logical qubits across QPUs, routes
inter-QPU gates through entanglement-mediated operations, reconstructs a valid
distributed program, and builds an execution schedule against a hardware
timing model.

```python
from memq_dqc import Compiler, Scheduler

compiler = Compiler("circuit.qasm", "network.json", algo="interaction")
compiler.compile()
assert compiler.verify()  # simulate both, compare distributions

scheduler = Scheduler(compiler, algo="des_link_fifo", modality="neutral_atom")
scheduler.run()
print("makespan:", scheduler.schedule.makespan)
```

Every intermediate artifact is inspectable and serializable: the circuit DAG,
the partition assignment, the distributed circuit, the annotated DAG, and the
schedule all round-trip through JSON. Correctness is checkable rather than
assumed — `verify()` rewrites the distributed circuit back to an equivalent
monolithic one, simulates both, and compares output distributions.

Nothing is required to get started. The library ships **40 network
topologies** and **10 transpiled circuits** (4–60 qubits) inside the installed
package, so the full workflow runs before you have written a topology of your
own.

## 2. Modular design

The pipeline is nine packages, each owning exactly one stage. You import from
the ones your work touches and ignore the rest.

- **[`memq_dqc`][memq_dqc]** — the two front doors, [`Compiler`][memq_dqc.Compiler]
  and [`Scheduler`][memq_dqc.Scheduler], plus settings and the
  scheduling-instance API. Most workflows never import anything else.
- **[`memq_dqc.preprocessing.qasm`][memq_dqc.preprocessing.qasm]** — parses
  OpenQASM 3 into the internal representation and writes it back out.
- **[`memq_dqc.circuit`][memq_dqc.circuit]** — circuits, operations, layers,
  and the DAGs (monolithic, distributed, and annotated) that every later stage
  consumes.
- **[`memq_dqc.network`][memq_dqc.network]** —
  [`NetworkGraph`][memq_dqc.network.NetworkGraph]: QPUs, their data and
  communication qubits, and the links between them, built from a canonical
  JSON topology.
- **[`memq_dqc.partition`][memq_dqc.partition]** — maps logical qubits onto
  QPUs. Five algorithms ship;
  [`BasePartitioner`][memq_dqc.partition.BasePartitioner] is the one class you
  subclass to add a sixth.
- **[`memq_dqc.builder`][memq_dqc.builder]** — reconstructs a valid distributed
  OpenQASM program from a partition, inserting the teleportation and
  cat-entanglement machinery remote gates require.
- **[`memq_dqc.scheduler`][memq_dqc.scheduler]** — places distributed
  operations on a timeline under a hardware model. Four schedulers ship,
  including three discrete-event link-arbitration policies.
- **[`memq_dqc.verify`][memq_dqc.verify]** — checks a distributed circuit
  against its original by simulation.
- **[`memq_dqc.visualization`][memq_dqc.visualization]** — ten plotting and
  animation entry points covering DAGs, partitions, schedules, and animated
  network playback.

**The point of this layout is how little of it you need to touch.** Each row
below is a complete answer — one module, nothing else:

| To change… | Touch | Everything else |
| --- | --- | --- |
| the partitioning algorithm | `memq_dqc.partition` | unchanged |
| the scheduling policy | `memq_dqc.scheduler` | unchanged |
| the network topology | a JSON file | no code at all |
| the hardware timing model | a modality profile | no code at all |
| how results are drawn | `memq_dqc.visualization` | unchanged |

A new partitioning algorithm does not know that schedulers exist. A new
scheduler does not know how partitioning happened. Both are handed a
fully-formed object and asked one question.

## 3. Extensibility and benchmarking

Adding a partitioning algorithm means implementing **one method**. Subclass
[`BasePartitioner`][memq_dqc.partition.BasePartitioner], fill in `run()`, and
set the placement it produced:

```python
from memq_dqc import Compiler
from memq_dqc.partition import BasePartitioner, QPU


class MyPartitioner(BasePartitioner):
    """self.network and self.circuit are provided; set the placement."""

    def run(self) -> None:
        self.schedule = [{QPU(id=0): {0, 1, 2, 3, 4}, QPU(id=1): {5, 6, 7, 8, 9}}]
        self.windows = [self.circuit.mono.ops]


compiler = Compiler("circuit.qasm", "network.json", algo=MyPartitioner)
compiler.compile()
```

From that point your algorithm is a first-class citizen: routing, circuit
reconstruction, verification, scheduling, and every visualization work on it
exactly as they do on the built-in strategies. There is no registration step
and no plugin manifest — `algo` accepts a name, a class, or a configured
instance.

That symmetry is what makes DQC a benchmarking platform rather than a single
compiler. Because every algorithm implements the same interface and every
topology is data, comparing five partitioners across forty networks is a loop,
not a porting effort — and because the same `verify()` runs against all of
them, a strategy that is fast but wrong cannot hide.
