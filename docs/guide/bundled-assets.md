# Bundled Networks & Circuits

The library ships a small suite of reference networks and circuits inside the
installed package, so you can run the full workflow before writing a topology
of your own. They are reachable through `memq_dqc.assets`, which returns
`pathlib.Path` objects — exactly what `Compiler`, `Partitioner`, and
`NetworkGraph` already accept.

```python
from memq_dqc import Compiler
from memq_dqc.assets import circuit_path, network_path

compiler = Compiler(
    circuit_path("qft_n10"),
    network_path("10_qubits/n2_pair_nn"),
)
compiler.compile()
```

## Discovering what is available

```python
from memq_dqc.assets import list_circuits, list_networks

list_circuits()  # ['adder_n28', 'multiply_n13', 'qft_n10', ...]
list_networks()  # ['10_qubits/n2_pair_a2a', '10_qubits/n2_pair_nn', ...]
```

## Circuits

Ten transpiled OpenQASM programs spanning 4 to 60 qubits, named
`<algorithm>_n<qubits>`. The `.qasm` extension is optional in
`circuit_path()`.

| Circuit | Qubits | `"sampling"` | `"statevector"` |
|---|---|---|---|
| `qft_n4` | 4 | yes | yes |
| `qft_n5` | 5 | yes | yes |
| `qft_n10` | 10 | yes | yes |
| `multiply_n13` | 13 | yes | yes |
| `qft_n18` | 18 | no | yes |
| `qft_n20` | 20 | no | yes |
| `adder_n28` | 28 | yes | too wide |
| `qft_n29` | 29 | no | too wide |
| `qft_n40` | 40 | no | too wide |
| `qft_n60` | 60 | no | too wide |

Every circuit is OpenQASM 3.0 and fully measured: each declares a `bit[n] c`
register and ends with one explicit `c[i] = measure q[i];` per qubit, rather
than a bulk register-to-register measurement. That makes them usable as
verification inputs, not just compilation inputs.

The two columns are the two verification methods, and they fail in opposite
directions — between them they cover every circuit up to `qft_n20`.

`Compiler.verify()` uses **sampling**: it simulates both circuits and compares
output distributions by Hellinger fidelity. That needs the distribution to be
concentrated enough to estimate from a feasible shot count. `adder_n28` passes
at 28 qubits because its output is a single computational basis state; a wide
QFT spreads amplitude across all 2ⁿ outcomes, so `qft_n18` reaches only 0.26
fidelity even at 200 000 shots, against a 0.9 threshold.

Where sampling starves, use the exact **statevector** method instead. It is
deterministic, needs no shots, and confirms the wide QFTs outright:

```python
from memq_dqc import get_verification_artifacts
from memq_dqc.assets import circuit_path, network_path
from memq_dqc.verify import verify_distributed_circuit

artifacts = get_verification_artifacts(
    str(circuit_path("qft_n18")),
    str(network_path("20_qubits/n2_pair_nn")),
)
verify_distributed_circuit(
    artifacts.original_program,
    artifacts.distributed_program,
    method="statevector",
)  # True
```

!!! warning "The statevector ceiling counts communication qubits"

    Statevector verification holds ~2ⁿ amplitudes in memory and refuses to run
    past `max_qubits` (default 28). The **n** it measures is the width of the
    *distributed* circuit — data qubits plus the communication qubits the
    network adds — not the original circuit's qubit count.

    So `adder_n28` is out of reach despite being exactly 28 qubits: on
    `30_qubits/n2_pair_nn` its distributed form is 34 qubits wide. Choosing a
    network with fewer QPUs, and therefore fewer communication qubits, lowers
    that width.

Neither limit is a compilation failure. Every bundled circuit partitions and
reconstructs; what varies is whether the result can be checked at that width.

!!! note "More sophisticated verification is coming soon"

    Sampling and statevector are today's two verification methods, and each
    has a ceiling — sampling on distribution concentration, statevector on
    qubit count. A more scalable verification approach that lifts these
    limits is planned.

## Networks

Networks are grouped by the circuit size they are built to host, and named
`n<QPUs>_<arrangement>_<variant>` within each group — so a full name looks like
`30_qubits/n4_hub_nn`.

The size directory is a **capacity, not an exact match**: a network sized for
30-qubit circuits hosts any circuit of 30 qubits or fewer. Data qubits per QPU
are `ceil(circuit_qubits / n)` and identical on every QPU, so rounding up may
leave a few spare data qubits.

Available sizes: 10, 20, 30, 40, and 60 qubits.

### Arrangements

| Arrangement | Shape | Why it is here |
|---|---|---|
| `pair` | two QPUs, one edge | minimal distributed case; every non-local gate crosses the same cut |
| `chain` | open line | linear diameter, hot middle cuts — the stress case for partitioning |
| `ring` | closed cycle | uniform degree 2 and two routes between any pair, so routing can balance |
| `hub` | star | one central QPU relays everything; the bottleneck case |

### Variants

Each arrangement comes in two intra-QPU connectivity variants, so you can
isolate the effect of local connectivity while holding the inter-QPU
arrangement fixed:

- `_nn` — **nearest neighbour**: data qubits on a 2D grid with 4-way
  adjacency, communication qubits attached to one boundary data qubit each.
- `_a2a` — **all-to-all**: data qubits fully connected to each other,
  communication qubits connected to every data qubit. Communication qubits are
  never connected to one another.

### Shared invariants

- Every adjacent QPU pair is joined by **2** remote links.
- Each link owns a private pair of communication qubits, so a QPU carries
  `2 × degree` of them. Chain endpoints therefore have fewer communication
  qubits than interior QPUs, and a hub has the most.
- Coherence time is 100 µs on every qubit; fidelity is 1 on every remote link.
  No current partitioner or scheduler reads these, but they are carried in the
  format for coherence- and fidelity-aware algorithms later.

### Per-network documentation

Every network has a same-named Markdown file describing its arrangement, qubit
counts, degrees, and remote links in full:

```python
from memq_dqc.assets import network_doc_path

print(network_doc_path("30_qubits/n4_hub_nn").read_text())
```

## Beyond the bundled set

These are a starting point, not a benchmark suite. For your own topologies,
see the [Network Builder guide](network-builder.md) — it exports the same JSON
format.
