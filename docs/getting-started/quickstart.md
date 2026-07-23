# Quickstart

This page compiles a circuit onto a network and verifies the result. It assumes
you have a circuit (`circuit.qasm`, OpenQASM 3.0) and a network topology
(`network.json`) to hand — the `demo/inputs/` directory in the repository has
working examples.

## The recommended entry point: `Compiler`

`Compiler` is the convenient front end for the whole compile → verify step. It
accepts file paths (as here), in-memory objects, or inline QASM source.

```python
from xdqc import Compiler

# Partition the circuit across QPUs and reconstruct a distributed circuit.
compiler = Compiler("circuit.qasm", "network.json", algo="interaction")
compiler.compile()

# The distributed circuit is a standard OpenQASM 3.0 program.
print(compiler.distributed_qasm)
compiler.save_distributed_circuit("distributed.qasm")

# Verify: rewrite to an equivalent monolithic circuit, simulate both, and
# compare output distributions. No need to re-supply the original circuit.
print("verified:", compiler.verify(shots=20000))
```

## Lower-level control: `Partitioner`

`Compiler` drives the lower-level `Partitioner` for you. If you want direct
control over the partitioning step, use it on its own:

```python
from xdqc.partition import Partitioner
from xdqc.builder import extract_distributed_circuit
from xdqc.verify import verify_distributed_circuit

partitioner = Partitioner("network.json", "circuit.qasm")
partitioner.run()

distributed = extract_distributed_circuit(partitioner)
is_valid = verify_distributed_circuit("circuit.qasm", "distributed.qasm")
```

`Partitioner` accepts either file paths or pre-loaded objects:

```python
from xdqc.network import NetworkGraph
from xdqc.preprocessing.qasm.io import load_qasm_program

network = NetworkGraph("network.json")
program = load_qasm_program("circuit.qasm")
partitioner = Partitioner(network, program)
```

## One-call artifacts

For one call that returns both circuits and their DAGs — handy for analysis and
verification — use `get_verification_artifacts`:

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

## Next steps

- Walk the full workflow end to end in the
  [Demo Walkthrough](../demo.md).
- Choose a partitioning strategy in
  [Partitioning Algorithms](../guide/partitioning.md).
- Lay operations on a hardware timeline — see
  [Workflow & Architecture](../guide/workflow.md).
