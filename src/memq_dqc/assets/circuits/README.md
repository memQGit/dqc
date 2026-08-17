# Reference circuits

Transpiled OpenQASM programs for exercising the compiler, spanning 4 to 60
qubits. They ship inside the installed package and are reachable through
`memq_dqc.assets`:

```python
from memq_dqc.assets import circuit_path, list_circuits

circuit_path("qft_n10")
```

Files are named `<algorithm>_n<qubits>.qasm`. Pair one with any network sized
to hold at least that many qubits — see [`../networks/README.md`](../networks/README.md).

| Circuit | Qubits | Smallest network that hosts it | `"sampling"` | `"statevector"` |
|---|---|---|---|---|
| `qft_n4` | 4 | `10_qubits/` | yes | yes |
| `qft_n5` | 5 | `10_qubits/` | yes | yes |
| `qft_n10` | 10 | `10_qubits/` | yes | yes |
| `multiply_n13` | 13 | `20_qubits/` | yes | yes |
| `qft_n18` | 18 | `20_qubits/` | no | yes |
| `qft_n20` | 20 | `20_qubits/` | no | yes |
| `adder_n28` | 28 | `30_qubits/` | yes | too wide |
| `qft_n29` | 29 | `30_qubits/` | no | too wide |
| `qft_n40` | 40 | `40_qubits/` | no | too wide |
| `qft_n60` | 60 | `60_qubits/` | no | too wide |

## Measurements

Every circuit is OpenQASM 3.0 and fully measured. Each declares a single
`bit[n] c` register and ends with one explicit measurement per qubit:

```
c[0] = measure q[0];
c[1] = measure q[1];
...
```

rather than a bulk `measure q -> c;`. The gate sequence ahead of the
measurements is byte-for-byte the transpiler output these circuits were sourced
from — adding measurements did not reorder or re-synthesize anything.

The last two columns are the two verification methods, which fail in opposite
directions. Sampling — what `Compiler.verify()` uses — needs a concentrated
output distribution, so a wide QFT starves it. The exact `"statevector"` method
of `verify_distributed_circuit` covers those, but refuses to run past
`max_qubits` (default 28) measured on the *distributed* circuit, communication
qubits included: `adder_n28` is 34 qubits wide once distributed over
`30_qubits/n2_pair_nn`.

Neither limit is a compilation failure — every circuit here partitions and
reconstructs. See the [guide](https://dqc.readthedocs.io/en/latest/guide/bundled-assets/)
for the statevector example.
