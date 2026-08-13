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
- Type checking: `pyright` (advisory — see below)

If you need to auto-format:

- `ruff format .`
- Then re-run: `tox -e lint -e format -e test`

## Project layout

- Library code: `src/xdqc/`
- Tests: `tests/`
- Scripts: `scripts/`
- Docs: `docs/`
- Runnable demo notebooks: `demo/`

## Changelog

We keep a human-written changelog in [`CHANGELOG.md`](CHANGELOG.md), following
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

**Any user-visible change needs a changelog entry in the same pull request.**
Add it under `## [Unreleased]`, in whichever of these applies:

| Section | Use for |
| --- | --- |
| `Added` | New features |
| `Changed` | Changes to existing behavior, including breaking ones |
| `Deprecated` | Features that still work but will be removed |
| `Removed` | Features taken out |
| `Fixed` | Bug fixes |
| `Security` | Vulnerability fixes |

Write entries for the person upgrading, not the person who wrote the patch:
say what changed and what a user must now do differently. Internal
refactors, test-only changes, and CI tweaks do not need an entry.

On release, `## [Unreleased]` is renamed to the new version with a date, a
fresh `Unreleased` section is opened above it, and the version tag is pushed.

## Contribution guidelines

- Keep diffs focused and reviewable.
- Do not change public APIs unless explicitly requested.
- Add tests for behavior changes and new features.
- Update docstrings when behavior changes.
- Use type hints and Google-style docstrings for public modules, classes, and
  functions.

## Type checking

New code should carry full type hints, and `pyright` is configured to check
`src/` and `tests/`. It is currently **advisory rather than a gate**: the
configuration is temporarily relaxed from `strict` to `basic` because several
core dependencies (networkx, matplotlib, qiskit) ship no type information, and
a backlog of pre-existing findings has not been cleared. Do not add new type
errors, but you are not expected to fix unrelated ones. Restoring strict mode
is tracked in [`RELEASE_TODO.md`](RELEASE_TODO.md).

## Pull request checklist

- Tests pass (`tox -e test`).
- Lint and format checks pass (`tox -e lint`, `tox -e format`).
- New/changed behavior is covered by tests.
- User-visible changes have a `CHANGELOG.md` entry.
