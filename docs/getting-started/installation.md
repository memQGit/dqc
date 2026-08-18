# Installation

DQC requires **Python 3.11 or newer** and is built and published with the
[uv](https://docs.astral.sh/uv/) package manager. If you're new to uv, see
the [first steps guide](https://docs.astral.sh/uv/getting-started/first-steps/)
to get it installed.

## From PyPI

The package is published on PyPI as `memq-dqc`. To add it to an existing
project:

```bash
uv add memq-dqc
# or, with pip:
pip install memq-dqc
```

This installs the library and its runtime dependencies (with the exception of KaHyPar for Windows users).
This is the fastest way to get started if you just want to import
`memq_dqc` into your own code.

## From a clone

Cloning the repository additionally gives you the example circuits,
benchmarking assets, and demo notebooks used throughout these docs (under
`examples/`, `benchmarking/`, and `demo/`), which are not part of the PyPI
package.

```bash
git clone https://github.com/memQGit/dqc.git
cd dqc
uv sync
```

`uv sync` installs the library and its runtime dependencies into a project
virtual environment. Run any command inside that environment with
`uv run`, for example:

```bash
uv run python -c "import memq_dqc; print(memq_dqc.__all__)"
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
