# Contributing to xDQC

Thanks for contributing! This repo values correctness, reproducibility, and
clean public APIs.

## Quickstart

1. Create a virtual environment with Python 3.11.
2. Install dependencies as needed for your workflow.

## Commands

- Lint: `tox -e lint`
- Format check: `tox -e format`
- Tests + coverage: `tox -e test`
- Type checking: `pyright`

If you need to auto-format:

- `ruff format .`
- Then re-run: `tox -e lint -e format -e test`

## Project layout

- Library code: `src/xdqc/`
- Tests: `tests/`
- Scripts: `scripts/`
- Docs: `docs/`

## Contribution guidelines

- Keep diffs focused and reviewable.
- Do not change public APIs unless explicitly requested.
- Add tests for behavior changes and new features.
- Update docstrings when behavior changes.
- Use type hints and Google-style docstrings for public modules, classes, and
  functions.

## Pull request checklist

- Tests pass (`tox -e test`).
- Lint and format checks pass (`tox -e lint`, `tox -e format`).
- Type checking passes (`pyright`).
- New/changed behavior is covered by tests.
