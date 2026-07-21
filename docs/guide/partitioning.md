# Partitioning Algorithms

Partitioning assigns the circuit's logical qubits to QPUs so that inter-QPU
gates — the expensive, entanglement-consuming operations — are minimized. Pass
`algo=` to `Compiler` or `Partitioner` to select a strategy. The default is
`"interaction"`.

| Algorithm | Description |
| --- | --- |
| `interaction` | Interaction-graph based partitioning (default). |
| `hypergraph` | Hypergraph partitioning (KaHyPar). |
| `benchmark_static` | Static baseline — deterministic reference. |
| `benchmark_random` | Random baseline — stochastic reference. |

```python
from xdqc import Compiler

compiler = Compiler("circuit.qasm", "network.json", algo="hypergraph")
compiler.compile()
```

Or with the lower-level `Partitioner`:

```python
from xdqc.partition import Partitioner

partitioner = Partitioner("network.json", "circuit.qasm", algo="hypergraph")
partitioner.run()
```

## Benchmarking strategies

The baselines exist so new algorithms can be measured against a fixed
reference. `benchmark_static` is deterministic and `benchmark_random` is
stochastic (seed it for reproducibility). A typical comparison compiles the
same circuit/network pair under several strategies and compares the resulting
inter-QPU communication cost or schedule makespan.

Each strategy is a class under `xdqc.partition` — `InteractionPartitioner`,
`HypergraphPartitioner`, `BenchmarkStaticPartitioner`,
and `BenchmarkRandomPartitioner`. See the
[`xdqc.partition` API reference](../reference/xdqc/partition/index.md) for their
constructors and options.
