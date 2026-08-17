# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Until `1.0.0`, the public API may change in any minor release. Breaking
changes are always listed under **Changed** or **Removed**.

## [Unreleased]

### Added

- `memq_dqc.assets`, a reference suite of 40 network topologies and 10 circuits
  bundled inside the installed package, so the full workflow runs without
  supplying a topology first. `network_path()`, `circuit_path()`, and
  `network_doc_path()` resolve an asset name to a `Path`; `list_networks()` and
  `list_circuits()` enumerate what is available. Networks are grouped by the
  circuit size they host (10, 20, 30, 40, 60 qubits) across `pair`, `chain`,
  `ring`, and `hub` arrangements, each in a nearest-neighbour and an
  all-to-all intra-QPU variant, and every one carries a Markdown file
  documenting it. Circuits are transpiled OpenQASM 3.0 programs from 4 to 60
  qubits, each fully measured with one explicit `c[i] = measure q[i];` per
  qubit, so they serve as verification inputs as well as compilation inputs.
- Windows support. KaHyPar publishes no Windows wheels, so it is now skipped
  there via a platform marker instead of failing the whole install. Four of
  the five partitioners are unaffected; `HypergraphPartitioner` raises an
  `ImportError` explaining the situation and pointing at the alternatives.
- Four runnable demo notebooks in `demo/`, covering network definition,
  partitioner benchmarking, scheduling and hardware models, and the full
  visualization suite, plus a `demo/README.md` index.
- Demo notebooks are rendered into the documentation site via
  `mkdocs-jupyter`.
- Documentation, coverage, Python version, and Ruff badges in the README.
- `RELEASE_TODO.md`, tracking everything outstanding before the first public
  release.

### Changed

- Renamed the project from `xDQC` to **DQC**. The PyPI distribution is now
  `memq-dqc` (`pip install memq-dqc`) and the import name is `memq_dqc`
  (`import memq_dqc as dqc`). The GitHub repository moved to
  `memQGit/dqc`.
- `Partitioner.cost` (and `Compiler.cost`, which delegates to it) now always
  report the **measured** e-bit usage of the extracted distributed circuit.
  Previously the value was a partition-time approximation that silently
  switched to the measured figure once anything touched
  `distributed_circuit` — so the same compile could report different costs
  depending on call order. If a network cannot produce a distributed circuit
  at all, the approximation is returned and a warning is logged.
- Dependabot now uses the `uv` ecosystem instead of `pip`, so `uv.lock` is
  kept in step with `pyproject.toml`.
- `pyright` is temporarily relaxed from `strict` to `basic` and is advisory
  rather than a merge gate; see `CONTRIBUTING.md`.
- Narrowed the public API of `memq_dqc.preprocessing.qasm` to the OpenQASM entry
  points (`load_qasm_program`, `dump_qasm_program`, `parse_qasm_file`,
  `parse_qasm_source`) and `CircuitQubit`. The statement-cleaning helpers and
  `Cleaned*` node types remain importable from their defining modules but are
  no longer part of the supported API.
- `memq_dqc.utils` is now documented as internal. Import its helpers from
  `memq_dqc.utils.circuit_utils` or `memq_dqc.utils.common`.
- `pytest` now collects only `tests/`, so a bare `pytest` run no longer fails
  on unrelated local directories.

### Removed

- The `examples/` directory, which duplicated `demo/` and contained a notebook
  that no longer imported. Its inputs now live in `demo/inputs/`.

### Fixed

- Corrected the misspelled `pyrightcofig.json`, which meant the pyright
  configuration had never been applied.

## [0.1.0] - Unreleased

Initial development version. Not yet published.

[Unreleased]: https://github.com/memQGit/dqc/compare/main...HEAD
