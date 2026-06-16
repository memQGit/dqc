"""Entry point shim for the compiler benchmark CLI.

Exposes ``uv run bench`` as a short alias for running
``benchmarking/compiler_benchmarking/run_compiler_benchmark.py``.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

_SCRIPT_PATH: Path = (
    Path(__file__).resolve().parents[2]
    / "benchmarking"
    / "compiler_benchmarking"
    / "run_compiler_benchmark.py"
)


def main() -> None:
    """Load and run the compiler benchmark CLI.

    Delegates to the benchmark runner script so it can be invoked as
    ``uv run bench`` rather than the full explicit path. The script's own
    ``__file__``-relative data directory discovery is preserved because
    importlib sets ``__file__`` to the actual script path.

    Raises:
        RuntimeError: If the benchmark script cannot be located or loaded.
    """
    spec = importlib.util.spec_from_file_location(
        "run_compiler_benchmark", _SCRIPT_PATH
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load benchmark script: {_SCRIPT_PATH}")
    module: ModuleType = importlib.util.module_from_spec(spec)
    sys.modules["run_compiler_benchmark"] = module
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    module.main()
