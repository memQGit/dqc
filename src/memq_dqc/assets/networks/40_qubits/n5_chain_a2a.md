# n5_chain_a2a

40-qubit circuit partitioned across 5 QPUs in a **chain** arrangement, **all-to-all** intra-QPU connectivity.

## Inter-QPU arrangement

QPUs in an open line. The end QPUs are not joined, so the diameter grows linearly and the middle cuts carry the most traffic -- the worst case for a naive partitioner.

```
QPU0 === QPU1 === QPU2 === QPU3 === QPU4
```

Every drawn edge is **2 independent remote links**, and each link owns its own dedicated pair of communication qubits (one on each side). Two QPUs can therefore hold two entangled pairs at once.

## At a glance

| | |
|---|---|
| Circuit qubits | 40 |
| QPUs | 5 |
| Data qubits per QPU | 8 (= ceil(40 / 5)) |
| Total data qubits | 40 |
| Spare data qubits | 0 |
| Communication qubits per QPU | QPU0: 2, QPU1: 4, QPU2: 4, QPU3: 4, QPU4: 2 |
| Total communication qubits | 16 |
| Total physical qubits | 56 |
| QPU-to-QPU edges | 4 |
| Remote links | 8 |
| Local couplings | 268 |

## Intra-QPU connectivity

Data qubits form a complete graph -- every data qubit is directly coupled to every other data qubit on the same QPU. Each communication qubit is coupled to every data qubit on its QPU. Communication qubits are never coupled to one another locally.

## QPU degrees and communication qubits

| QPU | Neighbours | Degree | Comm qubits |
|---|---|---|---|
| 0 | 1 | 1 | 2 |
| 1 | 0, 2 | 2 | 4 |
| 2 | 1, 3 | 2 | 4 |
| 3 | 2, 4 | 2 | 4 |
| 4 | 3 | 1 | 2 |

Communication qubits are allocated per neighbour: QPU *p*'s *k*-th neighbour (in ascending QPU order) owns comm qubits `c_p_{2k}` and `c_p_{2k+1}`.

## Remote links

| Link | Endpoint A | Endpoint B | Fidelity |
|---|---|---|---|
| 0 | `c_0_0` | `c_1_0` | 1 |
| 1 | `c_0_1` | `c_1_1` | 1 |
| 2 | `c_1_2` | `c_2_0` | 1 |
| 3 | `c_1_3` | `c_2_1` | 1 |
| 4 | `c_2_2` | `c_3_0` | 1 |
| 5 | `c_2_3` | `c_3_1` | 1 |
| 6 | `c_3_2` | `c_4_0` | 1 |
| 7 | `c_3_3` | `c_4_1` | 1 |

## Notes for compiler runs

* Data qubits are `q_<qpu>_<index>`, communication qubits are `c_<qpu>_<index>`. Only communication qubits carry `remoteConnections`.
* 0 spare data qubits beyond the 40 circuit qubits, because the per-QPU count is rounded up so all QPUs are identical.
* All qubits use a 100 us coherence time and all remote links a fidelity of 1; edit the JSON to sweep those.
* Pair this file with its nearest neighbour counterpart to isolate the effect of intra-QPU connectivity while the inter-QPU arrangement is held fixed.
