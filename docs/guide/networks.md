# Network Topology Format

A network topology is a JSON file describing the QPUs in a network, the
physical qubits each one owns, and the links between them. It is the second
required input to every compilation — `Compiler`, `Partitioner`, and
`NetworkGraph` all accept a path to one.

Most users should never hand-author this file. The
[Network Builder](network-builder.md) draws a topology in the browser and
exports it in exactly this format, and
[Bundled Networks & Circuits](bundled-assets.md) ships ready-made topologies.
This page is the reference for what the compiler actually reads — useful when
generating topologies programmatically, or when a loaded network does not have
the edges you expected.

For a worked walkthrough with runnable code, see the
[Defining Networks](../demos/networks.ipynb) demo.

## Structure

Two top-level sections matter:

```json
{
  "processors": {
    "0": {
      "id": 0,
      "qubits": {
        "computation": ["q_0_0", "q_0_1"],
        "communication": ["c_0_0", "c_0_1"]
      }
    }
  },
  "qubits": {
    "q_0_0": {
      "id": "q_0_0",
      "type": "computation",
      "processorId": 0,
      "localConnections": ["q_0_1", "c_0_0"],
      "remoteConnections": []
    },
    "c_0_0": {
      "id": "c_0_0",
      "type": "communication",
      "processorId": 0,
      "localConnections": ["q_0_0"],
      "remoteConnections": ["c_1_0"]
    }
  }
}
```

### `processors`

One entry per QPU, keyed by the processor ID as a **numeric string**
(`"0"`, `"1"`, …). Non-numeric keys are rejected. Each entry lists the qubit
IDs the QPU owns, split into `computation` (data) and `communication`
(networking) qubits.

`num_qpus` is the size of this section, so every QPU must appear here even if
its qubits are fully described under `qubits`.

### `qubits`

One entry per physical qubit, keyed by qubit ID. Two fields are **required**:

| Field | Meaning |
|---|---|
| `type` | Either `"computation"` or `"communication"`. Any other value raises. |
| `processorId` | The ID of the owning QPU. |

Optional fields:

| Field | Meaning |
|---|---|
| `localConnections` | Qubit IDs linked to this one *inside* the same QPU. Defaults to empty. |
| `remoteConnections` | Communication-qubit IDs on *other* QPUs linked to this one. Defaults to empty. |
| `localIndex` | Position within the QPU. Inferred from a `q_<qpu>_<idx>` / `c_<qpu>_<idx>` ID, or assigned in file order, when omitted. |
| `label`, `coherenceTime`, `coherenceTimeUnit` | Recorded on the graph node, not consumed by any current partitioner or scheduler. |

## Edges come only from the per-qubit lists

This is the one rule worth internalising, and the usual cause of a topology
that loads but behaves wrongly.

`NetworkGraph` builds every graph edge from each qubit's `localConnections`
and `remoteConnections`:

- **`localConnections`** — intra-QPU edges: data qubit to data qubit, or a data
  qubit to one of its own communication qubits.
- **`remoteConnections`** — inter-QPU entanglement links. These always join a
  communication qubit on one QPU to a communication qubit on another.

Some topology files also carry a top-level `connections` array, which is
convenient for other tools. **`NetworkGraph` ignores it entirely.** A link that
appears there but not in the two qubits' own connection lists does not exist in
the loaded graph. Keep the per-qubit lists authoritative; write links in both
directions.

The `fidelity` values inside `connections` are likewise recorded but unread,
reserved for future fidelity-aware algorithms.

## Provisioning links for routing

How many `remoteConnections` a link carries decides what the link can do.

| Operation | E-bit pairs | Remote pairs the link needs |
|---|---|---|
| Remote two-qubit gate (cat-entanglement) | 1 | 1 |
| Remote swap / state teleportation (`rswap`) | 2 | 2 |

A remote swap is two state teleportations and needs **two remote pairs alive at
once**, so a link provisioned with a single pair can carry remote gates but can
never be swapped across — and therefore can never be *routed through*.

Routing a gate between two QPUs with no direct link works by teleporting the
moving operand along a chain of intermediate QPUs, one remote swap per hop.
Every link on that chain needs 2 remote pairs, which means each QPU needs 2
communication qubits **per neighbour**. A middle QPU in a chain terminates two
links and so needs twice the communication qubits of an endpoint — that makes
the network heterogeneous, which is normal and fine.

Under-provisioning is not a silent failure: `get_qpu_route` and
`remote_swap_ebit_cost` raise `ValueError` when no route with enough pairs
exists.

## Cost model

Topology turns into cost through two accessors on `NetworkGraph`:

- **`remote_gate_ebit_cost(a, b)`** — 1 e-bit for a gate across a direct link.
  Across `k` intermediate QPUs it is `1 + 2k`: one teleportation hop per
  intermediary at 2 e-bits each, plus the gate's own pair.
- **`remote_swap_ebit_cost(a, b)`** — **2 e-bits per hop**. A swap onto a
  directly linked QPU is one hop and costs 2; a swap onto a QPU one further
  along the chain is two hops and costs 4.

```python
from memq_dqc.network import NetworkGraph

network = NetworkGraph("my_network.json")

network.get_qpu_route(0, 2)  # [0, 1, 2] -- routed through QPU 1
network.remote_gate_ebit_cost(0, 2)  # 3 = 1 + 2*1
network.remote_swap_ebit_cost(0, 2)  # 4 = 2 hops * 2
network.supports_remote_swap(0, 2)  # False -- no *direct* link
```

Because routing is several times the price of a direct link, a partitioner that
keeps interacting qubits on directly-linked QPUs spends far less entanglement
than one that does not. That single fact drives most partitioning results; the
[Comparing Partitioners](../demos/comparing_partitioners.ipynb) demo measures
it.

## The canonical configuration format

Separate from the topology format above, DQC also ships a **canonical** network
configuration — a broader, translation-oriented representation that captures
noise models, protocols, observables, and simulation settings, with every
cross-reference made explicit by string ID. It is aimed at exchanging network
definitions with other tools, not at driving compilation. Build one with
`CanonicalNetworkConfigBuilder` and check it with
`validate_canonical_network_config`; see section 6 of the
[Defining Networks](../demos/networks.ipynb) demo.
