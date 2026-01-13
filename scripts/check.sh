#!/usr/bin/env bash
set -euo pipefail # Error handling

echo "▶ Running Ruff lint..." # Linting
uv run ruff check .

echo "▶ Running Ruff format check..." # Formatting
uv run ruff format --check .

echo "▶ Running tests..." # Pytest
uv run pytest -q

echo "✅ All checks passed. Ready to commit."
