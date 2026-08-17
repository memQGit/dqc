# n3_ring_nn

10-qubit circuit partitioned across 3 QPUs in a **ring** arrangement, **nearest neighbour** intra-QPU connectivity.

## Inter-QPU arrangement

QPUs in a closed cycle. Every QPU has exactly two neighbours and there are two disjoint routes between any pair, so a router can balance load in either direction.

```
QPU0 === QPU1 === QPU2
  |                 |
  +-----------------+   (QPU2 wraps back to QPU0)
```

Every drawn edge is **2 independent remote links**, and each link owns its own dedicated pair of communication qubits (one on each side). Two QPUs can therefore hold two entangled pairs at once.

## At a glance

| | |
|---|---|
| Circuit qubits | 10 |
| QPUs | 3 |
| Data qubits per QPU | 4 (= ceil(10 / 3)) |
| Total data qubits | 12 |
| Spare data qubits | 2 |
| Communication qubits per QPU | 4 |
| Total communication qubits | 12 |
| Total physical qubits | 24 |
| QPU-to-QPU edges | 3 |
| Remote links | 6 |
| Local couplings | 24 |

## Intra-QPU connectivity

Data qubits sit on a 2 x 2 row-major grid with 4-way (up/down/left/right) adjacency. Each communication qubit hangs off a single data qubit on the grid boundary; the attachment points are spread evenly around the perimeter.

## QPU degrees and communication qubits

| QPU | Neighbours | Degree | Comm qubits |
|---|---|---|---|
| 0 | 1, 2 | 2 | 4 |
| 1 | 0, 2 | 2 | 4 |
| 2 | 0, 1 | 2 | 4 |

Communication qubits are allocated per neighbour: QPU *p*'s *k*-th neighbour (in ascending QPU order) owns comm qubits `c_p_{2k}` and `c_p_{2k+1}`.

## Remote links

| Link | Endpoint A | Endpoint B | Fidelity |
|---|---|---|---|
| 0 | `c_0_0` | `c_1_0` | 1 |
| 1 | `c_0_1` | `c_1_1` | 1 |
| 2 | `c_1_2` | `c_2_2` | 1 |
| 3 | `c_1_3` | `c_2_3` | 1 |
| 4 | `c_2_0` | `c_0_2` | 1 |
| 5 | `c_2_1` | `c_0_3` | 1 |

## Notes for compiler runs

* Data qubits are `q_<qpu>_<index>`, communication qubits are `c_<qpu>_<index>`. Only communication qubits carry `remoteConnections`.
* 2 spare data qubits beyond the 10 circuit qubits, because the per-QPU count is rounded up so all QPUs are identical.
* All qubits use a 100 us coherence time and all remote links a fidelity of 1; edit the JSON to sweep those.
* Pair this file with its all-to-all counterpart to isolate the effect of intra-QPU connectivity while the inter-QPU arrangement is held fixed.
