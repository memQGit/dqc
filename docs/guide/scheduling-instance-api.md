# memq_dqc scheduling-instance API (for external schedulers)

## Purpose
`memq_dqc` compiles a quantum circuit + network topology into a **distributed**
circuit. This API exposes the result as a single, versioned, JSON-persistable
**scheduling instance** containing everything an external discrete-event
simulator or RL scheduler needs: the distributed operation DAG, a deterministic
zero-EPR-wait nominal schedule, the physical resources/links, and the
entanglement (EPR) demands. It contains **no** OpenQASM AST objects and no live
compiler state — it round-trips through JSON losslessly.

The API is in-process Python. There are no HTTP endpoints. It imports no RL
framework (no Gymnasium/PyTorch).

Install `memq_dqc` (`pip install memq-dqc` / `uv add memq_dqc`); import as
`memq_dqc`.

## Import surface
Everything below is importable from the top-level package:

```python
from memq_dqc import (
    compile_scheduling_instance,
    compute_scheduling_source_fingerprint,
    compile_scheduling_batch,
    SchedulingCompileRequest,
    SchedulingCompileResult,
    SchedulingCompileOptions,
    SchedulingInstance,
    scheduling_instance_to_json,
    scheduling_instance_from_json,
    validate_scheduling_instance,
    Compiler,
)

# Record types + constant live under the scheduler subpackage:
from memq_dqc.scheduler import (
    SchedulingOperation,
    SchedulingDependency,
    SchedulingResource,
    EPRDemand,
    EPRLinkAssignment,
    SchedulerHardwareProfile,
    SCHEDULING_INSTANCE_SCHEMA_VERSION,
)
```

## Input types (used throughout)
- **`circuit`** (`ProgramInput`): a parsed `openqasm3.ast.Program`, **or** a path
  to a `.qasm`/`.qasm3` file (`str`/`os.PathLike`), **or** inline OpenQASM 3
  source text.
- **`topology`** (`NetworkInput`): a `memq_dqc.network.NetworkGraph`, **or** a
  path to its `.json` description.

---

## 1. Primary endpoint — compile one instance

```python
compile_scheduling_instance(
    circuit, topology, *,
    options: SchedulingCompileOptions | None = None,
    verbosity: Literal["quiet", "info", "debug"] = "quiet",
) -> SchedulingInstance
```

Partitions the circuit, extracts the distributed circuit, builds the nominal
schedule, and returns a **validated** `SchedulingInstance`. This is the call to
use 95% of the time.

```python
inst = compile_scheduling_instance("circuit.qasm", "network.json")
```

## 2. `SchedulingCompileOptions`
Immutable options object. Defaults match the current supported "MVP" corpus.

| field | type | default | meaning |
|---|---|---|---|
| `partitioner` | `str` | `"interaction"` | algorithm name: `interaction`, `hypergraph`, `benchmark_static`, `benchmark_random` |
| `partitioner_kwargs` | `Mapping \| None` | `None` | extra kwargs forwarded to the algorithm |
| `partition_seed` | `int \| None` | `None` | seed for algorithms with randomness (interaction uses it; deterministic ones record but ignore) |
| `ebit_assignment` | `bool` | `True` | `True` = compiler fixes concrete EPR link assignments; `False` = defer, exposing candidate assignments instead |
| `group_gates` | `bool` | `False` | share one cat-entanglement region across compatible remote gates |
| `max_group_size` | `int \| None` | `None` | cap two-qubit gates per group |
| `hardware_profile` | `SchedulerHardwareProfile \| None` | `None` | sets deterministic op durations; `None` = default profile |

Recommended for a first RL corpus: leave everything default (i.e.
`ebit_assignment=True`, `group_gates=False`).

Hardware profile options:

```python
SchedulerHardwareProfile.ba_trapped_ion()      # default
SchedulerHardwareProfile.sr_trapped_ion()
SchedulerHardwareProfile.neutral_atom()
```

### Custom hardware parameters

A profile also selects the *values* the named modality and entanglement
profile resolve to from `settings.toml`. Any of the five primitive hardware
parameters can be overridden per compile — pass a value to replace the
profile's, or leave it `None` to keep it:

| field | default source | default (`trapped_ion.ba` / `ion.time_bin`) |
|---|---|---|
| `one_qubit_gate_time` | `modality.<sel>.1q_gate_time` | 10.0 µs |
| `two_qubit_gate_time` | `modality.<sel>.2q_gate_time` | 500.0 µs |
| `measurement_time` | built-in constant | 3.0 µs |
| `entanglement_rate` | `entanglement_gen.<sel>.entanglement_rate` | 3.5e-6 pairs/µs |
| `epr_lifetime` | `entanglement_gen.<sel>.epr_lifetime` | 50.0 µs |

```python
from memq_dqc import (
    SchedulerHardwareProfile,
    SchedulingCompileOptions,
    compile_scheduling_instance,
)

inst = compile_scheduling_instance(
    "circuit.qasm",
    "network.json",
    options=SchedulingCompileOptions(
        hardware_profile=SchedulerHardwareProfile.sr_trapped_ion(
            two_qubit_gate_time=120.0,
            epr_lifetime=80.0,
        )
    ),
)
```

Every value must be a finite positive number; anything else raises
`ValueError` at construction. Derived timings — `catent_time`,
`catdisent_time`, `state_teleport_time`, `entanglement_time`, and the DES
per-cycle success probability — always recompute from the effective values, so
they cannot contradict the parameters they are built from and are not
separately overridable. `des_entanglement_time_step` stays global to
`settings.toml`.

Overrides are folded into `source_fingerprint` (and therefore `instance_id`),
so two compiles differing only in a hardware parameter never collide in a
fingerprint cache. A profile with no overrides fingerprints identically to
passing no profile at all.

The same object works for the execution schedulers, which already accept a
profile: `Scheduler(compiler, profile=my_profile)`. Note that `profile=`
cannot be combined with the scalar `modality=` / `entanglement_profile=`
keywords — to override parameters, pass a profile.

## 3. `SchedulingInstance` (the artifact)
Immutable dataclass. Fields:

- `schema_version: int` — currently `1` (== `SCHEDULING_INSTANCE_SCHEMA_VERSION`)
- `instance_id: str` — deterministic, derived from the fingerprint
  (`"inst-<16 hex>"`)
- `compiler_version: str` — memq_dqc version that produced it
- `source_fingerprint: str` — SHA-256 of normalized inputs+options+profile+schema
  version
- `time_unit: str` — `"microseconds"`
- `operations: tuple[SchedulingOperation, ...]` — ordered by `op_id`
- `dependencies: tuple[SchedulingDependency, ...]` — ordered by `(source, target)`
- `resources: tuple[SchedulingResource, ...]` — ordered by `resource_id`
- `epr_demands: tuple[EPRDemand, ...]` — ordered by `consumer_op_id`
- `nominal_makespan: float` — max nominal end time
- `metadata: Mapping[str, JSONValue]` — reproducibility record (partitioner,
  seed, profile, flags), including `metadata["hardware"]`: the **effective**
  hardware parameters (`one_qubit_gate_time`, `two_qubit_gate_time`,
  `measurement_time`, `entanglement_rate`, `epr_lifetime`,
  `des_entanglement_time_step`) after any overrides, so a consumer can recover
  the timings without re-resolving the profile against `settings.toml`

### `SchedulingOperation`
One node of the distributed DAG.
`op_id:int`, `statement_id:int`, `name:str`, `op_type:str`, `is_remote:bool`,
`data_qubits:tuple[str,...]`, `comm_qubits:tuple[str,...]`, `duration:float`,
`group_id:int|None`, `nominal_start:float`, `nominal_end:float`.

`op_type` ∈ `local_gate`, `local_swap`, `measurement`, `remote_gate`,
`remote_swap`, `epr_generation` (a `catent`), `disentangle` (a `catdisent`).

### `SchedulingDependency`
A DAG precedence edge. `source_op_id:int`, `target_op_id:int`,
`resources:tuple[str,...]` (qubit ids that created the dependency),
`classification: "cross_qpu" | "local" | None`.

### `SchedulingResource`
A physical resource. `resource_id:str`,
`resource_type: "computation"|"communication"|"link"`, `qpu_id:int|None`,
`local_index:int|None`, `endpoints:tuple[str,str]|None` (the two comm-qubit ids a
link joins), `parameters:Mapping` (reserved for you to annotate hardware —
coherence, fidelity — it's empty by default).

**Resource-id format (stable, this is your qubit vocabulary):**
- computation qubit → `q<qpu>[<slot>]`, e.g. `q0[3]`
- communication qubit → `c<qpu>[<slot>]`, e.g. `c1[0]`
- link → `link:<commA><->commB>` with endpoints sorted, e.g.
  `link:c0[0]<->c1[0]`

### `EPRDemand`
An operation's request for freshly generated entanglement. **This is your action
target.**
`demand_id:str`, `consumer_op_id:int`, `num_pairs:int`,
`assigned:EPRLinkAssignment|None`, `candidates:tuple[EPRLinkAssignment,...]`,
`nominal_start_time:float`, `predecessor_op_ids:tuple[int,...]`,
`remaining_critical_path:float`.

- When `ebit_assignment=True` (default): `assigned` is set, `candidates` is empty.
- When `ebit_assignment=False`: `assigned` is `None`, `candidates` lists the
  viable link assignments to choose among.
- `EPRLinkAssignment` = `link_ids:tuple[str,...]` (one per pair) +
  `comm_qubit_ids:tuple[str,...]` (the comm qubits it occupies).

**Which ops generate demands:** `catent` (`epr_generation`), `rswap`
(`remote_swap`), and any ungrouped `remote_gate`. Grouped remote gates reuse
their group's `catent` pair and do **not** produce their own demand.

**Important modeling note:** an EPR demand is a *resource request*, not a
generation event. The instance deliberately carries **no**
entanglement-generation time or EPR lifetime — your external DES/RL supplies
those models and decides *when* to start generation. The nominal schedule
assumes zero EPR wait, so it is a lower-bound prediction / observation source,
not an executable schedule. You must still enforce the DAG dynamically.

## 4. Persistence

```python
scheduling_instance_to_json(instance, path=None, *, indent=2) -> str
scheduling_instance_from_json(source) -> SchedulingInstance
# source: JSON str | path | mapping
```

- `indent=None` gives compact single-line JSON (use for large corpora).
- Non-finite numbers (NaN/Infinity) are rejected on both write and read.
- `from_json` validates the reconstructed instance and rejects unknown
  `type`/`schema_version`.
- Round-trips exactly: `from_json(to_json(x)) == x`.

Top-level JSON shape:

```json
{
  "type": "scheduling_instance",
  "schema_version": 1,
  "instance_id": "inst-…",
  "compiler_version": "…",
  "source_fingerprint": "…",
  "time_unit": "microseconds",
  "nominal_makespan": 5144.0,
  "operations": [
    {
      "op_id": 0, "statement_id": 0, "name": "…", "op_type": "…",
      "is_remote": false, "data_qubits": [], "comm_qubits": [],
      "duration": 0.0, "group_id": null,
      "nominal_start": 0.0, "nominal_end": 0.0
    }
  ],
  "dependencies": [
    {"source_op_id": 0, "target_op_id": 1, "resources": [], "classification": "local"}
  ],
  "resources": [
    {"resource_id": "q0[0]", "resource_type": "computation",
     "qpu_id": 0, "local_index": 0, "endpoints": null, "parameters": {}}
  ],
  "epr_demands": [
    {"demand_id": "epr-8", "consumer_op_id": 8, "num_pairs": 1,
     "assigned": {"link_ids": ["link:c0[0]<->c1[0]"], "comm_qubit_ids": ["c0[0]", "c1[0]"]},
     "candidates": [], "nominal_start_time": 1020.0,
     "predecessor_op_ids": [], "remaining_critical_path": 3121.0}
  ],
  "metadata": {}
}
```

## 5. Validation

```python
validate_scheduling_instance(instance) -> None
# raises ValueError naming the offending id + invariant
```

Checks: unique ids; dependency endpoints exist; DAG acyclic; every demand
references an EPR-consuming op; assigned links/comm qubits exist; pair counts
match; durations/times finite & nonnegative; nominal ordering satisfies
dependencies; per-qubit intervals don't overlap; `nominal_makespan` equals the
max end. (`compile_*` and `from_json` already call this.)

## 6. Batch compilation

```python
compile_scheduling_batch(
    requests: Sequence[SchedulingCompileRequest], *,
    workers: int = 1,
    cache_dir: str | PathLike | None = None,
    fail_fast: bool = False,
) -> tuple[SchedulingCompileResult, ...]
```

- `SchedulingCompileRequest(request_id, circuit, topology, options=None)`
- `SchedulingCompileResult(request_id, instance|None, cache_hit:bool,
  elapsed_seconds:float, error:str|None)`
- Results preserve input order.
- `cache_dir` caches by `source_fingerprint` with atomic writes; a later
  identical request is a cache hit.
- `workers>1` uses process parallelism — **use file paths (not in-memory
  `ast.Program`) so requests pickle across processes.**
- `fail_fast=False` (default) returns per-request errors in `.error`;
  `fail_fast=True` raises on the first failure.
- Artifacts are byte-identical regardless of `workers`.

```python
results = compile_scheduling_batch(
    [
        SchedulingCompileRequest("q1", "a.qasm", "net.json"),
        SchedulingCompileRequest("q2", "b.qasm", "net.json"),
    ],
    workers=4,
    cache_dir=".cache",
)
```

## 7. Convenience: from an existing `Compiler`
If you already drove the normal pipeline:

```python
c = Compiler("circuit.qasm", "network.json")
c.compile()
inst = c.to_scheduling_instance(hardware_profile=None)
# reuses the compiled result, no re-partition
```

## 8. Determinism & caching contract
- Same inputs + same `options` (incl. `partition_seed`) ⇒ identical
  `source_fingerprint`, identical `instance_id`, and **byte-identical** compact
  JSON.
- Precompute the cache key without compiling:
  `compute_scheduling_source_fingerprint(circuit, topology, options=None) -> str`
  (this is exactly the `source_fingerprint` the compile will produce).
- The default `interaction` partitioner is deterministic even without a seed
  (fixed internal default), so repeated compiles reproduce.

## 9. Minimal RL-loop usage sketch

```python
from memq_dqc import compile_scheduling_instance

inst = compile_scheduling_instance("qft.qasm", "net.json")

# Observation building blocks:
ops = inst.operations       # DAG nodes + nominal timing
deps = inst.dependencies    # precedence edges
res = inst.resources        # qubits + links (annotate .parameters yourself)
dem = inst.epr_demands      # per-demand: consumer op, #pairs, assigned/candidate
                            #   links, nominal start, predecessors, remaining
                            #   critical path
mk = inst.nominal_makespan  # zero-EPR-wait lower bound (baseline/normalizer)

# Your DES enforces the DAG, applies your own EPR gen-rate + lifetime model,
# and your policy decides WHEN to start each demand's entanglement generation.
```
