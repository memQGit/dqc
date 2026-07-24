# Installation

xDQC uses the [uv](https://docs.astral.sh/uv/) package manager and requires
**Python 3.11 or newer**.

## From a clone

Clone the repository and sync the environment:

```bash
git clone https://github.com/memQGit/xdqc.git
cd xdqc
uv sync
```

`uv sync` installs the library and its runtime dependencies (Qiskit,
NetworkX, KaHyPar, OpenQASM 3, and matplotlib) into a project virtual
environment. Run any command inside that environment with `uv run`, for
example:

```bash
uv run python -c "import xdqc; print(xdqc.__all__)"
```

## As a dependency

To use xDQC inside another project:

```bash
uv add xdqc
# or, with pip:
pip install xdqc
```

## Development dependencies

The `dev` dependency group adds the tooling used for linting, type checking,
tests, and building this documentation site (Ruff, pyright, pytest, tox, and
MkDocs). It is installed by default with `uv sync`. See the
[Contributing](https://github.com/memQGit/xdqc/blob/main/CONTRIBUTING.md)
guide for the full check suite.
