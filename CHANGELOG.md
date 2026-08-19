# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Until `1.0.0`, the public API may change in any minor release. Breaking
changes are always listed under **Changed** or **Removed**.

## [Unreleased]

## [0.1.1] - 2026-08-19

### Fixed

- **`verify()` now works on a fresh install.** `qiskit-qasm3-import` is a
  runtime requirement — `verify_distributed_circuit()` parses OpenQASM 3 via
  `qiskit.qasm3.loads()`, which needs it — but it was declared only in the
  `dev` dependency group. A `pip install memq-dqc` therefore produced an
  environment where verification raised
  `MissingOptionalLibraryError`. It is now a project dependency, so no manual
  install is needed. Users on `0.1.0` can either upgrade or run
  `pip install qiskit_qasm3_import`.

## [0.1.0] - 2026-08-19

Initial public release.

DQC is a Python library for distributed quantum compilation: it takes an
OpenQASM circuit and a network topology, partitions the circuit across QPUs,
routes inter-QPU gates, reconstructs a distributed circuit, and builds a
time-execution schedule under a hardware model. It is aimed at researchers
benchmarking partitioning algorithms and exploring network configurations, and
every stage is usable standalone so a custom component drops into the same
pipeline.

### Added

- **Compiler pipeline.** `Compiler` runs the full workflow — parse, partition,
  reconstruct, verify — in a few lines, and each stage is also usable on its
  own (`NetworkGraph`, `Partitioner`, `Scheduler`).
- **Partitioning algorithms.** Five strategies behind a common
  `BasePartitioner` interface, so a custom algorithm drops into the same
  pipeline. `BasePartitioner`, `QPU`, `PartitionSchedule`, and
  `PartitionWindows` are exported from `memq_dqc.partition`: they appear in the
  signatures of `Compiler.__init__` (whose `algo` accepts a `BasePartitioner`
  subclass or instance) and `Compiler.recompile_with_placement` (whose
  `schedule` is a `PartitionSchedule`, keyed by `QPU`), so subclassing or
  injecting a placement does not require a private-looking import path.
- **Network model.** `NetworkGraph` loads a topology JSON, exposes QPU and
  qubit structure and routing, and prices remote operations in e-bits: 1 per
  remote gate plus 2 per teleportation hop, and 2 per hop for a remote swap.
- **Circuit reconstruction.** Distributed circuits are emitted as OpenQASM 3.0
  with explicit `catent` / `catdisent` / `rswap` operations, and verified
  against the monolithic original by sampling or statevector comparison.
- **Schedulers.** Four strategies: a greedy `fifo` baseline plus three
  discrete-event schedulers that model stochastic entanglement generation with
  link contention, arbitrating by FIFO, shortest duration, or critical path.
- **Hardware profiles.** `SchedulerHardwareProfile` selects from packaged
  trapped-ion (Ba⁺, Sr⁺) and neutral-atom modalities and four
  entanglement-generation profiles, with per-parameter overrides validated on
  construction.
- **Bundled assets.** `memq_dqc.assets` ships 40 network topologies and 10
  circuits inside the installed package, so the full workflow runs without
  supplying a topology first. `network_path()`, `circuit_path()`, and
  `network_doc_path()` resolve an asset name to a `Path`; `list_networks()` and
  `list_circuits()` enumerate what is available. Networks are grouped by the
  circuit size they host (10, 20, 30, 40, 60 qubits) across `pair`, `chain`,
  `ring`, and `hub` arrangements, each in a nearest-neighbour and an all-to-all
  intra-QPU variant, and every one carries a Markdown file documenting it.
  Circuits are transpiled OpenQASM 3.0 programs from 4 to 60 qubits, each fully
  measured with one explicit `c[i] = measure q[i];` per qubit, so they serve as
  verification inputs as well as compilation inputs.
- **Network builder.** An optional local web app (`uv run network-builder`,
  installed via the `memq-dqc[builder]` extra) for drawing topologies in the
  browser and exporting them as compiler-ready JSON. Flask stays out of the
  base install, so importing `memq_dqc` never pulls in a web stack.
- **Visualization.** Circuit DAGs, partition flow and heatmaps, execution
  Gantt charts, and animated execution playback.
- **Documentation.** Guides for the workflow, network topology format, network
  builder, bundled assets, partitioning, hardware and settings, scheduling,
  visualization, and logging, plus a generated API reference and a Key Features
  overview. Five runnable demo notebooks in `demo/` cover network definition,
  partitioner benchmarking, scheduling and hardware models, and the full
  visualization suite, indexed by `demo/README.md` and rendered into the site
  via `mkdocs-jupyter`.
- Documentation, coverage, Python version, and Ruff badges in the README.
- Windows support. KaHyPar publishes no Windows wheels, so it is skipped there
  via a platform marker instead of failing the whole install.
- `RELEASE_TODO.md`, tracking everything outstanding before the first public
  release.

### Changed

- The project was renamed from `xDQC` to **DQC** during development. The PyPI
  distribution is `memq-dqc` (`pip install memq-dqc`), the import name is
  `memq_dqc` (`import memq_dqc as dqc`), and the repository is `memQGit/dqc`.
- `Partitioner.cost` (and `Compiler.cost`, which delegates to it) always
  reports the **measured** e-bit usage of the extracted distributed circuit
  rather than a partition-time approximation that silently switched to the
  measured figure once anything touched `distributed_circuit`. If a network
  cannot produce a distributed circuit at all, the approximation is returned
  and a warning is logged.
- `NetworkGraph.remote_swap_ebit_cost` prices a routed swap at **2 e-bits per
  hop**. It previously charged `2 * (2h - 1)`, encoding an out-and-back walk to
  restore whatever occupied each intermediate QPU. That over-priced every
  routed swap the builder actually emits — a two-hop swap was estimated at 6
  e-bits and built for 4 — which biased partitioners away from routes that were
  in fact cheaper. Direct swaps are unaffected.
- The public API of `memq_dqc.preprocessing.qasm` is narrowed to the OpenQASM
  entry points (`load_qasm_program`, `dump_qasm_program`, `parse_qasm_file`,
  `parse_qasm_source`) and `CircuitQubit`. The statement-cleaning helpers and
  `Cleaned*` node types remain importable from their defining modules but are
  not part of the supported API.
- `memq_dqc.utils` is internal. Import its helpers from
  `memq_dqc.utils.circuit_utils` or `memq_dqc.utils.common`.
- `pyright` is temporarily relaxed from `strict` to `basic` and is advisory
  rather than a merge gate; see `CONTRIBUTING.md`.
- `pytest` collects only `tests/`, so a bare `pytest` run does not fail on
  unrelated local directories.
- Dependabot uses the `uv` ecosystem instead of `pip`, so `uv.lock` is kept in
  step with `pyproject.toml`.

### Fixed

- The scheduling guide's timing model misstated two durations: it priced an
  `rswap` at `t_2q + 2*t_1q + t_meas` when the scheduler charges
  `2 * (t_2q + 3*t_1q + 2*t_meas)`, and it treated a remote gate as one
  operation when `catent` and `catdisent` are priced separately.
- Relative links in notebook markdown cells resolved to nothing in both the
  built docs site and Jupyter. MkDocs link validation is now enabled and CI
  builds the docs with `--strict`, so broken links fail a pull request.
- Corrected the misspelled `pyrightcofig.json`, which meant the pyright
  configuration had never been applied.

### Known limitations

- **No local compilation passes yet.** The compiler distributes a circuit but
  does not optimise it. There is no gate cancellation, commutation-aware
  reordering, resynthesis, or peephole pass on the per-QPU circuits, so the
  local gate counts are whatever the input circuit and the reconstruction
  produce.
- **Limited two-qubit gate support.** Only `cx`, `cp`, `cry`, `cz`, and `swap`
  can be distributed across QPUs. A cross-QPU gate of any other name raises
  `ValueError` naming the supported set — decompose into the supported gates
  before compiling.
- **`HypergraphPartitioner` is unavailable on Windows.** KaHyPar publishes no
  Windows wheels, so it is skipped by a platform marker rather than failing the
  install. The other four partitioners are unaffected, and
  `HypergraphPartitioner` raises an `ImportError` explaining the situation and
  pointing at the alternatives.
- **The API reference still needs cleanup.** It is generated from docstrings
  per package, and the grouping, ordering, and cross-references are not yet
  curated. Prefer the hand-written guides for orientation and treat the
  reference as a lookup table.
- **`epr_lifetime` is pinned effectively infinite** (`1e9` µs) rather than the
  experimental 50 µs. At the default entanglement rate a 50 µs pair expires
  long before a second one can be generated, which makes any two-pair
  operation — such as a remote swap — impossible to assemble. The partitioner
  cost model has no notion of pair lifetime, so it will plan swaps no
  discrete-event scheduler can run, and `fifo` does not model pair lifetime at
  all, so it returns schedules for exactly the cases the DES schedulers declare
  infeasible.
- Per-qubit `coherenceTime` and per-link `fidelity` in topology files are
  parsed and recorded but not consumed by any partitioner or scheduler.
- The `[verification]` section of `settings.toml` is exposed via
  `load_settings()` but not read by `verify()`, which takes its own `shots` and
  `fidelity_threshold` arguments. Editing those TOML values has no effect.
- Type checking runs at pyright `basic`, not `strict`, and no `py.typed` marker
  ships — type quality is not yet verified enough to advertise.

### Removed

- The `examples/` directory, which duplicated `demo/` and contained a notebook
  that no longer imported. Its inputs now live in `demo/inputs/`.

[Unreleased]: https://github.com/memQGit/dqc/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/memQGit/dqc/compare/v0.1.0...v0.1.1
[0.1.0]: https://github.com/memQGit/dqc/releases/tag/v0.1.0
