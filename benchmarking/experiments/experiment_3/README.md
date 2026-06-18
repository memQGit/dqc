# Experiment 3 — Fixed 5-QPU networks, varied inter-QPU topology

**Total computation qubits:** 100 (constant across every file)
**Network size:** fixed **5 QPUs × 20 computation qubits each**
**Per-QPU grid:** **5 × 4** (5 columns × 4 rows), fully filled, left→right / top→bottom
**Communication qubits:** 8 per QPU — 2 centered on each of the 4 sides
(comm qubits are separate from the 100 computation qubits)

Each topology comes in **2 intra-QPU connectivity variants** (identical rules to
Experiment 1):

| variant | meaning |
|---|---|
| `all_to_all` | complete graph over all computation **and** communication qubits in the QPU |
| `nearest_neighbor` | orthogonal grid neighbors only (no diagonals); each comm qubit links to its nearest 1–2 computation qubits on its side |

## The 4 inter-QPU topologies

How the 5 QPUs connect to one another. Each inter-QPU edge uses one **side/port**
per QPU (a side = its 2 comm qubits), so **every adjacent QPU pair is joined by
exactly 2 comm–comm remote links** (`type: "remote"`, `fidelity: 1`). A QPU has at
most 4 neighbors (one per side).

| folder | shape | adjacent pairs | remote links | description |
|---|---|---|---|---|
| `chain/` | line `0–1–2–3–4` | 4 | 8 | QPUs in a row; the two end QPUs have a single neighbor |
| `ring/` | closed loop | 5 | 10 | the chain with the two ends joined together |
| `hub/` | star | 4 | 8 | **QPU 0 is the hub**; QPUs 1–4 each attach only to the hub |
| `all_to_all/` | complete (K5) | 10 | 20 | every QPU connects to every other QPU |

### Port assignment per topology
- **chain / ring:** each QPU uses its **right** side (comm 6,7) toward the next QPU
  and its **left** side (comm 4,5) toward the previous one; `ring` adds one extra
  edge closing QPU 4 → QPU 0.
- **hub:** QPU 0 uses all four sides (top→QPU1, bottom→QPU2, left→QPU3, right→QPU4);
  each leaf uses the single side facing the hub.
- **all_to_all:** each QPU has exactly 4 neighbors, so all four sides are used (one
  per neighbor, assigned deterministically).

## Communication-qubit side/port indices (every QPU)
```
top    = comm 0, 1
bottom = comm 2, 3
left   = comm 4, 5
right  = comm 6, 7
```

## Folder layout
```
experiment_3/
  chain/        all_to_all.json   nearest_neighbor.json
  ring/         all_to_all.json   nearest_neighbor.json
  hub/          all_to_all.json   nearest_neighbor.json
  all_to_all/   all_to_all.json   nearest_neighbor.json   (folder = inter-QPU shape)
  images/       <topology>/<variant>.png                  (one PNG per file)
  README.md
```
> Note on naming: a folder name is the **inter-QPU** topology; the file name is the
> **intra-QPU** variant. So `all_to_all/all_to_all.json` = all-to-all *between* QPUs
> **and** all-to-all *inside* each QPU.

## JSON schema
Identical to the rest of the repo: top-level `processors`, `qubits`, `connections`.
Qubit IDs `q_<proc>_<idx>` / `c_<proc>_<idx>`; `coherenceTime` 100 `us`; local edges
`{qubit1, qubit2, type:"local"}`, remote edges add `fidelity:1`. Per-qubit
`localConnections`/`remoteConnections` mirror the `connections` array.

## Reproduce
```
python3 generate_experiment_3.py     # writes the 8 JSON files (asserts validity)
python3 visualize_experiment_3.py     # writes the 8 PNGs under images/
```
