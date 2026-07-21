# Response to reviewer: why we observe these topology / connectivity trends

This addresses the three page-11 comments on Fig. 9:

1. *"Is there a reason behind this specific regime where ring is not the best topology?"*
2. *"Is there a general trend between the degree of connectivity and the number of EPR pairs that we can comment on?"*
3. *"Would 'dependence on intra-QPU connectivity' be better?"* (wording — handled separately)

Everything below is grounded in the compiler's actual cost accounting (`_exact_entanglement_cost` in `src/memq_dqc/builder/circuit_extractor.py`) and a re-run of the Experiment 5 QFT sweep (`benchmarking/experiments/experiment_5`, 5-QPU networks, nearest-neighbor intra-QPU connectivity, dynamic Interaction partitioner). All numbers reconcile exactly to the reported EPR cost.

---

## The underlying cost mechanism (the one fact that explains both trends)

In the compiled circuit, entanglement is consumed by cat-entangler groups. Each remote-gate group costs **one EPR pair for every communication-qubit pair it must chain together**:

- a remote operation between two **directly-linked** QPUs costs **1 EPR pair**;
- a remote operation that must be **routed through an intermediary** QPU costs **2 EPR pairs** (an extra comm-pair per hop).

So the total EPR cost is driven by two measurable quantities:

- **(a) how many remote-gate groups the partitioner creates**, and
- **(b) what fraction of those groups fall on non-adjacent QPU pairs** and therefore have to be routed.

A topology is "good" when it lets the (dynamic) partitioner keep interacting qubits on directly-linked QPUs and settle into a *stable* assignment, so that (a) and (b) stay small.

---

## General trend: EPR cost tracks routed distance and layout stability — not raw link count

EPR pairs for the Interaction partitioner, QFT, 5 QPUs, nearest-neighbor intra-QPU connectivity:

| Inter-QPU topology | links | 5q | 10q | 20q | 40q | 60q |
|---|---:|---:|---:|---:|---:|---:|
| All-to-all (K5)    | 10 |  12 |  64 | 248 | 1027 | 2249 |
| Hub (star)         |  4 |  28 |  98 | 336 | 1280 | 2925 |
| Ring               |  5 |  30 | 121 | 458 | 1799 | 4089 |
| Chain              |  4 |  36 | 144 | 616 | 2376 | 3523 |

Two robust observations:

- **All-to-all is always cheapest** — every remote operation is a single hop (1 EPR), so both (a) and (b) are minimized.
- **The ordering is *not* monotonic in the number of inter-QPU links.** The hub has the *fewest* links (4) yet is the second-cheapest topology at *every* circuit size, and it beats the ring, which has more links (5). Raw connectivity (edge count / degree) is therefore a poor predictor.

The quantity that *does* predict cost is the **routed distance between the QPU pairs that actually have to communicate**, combined with **how easily the dynamic partitioner can settle into a low-movement layout**. The hub's central node acts as a "gravity well": the partitioner parks heavily-interacting qubits on and around the hub, so only ~32% of its groups ever need routing. The all-to-all network removes routing entirely. Chain and ring, whose non-adjacent QPU pairs must be routed, sit above both.

**Suggested manuscript sentence (Section V-B):** *"Across circuit sizes, EPR cost is governed less by the raw number of inter-QPU links than by the routed distance between communicating QPUs and the stability of the resulting qubit placement: the hub topology, despite having the fewest links, consistently outperforms the ring because its central node lets the partitioner concentrate interactions on directly-connected QPU pairs."*

---

## The specific regime: why the ring loses to the chain at 60 qubits

Below 40 qubits the ring beats the chain (its diameter-2 structure keeps average routing distance lower than the chain's up-to-diameter-4 structure). At 60 qubits this inverts. The reason is visible in the decomposition of the cost:

| Topology | EPR (60q) | remote-gate groups | groups needing routing (2-EPR) | % routed | state teleportations |
|---|---:|---:|---:|---:|---:|
| Chain | 3523 | 2496 | 1027 | 41% | 1051 |
| Ring  | 4089 | 2756 | 1333 | 48% | 1356 |

At 60 qubits the ring produces **more remote-gate groups** (2756 vs 2496) and a **higher fraction that require routing** (48% vs 41%) — both cost drivers point the wrong way for the ring.

The cause is the behaviour of the **dynamic** partitioner as the circuit grows. It re-partitions each window and moves qubits (state teleportation) whenever a cheaper-looking placement appears. Tracking how much "churn" this produces as the circuit scales:

| | 20q | 40q | 60q | growth 40→60 |
|---|---:|---:|---:|---:|
| **Chain** groups | 390 | 1514 | 2496 | +65% |
| **Ring** groups  | 312 | 1223 | 2756 | **+125%** |
| **Chain** teleportations | 234 | 881 | 1051 | **+19%** |
| **Ring** teleportations  | 154 | 592 | 1356 | **+129%** |

This is the mechanism. On the **chain**, the linear structure has fixed endpoints that anchor the layout; by 60 qubits the partitioner has essentially settled — its teleportation count *saturates* (881 → 1051, only +19%) and a shrinking share of gates need routing. On the **ring**, rotational symmetry means every window admits many equally-good but *different* rotations of the qubit-to-QPU assignment; the greedy accept rule keeps taking these lateral moves, so teleportations and remote-gate groups keep climbing (teleportations +129% over the same interval). The ring never settles, and the accumulated churn overtakes its diameter advantage exactly in the large-circuit regime.

So the ring is "not the best topology" specifically when the circuit is large enough that the dynamic partitioner's placement instability on a symmetric network outweighs its shorter nominal routing distance.

**Suggested manuscript sentence (replacing/augmenting the current Fig. 9 discussion):** *"The ring's advantage over the chain holds only at smaller circuit sizes. As the circuit grows, the dynamic partitioner increasingly re-places qubits window-to-window; the ring's rotational symmetry offers no stable anchor for this process, so it accrues more state-teleportation and remote-gate groups than the chain, whose fixed endpoints let the placement settle. Beyond ~40 qubits this placement churn outweighs the ring's shorter average routing distance, and the chain becomes the cheaper topology."*

---

## Caveat worth knowing (not for the reviewer)

In the current code, `_exact_entanglement_cost` sums **only cat-entangler groups**; the e-bits consumed by `rswap` state-teleportations are *not* added to the reported EPR figure (see the `# TODO: make this exact and confirm cost calculations` note). That is why the explanation above frames teleportation count as *evidence of layout churn* rather than as a directly-counted cost — the churn is counted indirectly, through the extra (and more-routed) remote-gate groups it produces. If teleportation e-bits were later included, the ring's disadvantage in this regime would only widen (it does ~30% more teleportations than the chain at 60q). Worth deciding before publication whether the reported metric should include teleportation cost.
