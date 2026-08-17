# Installation

DQC uses the [uv](https://docs.astral.sh/uv/) package manager and requires
**Python 3.11 or newer**.

## From a clone

Clone the repository and sync the environment:

```bash
git clone https://github.com/memQGit/dqc.git
cd dqc
uv sync
```

`uv sync` installs the library and its runtime dependencies (Qiskit,
NetworkX, OpenQASM 3, matplotlib, and — on every platform except Windows —
KaHyPar) into a project virtual environment. Run any command inside that
environment with `uv run`, for example:

```bash
uv run python -c "import memq_dqc; print(memq_dqc.__all__)"
```

## As a dependency

To use DQC inside another project:

```bash
uv add memq-dqc
# or, with pip:
pip install memq-dqc
```

## Windows support

KaHyPar publishes no Windows wheels, so it is skipped automatically when
installing on Windows. Everything else installs and runs normally, and four
of the five partitioners are unaffected — only
[`HypergraphPartitioner`][memq_dqc.partition.HypergraphPartitioner] needs
KaHyPar, and it raises an `ImportError` explaining the situation if called.
On Linux and macOS all five partitioners are available by default.

## Development dependencies

The `dev` dependency group adds the tooling used for linting, type checking,
tests, and building this documentation site (Ruff, pyright, pytest, tox, and
MkDocs). It is installed by default with `uv sync`. See the
[Contributing](https://github.com/memQGit/dqc/blob/main/CONTRIBUTING.md)
guide for the full check suite.
