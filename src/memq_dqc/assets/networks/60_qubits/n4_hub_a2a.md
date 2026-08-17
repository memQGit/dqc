# n4_hub_a2a

60-qubit circuit partitioned across 4 QPUs in a **hub** arrangement, **all-to-all** intra-QPU connectivity.

## Inter-QPU arrangement

A star: one central QPU, every other QPU attached only to it. The hub is a hard bottleneck -- every remote gate between two leaves must be relayed through it.

```
QPU1   QPU2   QPU3
  |      |      |
  +------+------+
         |
        QPU0 (hub)
```

Every drawn edge is **2 independent remote links**, and each link owns its own dedicated pair of communication qubits (one on each side). Two QPUs can therefore hold two entangled pairs at once.

## At a glance

| | |
|---|---|
| Circuit qubits | 60 |
| QPUs | 4 |
| Data qubits per QPU | 15 (= ceil(60 / 4)) |
| Total data qubits | 60 |
| Spare data qubits | 0 |
| Communication qubits per QPU | QPU0: 6, QPU1: 2, QPU2: 2, QPU3: 2 |
| Total communication qubits | 12 |
| Total physical qubits | 72 |
| QPU-to-QPU edges | 3 |
| Remote links | 6 |
| Local couplings | 600 |

## Intra-QPU connectivity

Data qubits form a complete graph -- every data qubit is directly coupled to every other data qubit on the same QPU. Each communication qubit is coupled to every data qubit on its QPU. Communication qubits are never coupled to one another locally.

## QPU degrees and communication qubits

| QPU | Neighbours | Degree | Comm qubits |
|---|---|---|---|
| 0 | 1, 2, 3 | 3 | 6 |
| 1 | 0 | 1 | 2 |
| 2 | 0 | 1 | 2 |
| 3 | 0 | 1 | 2 |

Communication qubits are allocated per neighbour: QPU *p*'s *k*-th neighbour (in ascending QPU order) owns comm qubits `c_p_{2k}` and `c_p_{2k+1}`.

## Remote links

| Link | Endpoint A | Endpoint B | Fidelity |
|---|---|---|---|
| 0 | `c_0_0` | `c_1_0` | 1 |
| 1 | `c_0_1` | `c_1_1` | 1 |
| 2 | `c_0_2` | `c_2_0` | 1 |
| 3 | `c_0_3` | `c_2_1` | 1 |
| 4 | `c_0_4` | `c_3_0` | 1 |
| 5 | `c_0_5` | `c_3_1` | 1 |

## Notes for compiler runs

* Data qubits are `q_<qpu>_<index>`, communication qubits are `c_<qpu>_<index>`. Only communication qubits carry `remoteConnections`.
* 0 spare data qubits beyond the 60 circuit qubits, because the per-QPU count is rounded up so all QPUs are identical.
* All qubits use a 100 us coherence time and all remote links a fidelity of 1; edit the JSON to sweep those.
* Pair this file with its nearest neighbour counterpart to isolate the effect of intra-QPU connectivity while the inter-QPU arrangement is held fixed.
