# memQ Distributed Quantum Compiler (memQ-DQC)


<p align="center">
    <a href="https://github.com/memQGit/DistributedCompiler/actions/workflows/ci.yml">
        <img src="https://github.com/memQGit/DistributedCompiler/actions/workflows/ci.yml/badge.svg" alt="CI Status">
    </a>
    <a href="https://github.com/memQGit/DistributedCompiler/blob/main/LICENSE">
      <img src="https://img.shields.io/badge/license-MIT-blue" alt="License">
    </a>
</p>

memQ-DQC is an open-source distributed quantum compiler designed to optimize and compile quantum circuits for execution on distributed quantum computing architectures.

---

This repository uses **Ruff** for linting and formatting and **pytest** for tests. All checks are wrapped in a single script for convenience.

### Run all checks

To run all checks locally (lint, format check, and tests):

    uv run tox

### Run checks individually

If you want to run each step on its own:

#### Linting (Ruff)

    uv run ruff check .

#### Formatting check (Ruff)

Checks formatting without modifying files:

    uv run ruff format --check .

To automatically format files instead:

    uv run ruff format .

#### Tests (pytest)

    uv run pytest -q
