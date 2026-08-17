# Reference networks

A small, hand-picked suite of distributed-quantum-computer networks for exercising the compiler. They ship inside the installed package and are reachable through `memq_dqc.assets`:

```python
from memq_dqc.assets import list_networks, network_path

network_path("30_qubits/n4_hub_nn")
```

## Layout

Networks are grouped by the size of the circuit they are meant to host. Within a size directory, files are named `n<QPUs>_<arrangement>_<variant>.json`:

* `_nn` -- **nearest neighbour**: data qubits on a 2D grid with 4-way adjacency, communication qubits attached to one boundary data qubit each.
* `_a2a` -- **all-to-all**: data qubits fully connected to each other, communication qubits connected to every data qubit. Communication qubits are never connected to each other.

Each `.json` has a same-named `.md` describing it in full.

## Invariants

* Data qubits per QPU = `ceil(circuit_qubits / n)`, identical on every QPU. Rounding up leaves a few spare data qubits.
* Every adjacent QPU pair is joined by **2** remote links.
* Each link owns a private pair of communication qubits, so a QPU carries `2 x degree` of them. Chain endpoints therefore have fewer communication qubits than interior QPUs, and a hub has the most.
* Coherence time 100 us on every qubit; fidelity 1 on every remote link.

## Arrangements

| Arrangement | Shape | Why it is here |
|---|---|---|
| `pair` | two QPUs, one edge | minimal distributed case; every non-local gate crosses the same cut |
| `chain` | open line | linear diameter, hot middle cuts -- the stress case for partitioning |
| `ring` | closed cycle | uniform degree 2 and two routes between any pair, so routing can balance |
| `hub` | star | one central QPU relays everything; the bottleneck case |

## Index

### [10-qubit circuits](10_qubits/)

* [`n2_pair_nn`](10_qubits/n2_pair_nn.md) -- 2 QPUs, pair, nearest neighbour
* [`n2_pair_a2a`](10_qubits/n2_pair_a2a.md) -- 2 QPUs, pair, all-to-all
* [`n3_ring_nn`](10_qubits/n3_ring_nn.md) -- 3 QPUs, ring, nearest neighbour
* [`n3_ring_a2a`](10_qubits/n3_ring_a2a.md) -- 3 QPUs, ring, all-to-all
* [`n3_chain_nn`](10_qubits/n3_chain_nn.md) -- 3 QPUs, chain, nearest neighbour
* [`n3_chain_a2a`](10_qubits/n3_chain_a2a.md) -- 3 QPUs, chain, all-to-all

### [20-qubit circuits](20_qubits/)

* [`n2_pair_nn`](20_qubits/n2_pair_nn.md) -- 2 QPUs, pair, nearest neighbour
* [`n2_pair_a2a`](20_qubits/n2_pair_a2a.md) -- 2 QPUs, pair, all-to-all
* [`n4_ring_nn`](20_qubits/n4_ring_nn.md) -- 4 QPUs, ring, nearest neighbour
* [`n4_ring_a2a`](20_qubits/n4_ring_a2a.md) -- 4 QPUs, ring, all-to-all
* [`n4_chain_nn`](20_qubits/n4_chain_nn.md) -- 4 QPUs, chain, nearest neighbour
* [`n4_chain_a2a`](20_qubits/n4_chain_a2a.md) -- 4 QPUs, chain, all-to-all

### [30-qubit circuits](30_qubits/)

* [`n2_pair_nn`](30_qubits/n2_pair_nn.md) -- 2 QPUs, pair, nearest neighbour
* [`n2_pair_a2a`](30_qubits/n2_pair_a2a.md) -- 2 QPUs, pair, all-to-all
* [`n3_chain_nn`](30_qubits/n3_chain_nn.md) -- 3 QPUs, chain, nearest neighbour
* [`n3_chain_a2a`](30_qubits/n3_chain_a2a.md) -- 3 QPUs, chain, all-to-all
* [`n3_ring_nn`](30_qubits/n3_ring_nn.md) -- 3 QPUs, ring, nearest neighbour
* [`n3_ring_a2a`](30_qubits/n3_ring_a2a.md) -- 3 QPUs, ring, all-to-all
* [`n4_hub_nn`](30_qubits/n4_hub_nn.md) -- 4 QPUs, hub, nearest neighbour
* [`n4_hub_a2a`](30_qubits/n4_hub_a2a.md) -- 4 QPUs, hub, all-to-all

### [40-qubit circuits](40_qubits/)

* [`n2_pair_nn`](40_qubits/n2_pair_nn.md) -- 2 QPUs, pair, nearest neighbour
* [`n2_pair_a2a`](40_qubits/n2_pair_a2a.md) -- 2 QPUs, pair, all-to-all
* [`n5_hub_nn`](40_qubits/n5_hub_nn.md) -- 5 QPUs, hub, nearest neighbour
* [`n5_hub_a2a`](40_qubits/n5_hub_a2a.md) -- 5 QPUs, hub, all-to-all
* [`n5_chain_nn`](40_qubits/n5_chain_nn.md) -- 5 QPUs, chain, nearest neighbour
* [`n5_chain_a2a`](40_qubits/n5_chain_a2a.md) -- 5 QPUs, chain, all-to-all
* [`n5_ring_nn`](40_qubits/n5_ring_nn.md) -- 5 QPUs, ring, nearest neighbour
* [`n5_ring_a2a`](40_qubits/n5_ring_a2a.md) -- 5 QPUs, ring, all-to-all

### [60-qubit circuits](60_qubits/)

* [`n2_pair_nn`](60_qubits/n2_pair_nn.md) -- 2 QPUs, pair, nearest neighbour
* [`n2_pair_a2a`](60_qubits/n2_pair_a2a.md) -- 2 QPUs, pair, all-to-all
* [`n3_ring_nn`](60_qubits/n3_ring_nn.md) -- 3 QPUs, ring, nearest neighbour
* [`n3_ring_a2a`](60_qubits/n3_ring_a2a.md) -- 3 QPUs, ring, all-to-all
* [`n3_chain_nn`](60_qubits/n3_chain_nn.md) -- 3 QPUs, chain, nearest neighbour
* [`n3_chain_a2a`](60_qubits/n3_chain_a2a.md) -- 3 QPUs, chain, all-to-all
* [`n4_hub_nn`](60_qubits/n4_hub_nn.md) -- 4 QPUs, hub, nearest neighbour
* [`n4_hub_a2a`](60_qubits/n4_hub_a2a.md) -- 4 QPUs, hub, all-to-all
* [`n4_chain_nn`](60_qubits/n4_chain_nn.md) -- 4 QPUs, chain, nearest neighbour
* [`n4_chain_a2a`](60_qubits/n4_chain_a2a.md) -- 4 QPUs, chain, all-to-all
* [`n4_ring_nn`](60_qubits/n4_ring_nn.md) -- 4 QPUs, ring, nearest neighbour
* [`n4_ring_a2a`](60_qubits/n4_ring_a2a.md) -- 4 QPUs, ring, all-to-all
