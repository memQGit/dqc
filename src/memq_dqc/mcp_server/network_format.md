# memq-dqc network topology format

A network is a JSON object describing the QPUs, the physical qubits each one
owns, and the links between them. This is the format every memq-dqc tool
accepts as `network`, inline or as a `.json` file.

Prefer the `build_network` tool, which generates valid networks with
identically sized QPUs. Write the JSON by hand only for designs it cannot
express, and check the result with `describe_network`.

## Minimal complete example

Two QPUs, each with 2 computation (data) qubits and 2 communication qubits,
joined by 2 remote links:

```json
{
  "processors": {
    "0": {"id": 0, "qubits": {"computation": ["q_0_0", "q_0_1"], "communication": ["c_0_0", "c_0_1"]}},
    "1": {"id": 1, "qubits": {"computation": ["q_1_0", "q_1_1"], "communication": ["c_1_0", "c_1_1"]}}
  },
  "qubits": {
    "q_0_0": {"id": "q_0_0", "type": "computation", "processorId": 0, "localConnections": ["q_0_1", "c_0_0"], "remoteConnections": []},
    "q_0_1": {"id": "q_0_1", "type": "computation", "processorId": 0, "localConnections": ["q_0_0", "c_0_1"], "remoteConnections": []},
    "c_0_0": {"id": "c_0_0", "type": "communication", "processorId": 0, "localConnections": ["q_0_0"], "remoteConnections": ["c_1_0"]},
    "c_0_1": {"id": "c_0_1", "type": "communication", "processorId": 0, "localConnections": ["q_0_1"], "remoteConnections": ["c_1_1"]},
    "q_1_0": {"id": "q_1_0", "type": "computation", "processorId": 1, "localConnections": ["q_1_1", "c_1_0"], "remoteConnections": []},
    "q_1_1": {"id": "q_1_1", "type": "computation", "processorId": 1, "localConnections": ["q_1_0", "c_1_1"], "remoteConnections": []},
    "c_1_0": {"id": "c_1_0", "type": "communication", "processorId": 1, "localConnections": ["q_1_0"], "remoteConnections": ["c_0_0"]},
    "c_1_1": {"id": "c_1_1", "type": "communication", "processorId": 1, "localConnections": ["q_1_1"], "remoteConnections": ["c_0_1"]}
  }
}
```

## `processors`

One entry per QPU, keyed by its numeric ID as a string (`"0"`, `"1"`, ...).
Each entry has the same `id` as an integer and lists the IDs of the qubits it
owns under `computation` and `communication`. Every QPU must appear here: the
QPU count is the number of entries.

## `qubits`

One entry per physical qubit, keyed by qubit ID.

| Field | Required | Meaning |
|---|---|---|
| `id` | yes | The same ID as the key. |
| `type` | yes | `"computation"` or `"communication"`. |
| `processorId` | yes | Integer ID of the owning QPU. |
| `localConnections` | no | Qubit IDs on the same QPU linked to this one. |
| `remoteConnections` | no | Communication-qubit IDs on other QPUs linked to this one. |
| `coherenceTime`, `coherenceTimeUnit` | no | Recorded but not used by any current algorithm. |

Use IDs of the form `q_<qpu>_<index>` for computation qubits and
`c_<qpu>_<index>` for communication qubits, with indices counting from 0
within each QPU.

## Rules

1. **Edges come only from the per-qubit lists.** A top-level `connections`
   array, if present, is ignored by the compiler.
2. **Write every link in both directions.** If `a` lists `b`, `b` lists `a`.
3. **Remote links join communication qubits on different QPUs.** Computation
   qubits always have `"remoteConnections": []`.
4. **Each communication qubit belongs to exactly one remote link** and has a
   local connection to at least one computation qubit on its own QPU.
   Communication qubits are never locally connected to each other.
5. **Keep `processors` and `qubits` consistent**: every qubit listed under a
   QPU has that QPU's `processorId`, and every qubit appears under exactly one
   QPU.

## Sizing and provisioning

- **Capacity:** the total number of computation qubits must be at least the
  number of qubits in the circuits the network will run. The usual choice is
  `ceil(circuit_qubits / num_qpus)` computation qubits on every QPU.
- **Links per neighbour:** give each pair of directly linked QPUs **2**
  remote links. One link supports remote gates between those two QPUs, but a
  QPU pair needs 2 to teleport qubits, which is what routing a gate *through*
  an intermediate QPU requires. With 1 link per neighbour, QPUs that are not
  directly linked cannot interact.
- **Communication qubits:** each remote link uses one communication qubit on
  each end, so a QPU has `links_per_neighbour x number_of_neighbours`
  communication qubits. Interior chain QPUs and hubs need more than
  endpoints; that is expected.

## Common shapes

Between QPUs:

| Arrangement | Links |
|---|---|
| pair | QPU 0 to QPU 1 |
| chain | QPU i to QPU i+1 |
| ring | chain plus last QPU to QPU 0 |
| hub (star) | QPU 0 to every other QPU |
| all-to-all | every QPU pair |

Inside each QPU:

| Connectivity | Computation qubits | Communication qubits |
|---|---|---|
| nearest neighbour (`nn`) | a 2D grid with 4-way adjacency, `ceil(sqrt(k))` columns wide | each connected to one computation qubit on the grid boundary |
| all-to-all (`a2a`) | every pair connected | each connected to every computation qubit |
| line | qubit i to qubit i+1 | each connected to one end qubit |

The bundled networks (see `list_bundled_assets`) follow these conventions
and are good references.
