# Hardware & Settings

Scheduling is the one stage of the DQC pipeline that needs a physical device
model. Partitioning counts e-bits, which is hardware-independent; turning a
distributed circuit into a *timeline* needs gate durations, an entanglement
generation rate, and a pair lifetime.

Those values come from two places:

1. **`src/memq_dqc/settings.toml`** — the packaged defaults, organised into
   named **modality** and **entanglement generation** profiles.
2. **`SchedulerHardwareProfile`** — the runtime object that selects a pair of
   those profiles and optionally overrides individual parameters, per compile
   or per scheduler run.

Nothing in `settings.toml` needs editing for normal use. Selecting a profile
and passing overrides covers the common cases, and keeps your experiment
reproducible from code rather than from a mutated package file.

## The primitive parameters

Five values drive every duration the scheduler computes. Everything else is
derived from them.

| Parameter | Symbol | Source | Override field |
|---|---|---|---|
| Single-qubit gate time | $t_{1q}$ | modality profile | `one_qubit_gate_time` |
| Two-qubit gate time | $t_{2q}$ | modality profile | `two_qubit_gate_time` |
| Measurement time | $t_{\mathrm{meas}}$ | module constant, **not** `settings.toml` | `measurement_time` |
| Entanglement generation rate | $r$ | entanglement profile | `entanglement_rate` |
| EPR pair lifetime | — | entanglement profile | `epr_lifetime` |

$t_{\mathrm{meas}}$ is the odd one out: it defaults to `3.0` from
`_MEASUREMENT_TIME` in `memq_dqc/scheduler/schedule.py` rather than from a
profile, because no packaged profile varies it. Override it like any other
parameter.

One further parameter, the DES entanglement-attempt cycle $t_c$
(`scheduler.des.entanglement_time_step`, default `1.0`), is **global to
`settings.toml`** and has no per-profile entry and no override field. Changing
it means editing the file.

All times are in microseconds; `global.time_unit = "us"` is the display label
used by the schedule visualizer.

## Modality profiles

A modality supplies the local gate times. Three ship with the library:

| Selector | Device | $t_{1q}$ | $t_{2q}$ |
|---|---|---|---|
| `trapped_ion.ba` | Ba⁺ trapped ion | 10 | 500 |
| `trapped_ion.sr` | Sr⁺ trapped ion | 13 | 200 |
| `neutral_atom` | Yb neutral atom | 1 | 0.8 |

`trapped_ion.ba` is the default. Note the three-order-of-magnitude spread in
$t_{2q}$ — the choice of modality changes makespans far more than any
scheduling strategy does, so keep it fixed when comparing schedulers.

## Entanglement generation profiles

An entanglement profile supplies the rate and the pair lifetime. These are
experimental values from the literature, cited in `settings.toml`.

| Selector | Source | $r$ (pairs/µs) | $t_{\mathrm{epr}} = 1/r$ |
|---|---|---|---|
| `ion.time_bin` | Saha et al. | 3.5 × 10⁻⁶ | ~285,700 µs |
| `ion.polarization` | O'Reilly et al. | 2.5 × 10⁻³ | 400 µs |
| `neutral_atom.polarization` | Young et al. | 3.2 × 10⁻² | 31.25 µs |
| `demo.demo` | illustrative, not physical | 1 × 10⁻¹ | 10 µs |

`ion.time_bin` is the default, and it is by far the slowest — entanglement
generation dominates the makespan under it by five orders of magnitude over a
local gate. That is the physically honest default, but it makes for
uninformative plots, which is why `demo.demo` exists.

!!! warning "`demo.demo` is not in the type annotation"
    `SchedulerEntanglementProfile` is a `Literal` listing only the three
    experimental profiles, so passing `entanglement_profile="demo.demo"` works
    at runtime but is flagged by a type checker. Treat it as demo-only.

### EPR lifetime is currently pinned open

Every profile above sets `epr_lifetime = 1e9` µs — effectively infinite. The
real experimental value is **50 µs** for all four.

The reason is a genuine physical tension, not an oversight. A remote swap needs
two e-bit pairs alive *simultaneously* (two state teleportations). At the
default `ion.time_bin` rate, generating one pair takes ~285,700 µs, so a 50 µs
pair always expired long before a second one arrived — the DES schedulers
discarded and regenerated forever and never terminated. Raising the lifetime
removes the blocker without changing scheduling semantics for the single-pair
remote gates that already worked.

`BaseDESLinkScheduler._validate_multi_pair_feasibility` rejects the hopeless
configurations up front with a clear error rather than hanging, so if you set a
realistic lifetime you get a diagnostic instead of an infinite loop. Be aware
that the partitioner cost model has no notion of EPR lifetime at all, so it
will happily plan swaps no scheduler can run, and FIFO does not model pair
lifetime either — it returns a schedule for exactly the cases DES declares
infeasible.

## Selecting and overriding

`SchedulerHardwareProfile` has three constructors, one per modality, each
taking the entanglement profile and any parameter overrides as keyword
arguments:

```python
from memq_dqc import SchedulerHardwareProfile

# Packaged defaults for Sr+ trapped ion.
profile = SchedulerHardwareProfile.sr_trapped_ion()

# Same device, but a faster two-qubit gate and a realistic pair lifetime.
tuned = SchedulerHardwareProfile.sr_trapped_ion(
    two_qubit_gate_time=120.0,
    epr_lifetime=80.0,
)

# A neutral-atom device on its matching entanglement profile.
atoms = SchedulerHardwareProfile.neutral_atom(
    entanglement_profile="neutral_atom.polarization",
)
```

`ba_trapped_ion()`, `sr_trapped_ion()`, and `neutral_atom()` are equivalent to
constructing `SchedulerHardwareProfile(modality=...)` directly; prefer them, as
they keep the selector string out of your code.

Every override is validated on construction: a non-finite or non-positive value
raises `ValueError` immediately rather than producing a nonsense schedule.
`None` means "keep the profile's value", which is why omitting an argument and
passing `None` behave identically.

Note that pairing a modality with a mismatched entanglement profile is allowed
— nothing stops `neutral_atom` on `ion.time_bin`. That flexibility is
deliberate for exploring hypothetical hardware, but it is on you to keep the
combination meaningful.

### Passing it in

Two entry points accept a profile:

```python
from memq_dqc import Scheduler, SchedulingCompileOptions

# Directly on a scheduler.
schedule = Scheduler(distributed_circuit, profile=tuned).run()

# Or through the scheduling-instance compile path.
options = SchedulingCompileOptions(hardware_profile=tuned)
```

`BaseScheduler` also accepts bare `modality=` / `entanglement_profile=`
selectors for convenience, but they are mutually exclusive with `profile=`:
pass a profile when you need overrides, and leave the scalar selectors at their
defaults. See [Scheduling-Instance API](scheduling-instance-api.md) for the
`compile_scheduling_instance` path.

## Derived durations

Nothing below is configurable; each recomputes from whatever primitives are in
effect, so a derived duration can never contradict the parameters it is built
from.

| Operation | Formula |
|---|---|
| `catent` (remote gate, entangling half) | $t_{2q} + t_{1q} + t_{\mathrm{meas}}$ |
| `catdisent` (remote gate, disentangling half) | $2 t_{1q} + t_{\mathrm{meas}}$ |
| State teleport | $t_{2q} + 3 t_{1q} + 2 t_{\mathrm{meas}}$ |
| `rswap` | $2 \left( t_{2q} + 3 t_{1q} + 2 t_{\mathrm{meas}} \right)$ |
| FIFO entanglement window | $t_{\mathrm{epr}} = 1/r$ |
| DES success probability | $p = 1 - e^{-r t_c}$ |

Worked out for the packaged profiles, with $t_{\mathrm{meas}} = 3$ and
$t_c = 1$:

| | `trapped_ion.ba` | `trapped_ion.sr` | `neutral_atom` |
|---|---|---|---|
| `catent` | 513 | 216 | 4.8 |
| `catdisent` | 23 | 29 | 5.0 |
| State teleport | 536 | 245 | 9.8 |
| `rswap` | 1072 | 490 | 19.6 |

Inspect them yourself for any profile:

```python
from memq_dqc import SchedulerHardwareProfile, load_settings

settings = load_settings()
settings.modality_profile("trapped_ion.sr")  # ModalityProfile(...)
settings.entanglement_profile("ion.time_bin")  # EntanglementGenerationProfile(...)
```

## Reading `settings.toml` directly

`load_settings()` returns a validated `Settings` object built from the packaged
file; `load_settings_file(path)` reads an alternative file, which is the
supported way to experiment with a whole settings file rather than a few
overrides.

```python
from memq_dqc import load_settings

settings = load_settings()
settings.global_settings.time_unit  # 'us'
settings.des_simulation.entanglement_time_step  # 1.0
sorted(".".join(k) for k in settings.modality_profiles)
# ['neutral_atom', 'trapped_ion.ba', 'trapped_ion.sr']
```

Selectors accept either dotted strings or separate components:
`settings.modality_profile("trapped_ion.ba")` and
`settings.modality_profile("trapped_ion", "ba")` are the same call. An unknown
selector raises `ValueError` naming the selector.

!!! note "The `[verification]` section is not yet wired up"
    `settings.toml` carries `verification.shots` and
    `verification.fidelity_threshold`, and `load_settings()` exposes them as
    `settings.verification`. **Nothing reads them.** `verify()` takes its own
    `shots` and `fidelity_threshold` arguments with independent defaults, so
    editing the TOML values has no effect on verification. Pass the arguments
    explicitly instead.

## Next

- [Scheduling Strategies](scheduling.md) — what each of the four schedulers
  does with these timings.
- [Scheduling & Hardware](https://dqc.readthedocs.io/en/latest/demos/scheduling_and_hardware/)
  — the runnable walkthrough.
