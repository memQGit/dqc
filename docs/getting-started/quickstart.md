# Quickstart

This page compiles a circuit onto a network and verifies the result. You need a
circuit (OpenQASM) and a network topology (`network.json`) — and if you don't
have either yet, the library ships a reference set you can use straight away:

```python
from memq_dqc import Compiler
from memq_dqc.assets import circuit_path, network_path

compiler = Compiler(circuit_path("qft_n10"), network_path("10_qubits/n2_pair_nn"))
compiler.compile()
print("verified:", compiler.verify(shots=20000))
```

`list_circuits()` and `list_networks()` from the same module enumerate what is
available; see [Bundled Networks & Circuits](../guide/bundled-assets.md) for
the full catalogue. The examples that follow use `circuit.qasm` and
`network.json` as stand-ins for your own files.

## The recommended entry point: `Compiler`

`Compiler` is the convenient front end for the whole compile → verify step. It
accepts file paths (as here), in-memory objects, or inline QASM source.

```python
from memq_dqc import Compiler

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
from memq_dqc.partition import Partitioner
from memq_dqc.builder import extract_distributed_circuit
from memq_dqc.verify import verify_distributed_circuit

partitioner = Partitioner("network.json", "circuit.qasm")
partitioner.run()

distributed = extract_distributed_circuit(partitioner)
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

## One-call artifacts

For one call that returns both circuits and their DAGs — handy for analysis and
verification — use `get_verification_artifacts`:

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

## Next steps

- Walk the full workflow end to end in the
  [Demo Walkthrough](../demo.md).
- Choose a partitioning strategy in
  [Partitioning Algorithms](../guide/partitioning.md).
- Lay operations on a hardware timeline — see
  [Workflow & Architecture](../guide/workflow.md).
