#!/usr/bin/env bash
set -euo pipefail # Error handling

echo "▶ Running Ruff lint..." # Linting
uv run ruff check .

echo "▶ Running Ruff format check..." # Formatting
uv run ruff format --check .

echo "▶ Running tests (with coverage) ... " # Pytest
uv run pytest -q --cov=memq_dqc --cov-report=term-missing

echo "✅ All checks passed. Ready to commit."
