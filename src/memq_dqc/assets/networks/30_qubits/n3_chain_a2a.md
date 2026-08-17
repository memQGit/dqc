# n3_chain_a2a

30-qubit circuit partitioned across 3 QPUs in a **chain** arrangement, **all-to-all** intra-QPU connectivity.

## Inter-QPU arrangement

QPUs in an open line. The end QPUs are not joined, so the diameter grows linearly and the middle cuts carry the most traffic -- the worst case for a naive partitioner.

```
QPU0 === QPU1 === QPU2
```

Every drawn edge is **2 independent remote links**, and each link owns its own dedicated pair of communication qubits (one on each side). Two QPUs can therefore hold two entangled pairs at once.

## At a glance

| | |
|---|---|
| Circuit qubits | 30 |
| QPUs | 3 |
| Data qubits per QPU | 10 (= ceil(30 / 3)) |
| Total data qubits | 30 |
| Spare data qubits | 0 |
| Communication qubits per QPU | QPU0: 2, QPU1: 4, QPU2: 2 |
| Total communication qubits | 8 |
| Total physical qubits | 38 |
| QPU-to-QPU edges | 2 |
| Remote links | 4 |
| Local couplings | 215 |

## Intra-QPU connectivity

Data qubits form a complete graph -- every data qubit is directly coupled to every other data qubit on the same QPU. Each communication qubit is coupled to every data qubit on its QPU. Communication qubits are never coupled to one another locally.

## QPU degrees and communication qubits

| QPU | Neighbours | Degree | Comm qubits |
|---|---|---|---|
| 0 | 1 | 1 | 2 |
| 1 | 0, 2 | 2 | 4 |
| 2 | 1 | 1 | 2 |

Communication qubits are allocated per neighbour: QPU *p*'s *k*-th neighbour (in ascending QPU order) owns comm qubits `c_p_{2k}` and `c_p_{2k+1}`.

## Remote links

| Link | Endpoint A | Endpoint B | Fidelity |
|---|---|---|---|
| 0 | `c_0_0` | `c_1_0` | 1 |
| 1 | `c_0_1` | `c_1_1` | 1 |
| 2 | `c_1_2` | `c_2_0` | 1 |
| 3 | `c_1_3` | `c_2_1` | 1 |

## Notes for compiler runs

* Data qubits are `q_<qpu>_<index>`, communication qubits are `c_<qpu>_<index>`. Only communication qubits carry `remoteConnections`.
* 0 spare data qubits beyond the 30 circuit qubits, because the per-QPU count is rounded up so all QPUs are identical.
* All qubits use a 100 us coherence time and all remote links a fidelity of 1; edit the JSON to sweep those.
* Pair this file with its nearest neighbour counterpart to isolate the effect of intra-QPU connectivity while the inter-QPU arrangement is held fixed.
