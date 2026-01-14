# memQ Distributed Quantum Compiler (memQ-DQC)

memQ-DQC is an open-source distributed quantum compiler designed to optimize and compile quantum circuits for execution on distributed quantum computing architectures.

<p align="center">
    <a href="https://github.com/memQGit/DistributedCompiler/actions/workflows/ci.yml">
        <img src="https://github.com/memQGit/DistributedCompiler/actions/workflows/ci.yml/badge.svg" alt="CI Status">
    </a>
    <a href="https://github.com/memQGit/DistributedCompiler/blob/main/LICENSE">
      <img src="https://img.shields.io/github/license/memQGit/DistributedCompiler" alt="License">
    </a>

</p>

This repository uses **Ruff** for linting and formatting and **pytest** for tests. All checks are wrapped in a single script for convenience.

### Run all checks

First, make sure the script is executable (only needs to be done once):

    chmod +x scripts/check.sh

Then run all checks (lint, format check, and tests):

    ./scripts/check.sh

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
