# Changelog

All notable changes to this project are documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

Until `1.0.0`, the public API may change in any minor release. Breaking
changes are always listed under **Changed** or **Removed**.

## [Unreleased]

### Added

- Four runnable demo notebooks in `demo/`, covering network definition,
  partitioner benchmarking, scheduling and hardware models, and the full
  visualization suite, plus a `demo/README.md` index.
- Demo notebooks are rendered into the documentation site via
  `mkdocs-jupyter`.
- Documentation, coverage, Python version, and Ruff badges in the README.
- `RELEASE_TODO.md`, tracking everything outstanding before the first public
  release.

### Changed

- Narrowed the public API of `xdqc.preprocessing.qasm` to the OpenQASM entry
  points (`load_qasm_program`, `dump_qasm_program`, `parse_qasm_file`,
  `parse_qasm_source`) and `CircuitQubit`. The statement-cleaning helpers and
  `Cleaned*` node types remain importable from their defining modules but are
  no longer part of the supported API.
- `xdqc.utils` is now documented as internal. Import its helpers from
  `xdqc.utils.circuit_utils` or `xdqc.utils.common`.
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

[Unreleased]: https://github.com/memQGit/xdqc/compare/main...HEAD
