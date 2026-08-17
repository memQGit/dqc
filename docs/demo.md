# Demo Walkthrough

This walkthrough covers the **entire** memQ distributed-compilation workflow —
compile, verify, schedule — and shows just how little code it takes. It mirrors
the runnable notebook at
[`demo/demo.ipynb`](https://github.com/memQGit/dqc/blob/main/demo/demo.ipynb);
run that notebook to reproduce the outputs interactively.

The whole workflow is driven by two objects — and they are the only things we
import:

```python
from memq_dqc import Compiler, Scheduler
```

## 1. Inputs

The compiler takes two plain-text inputs:

1. **A circuit** — an OpenQASM 3.0 file. Here, a 4-qubit Quantum Fourier
   Transform (`qft_n4.qasm`).
2. **A network topology** — a JSON file. Here, `demo_network`: two QPUs
   (`P0`, `P1`), each with 2 computation + 2 communication qubits, linked by a
   remote (entanglement) connection between their communication qubits.

## 2. Compile

The whole compilation step is **two calls**. `Compiler` takes the circuit and
network directly (file paths, in-memory objects, or inline QASM source), then
`compile()` partitions the circuit's logical qubits across QPUs and
reconstructs a distributed circuit that inserts the network primitives needed
to run two-qubit gates across QPUs.

```python
compiler = Compiler(
    "inputs/qft_n4.qasm",
    "inputs/demo_network.json",
    algo="interaction",
)
compiler.compile()

print(
    "network:",
    compiler.network.num_qpus,
    "QPUs |",
    compiler.network.num_comp_qubits,
    "computation +",
    compiler.network.num_comm_qubits,
    "communication qubits",
)
```

The distributed circuit is a standard OpenQASM 3.0 program — the compiler's
primary output. Read it as a string (`distributed_qasm`) and write it to disk
(`save_distributed_circuit`). Note the per-QPU data registers (`q0`, `q1`),
the matching communication registers (`c0`, `c1`), and the `catent` →
remote-gate → `catdisent` sequences that implement each cross-QPU gate.

```python
compiler.save_distributed_circuit("outputs/qft_n4_distributed.qasm")
print(compiler.distributed_qasm)
```

## 3. The network primitives

The distributed circuit uses a handful of custom gates that stand in for the
networking operations a distributed quantum computer must perform:

- **Remote gates** — `rcx`, `rcp`, `rcz`, `rcry` carry out a two-qubit gate
  between data qubits that physically live on **different** QPUs, without ever
  moving those data qubits. `rswap` performs **state teleportation**, actually
  moving a qubit's state from one QPU to another.
- **Cat-entanglement** — every remote gate is wrapped in a cat-entanglement
  (`catent`) / cat-disentanglement (`catdisent`) pair that consumes an
  entangled (EPR) pair on the communication qubits.

## 4. Verify

Is the distributed circuit still correct? `compiler.verify()` checks it
directly — no need to re-supply the original circuit, since the compiler
already has it. Under the hood it rewrites the distributed circuit into an
equivalent **monolithic** circuit (each remote gate replaced by its local
equivalent — `rcx`→`cx`, `rcp`→`cp`, …, `rswap`→`swap` — and the entanglement
scaffolding dropped), simulates both, and compares their output distributions
via **Hellinger fidelity**.

```python
print("verified:", compiler.verify(shots=20000, verbosity="info"))
```

## 5. Schedule

Finally, the `Scheduler` lays the distributed circuit's operations out on a
timeline — respecting data dependencies, communication-qubit availability, and
how long each operation takes on real hardware — aiming to minimize the
**makespan** (total execution time). Hand it the `compiler` directly. The
hardware is chosen with two strings: a *modality* (here `neutral_atom`, which
sets local gate times) and an *entanglement profile* (here an illustrative
`demo.demo`, which sets the entanglement-generation rate).

```python
scheduler = Scheduler(
    compiler,
    algo="des_link_fifo",
    modality="neutral_atom",
    entanglement_profile="demo.demo",
    algo_kwargs={"seed": 0},
)
scheduler.run()

print(
    "makespan:",
    round(scheduler.schedule.makespan, 1),
    "µs |",
    "scheduled events:",
    len(scheduler.schedule.operations),
)

scheduler.plot_gantt(
    title="Execution schedule — qft_n4",
    display="legacy",
    save_path="outputs/schedule_gantt.png",
)
```

Each row is a physical qubit. The communication qubits (`c…`) generate
entanglement (`epr`) and run the `catent`/`catdisent` halves of each remote
gate, while the data qubits (`q…`) carry the local gates and final
measurements.

## What you produced

From two plain-text inputs and a handful of lines — importing nothing but
`Compiler` and `Scheduler` — the workflow produced:

| File | What it is |
| --- | --- |
| `outputs/qft_n4_distributed.qasm` | The distributed circuit — standard OpenQASM 3.0. |
| `outputs/schedule_gantt.png` | The execution-schedule Gantt chart. |

…plus a verification check confirming the distributed circuit still computes
the original result.
