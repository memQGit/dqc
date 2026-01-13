# Local Checks

This repository uses **Ruff** for linting and formatting and **pytest** for tests. All checks are wrapped in a single script for convenience.

## Run all checks

First, make sure the script is executable (only needs to be done once):

    chmod +x scripts/check.sh

Then run all checks (lint, format check, and tests):

    ./scripts/check.sh

## Run checks individually

If you want to run each step on its own:

### Linting (Ruff)

    uv run ruff check .

### Formatting check (Ruff)

Checks formatting without modifying files:

    uv run ruff format --check .

To automatically format files instead:

    uv run ruff format .

### Tests (pytest)

    uv run pytest -q
