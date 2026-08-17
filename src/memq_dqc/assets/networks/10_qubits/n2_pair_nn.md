# n2_pair_nn

10-qubit circuit partitioned across 2 QPUs in a **pair** arrangement, **nearest neighbour** intra-QPU connectivity.

## Inter-QPU arrangement

Two QPUs joined directly. The minimal distributed case: every non-local gate crosses the one and only cut.

```
QPU0 === QPU1
```

Every drawn edge is **2 independent remote links**, and each link owns its own dedicated pair of communication qubits (one on each side). Two QPUs can therefore hold two entangled pairs at once.

## At a glance

| | |
|---|---|
| Circuit qubits | 10 |
| QPUs | 2 |
| Data qubits per QPU | 5 (= ceil(10 / 2)) |
| Total data qubits | 10 |
| Spare data qubits | 0 |
| Communication qubits per QPU | 2 |
| Total communication qubits | 4 |
| Total physical qubits | 14 |
| QPU-to-QPU edges | 1 |
| Remote links | 2 |
| Local couplings | 14 |

## Intra-QPU connectivity

Data qubits sit on a 3 x 2 row-major grid with 4-way (up/down/left/right) adjacency. Each communication qubit hangs off a single data qubit on the grid boundary; the attachment points are spread evenly around the perimeter.

## QPU degrees and communication qubits

| QPU | Neighbours | Degree | Comm qubits |
|---|---|---|---|
| 0 | 1 | 1 | 2 |
| 1 | 0 | 1 | 2 |

Communication qubits are allocated per neighbour: QPU *p*'s *k*-th neighbour (in ascending QPU order) owns comm qubits `c_p_{2k}` and `c_p_{2k+1}`.

## Remote links

| Link | Endpoint A | Endpoint B | Fidelity |
|---|---|---|---|
| 0 | `c_0_0` | `c_1_0` | 1 |
| 1 | `c_0_1` | `c_1_1` | 1 |

## Notes for compiler runs

* Data qubits are `q_<qpu>_<index>`, communication qubits are `c_<qpu>_<index>`. Only communication qubits carry `remoteConnections`.
* 0 spare data qubits beyond the 10 circuit qubits, because the per-QPU count is rounded up so all QPUs are identical.
* All qubits use a 100 us coherence time and all remote links a fidelity of 1; edit the JSON to sweep those.
* Pair this file with its all-to-all counterpart to isolate the effect of intra-QPU connectivity while the inter-QPU arrangement is held fixed.
