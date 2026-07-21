# Workflow & Architecture

xDQC turns a circuit and a network into a distributed, schedulable program.
This page describes the pipeline and the module layout behind it.

## The pipeline

```
OpenQASM circuit + network topology
        │  compile   (partition across QPUs, route inter-QPU gates)
        ▼
   distributed OpenQASM  ──►  verify  (Hellinger-fidelity check vs. original)
        │  schedule   (lay operations on a hardware timeline)
        ▼
     execution schedule  (minimize makespan)
```

1. **Load** — OpenQASM is loaded from disk
   (`xdqc.preprocessing.qasm.io.load_qasm_program`).
2. **Clean** — statements are cleaned into lightweight structures
   (`xdqc.preprocessing.qasm`).
3. **Build the DAG** — circuit operations are assembled into a circuit DAG
   (`xdqc.circuit.CircuitDAG`, built from `xdqc.circuit.Op` and
   `xdqc.circuit.Layer`).
4. **Partition** — the `Partitioner` assigns logical qubits to QPUs; the
   `Compiler` front end drives this for you (see
   [Partitioning Algorithms](partitioning.md)).
5. **Reconstruct** — inter-QPU gates are routed and the distributed circuit is
   extracted (`xdqc.builder.extract_distributed_circuit`), inserting the
   network primitives (cat-entanglement and remote gates).
6. **Verify** — the distributed circuit is rewritten to an equivalent
   monolithic circuit and both are simulated and compared
   (`xdqc.verify.verify_distributed_circuit`).
7. **Schedule** — the `Scheduler` lays the distributed operations on a hardware
   timeline, respecting data dependencies, communication-qubit availability,
   and per-operation durations, aiming to minimize the **makespan**.

The main workflow APIs can emit progress, timing, and debug diagnostics via the
`verbosity` controls on partitioning, extraction, and verification — see
[Logging & Verbosity](logging.md).

## Package layout

| Package | Responsibility |
| --- | --- |
| `xdqc.preprocessing.qasm` | Load and clean OpenQASM; extraction and IO helpers. |
| `xdqc.circuit` | Circuit representation: `Op` (`op.py`), `Layer` (`layer.py`), `Circuit` (`circuit.py`), and the DAG builders in the `dag/` subpackage (`mono`, `distributed`, `annotated`, `routing`, `remap`, `entanglement`, `swap_builders`). |
| `xdqc.network` | Network topology: `NetworkGraph`, `PhysicalQubit`, and config builders/validators. |
| `xdqc.partition` | Partitioning strategies and the `Partitioner` façade. |
| `xdqc.builder` | Distributed-circuit extraction (`circuit_extractor.py`, `extract_utils.py`). |
| `xdqc.verify` | Correctness checking of distributed circuits. |
| `xdqc.scheduler` | Schedulers (FIFO, ILP, discrete-event link schedulers) and scheduling-instance record types. |
| `xdqc.visualization` | SVG/matplotlib views of circuits, partitions, and schedules. |
| `xdqc.utils` | Shared circuit and partition helpers. |

## Public entry points

- `xdqc.Compiler` — recommended front end (compile → verify).
- `xdqc.Scheduler` — build an execution schedule from a compiler or a
  scheduling instance.
- `xdqc.Partitioner` — direct control over the partitioning step.
- `xdqc.get_verification_artifacts` — one call returning both circuits and
  their DAGs.
- `xdqc.compile_scheduling_instance` — a versioned, JSON-persistable
  scheduling instance for external schedulers (see the
  [Scheduling-Instance API](scheduling-instance-api.md)).

For the full symbol-level reference, see the
[API Reference](../reference/xdqc/index.md).
