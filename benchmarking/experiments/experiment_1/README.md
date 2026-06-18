# Experiment 1 — Scaling QPU count, grid-arranged network

**Total computation qubits:** 100 (constant across every file)
**Network size:** varies — **n = 2 … 10 QPUs**
**Communication qubits:** 8 per QPU — 2 centered on each of the 4 sides
(comm qubits are separate from the 100 computation qubits)

18 files = **9 QPU counts × 2 intra-QPU connectivity variants**.

## Per-QPU grid sizing
For `n` QPUs:
- `per = ceil(100 / n)` target computation qubits per QPU
- `side = ceil(sqrt(per))` → each QPU is a **`side × side` square grid**
- Sequential fill so the total is exactly 100: each QPU gets `per`, the **last QPU
  takes the remainder**. Trailing grid cells stay empty (no qubit object created).

| n | grid | fill per QPU |
|---|---|---|
| 2 | 8×8 | 50, 50 |
| 3 | 6×6 | 34, 34, 32 |
| 4 | 5×5 | 25, 25, 25, 25 |
| 5 | 5×5 | 20 ×5 |
| 6 | 5×5 | 17 ×5, 15 |
| 7 | 4×4 | 15 ×6, 10 |
| 8 | 4×4 | 13 ×7, 9 |
| 9 | 4×4 | 12 ×8, 4 |
| 10 | 4×4 | 10 ×10 |

## Intra-QPU connectivity variants

| variant | meaning |
|---|---|
| `all_to_all` | complete graph over all filled computation **and** communication qubits in the QPU |
| `nearest_neighbor` | orthogonal grid neighbors only (no diagonals), among filled cells; each comm qubit links to its nearest 1–2 filled computation qubits on its side |

## Inter-QPU arrangement (identical for both variants)
- QPUs are placed on a **3-column grid**, filled left→right / top→bottom
  (QPU `p` → column `p % 3`, row `p // 3`).
- Adjacency is **nearest-neighbor only**: a QPU links to the QPU immediately
  left / right / up / down — **no diagonals**, at most 4 neighbors.
- Each adjacent QPU pair is joined by **2 comm–comm remote links** on the facing
  sides (right↔left, bottom↔top). Remote links are `type:"remote"`, `fidelity:1`.
- Edge/corner QPUs have fewer neighbors, so some comm qubits stay unused.

## Communication-qubit side/port indices (every QPU)
```
top    = comm 0, 1
bottom = comm 2, 3
left   = comm 4, 5
right  = comm 6, 7
```

## Folder layout
```
experiment_1/
  n02_2qpu/   all_to_all.json   nearest_neighbor.json
  n03_3qpu/   ...
  ...
  n10_10qpu/  all_to_all.json   nearest_neighbor.json
  README.md
```

## JSON schema
Top-level `processors`, `qubits`, `connections`. Qubit IDs `q_<proc>_<idx>` /
`c_<proc>_<idx>`; `coherenceTime` 100 `us`; local edges `{qubit1, qubit2,
type:"local"}`, remote edges add `fidelity:1`. Per-qubit `localConnections` /
`remoteConnections` mirror the `connections` array.

## Reproduce
```
python3 generate_topologies.py     # writes the 18 JSON files (asserts validity)
```
(The generator currently writes to a top-level `topologies/` folder; these files
were moved here into `experiment_1/`.)
