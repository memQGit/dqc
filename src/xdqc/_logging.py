"""Internal helpers for xdqc workflow logging.

These utilities provide per-call verbosity control for the main workflow
entrypoints while still using Python's standard ``logging`` module.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from time import perf_counter
from typing import Literal, cast

Verbosity = Literal["quiet", "info", "debug"]

_LOGGER_NAME = "xdqc"
_VERBOSITY_TO_LEVEL: dict[Verbosity, int] = {
    "quiet": logging.WARNING,
    "info": logging.INFO,
    "debug": logging.DEBUG,
}
_LOG_FORMAT = "%(asctime)s | %(levelname)s | %(name)s | %(message)s"
_LOG_DATE_FORMAT = "%Y-%m-%d %H:%M:%S"


@dataclass(slots=True)
class StepTimer:
    """Track elapsed wall-clock time for workflow logging."""

    _start_time: float = field(default_factory=perf_counter)

    def elapsed_seconds(self) -> float:
        """Return elapsed time in seconds."""
        return perf_counter() - self._start_time


def validate_verbosity(verbosity: str) -> Verbosity:
    """Validate and normalize a workflow verbosity string.

    Args:
        verbosity: User-provided verbosity level.

    Returns:
        Normalized verbosity level.

    Raises:
        ValueError: If the verbosity level is unsupported.
    """
    if verbosity not in _VERBOSITY_TO_LEVEL:
        allowed = ", ".join(_VERBOSITY_TO_LEVEL)
        raise ValueError(
            f"Unsupported verbosity {verbosity!r}. Expected one of: {allowed}."
        )
    return cast(Verbosity, verbosity)


def verbosity_to_level(verbosity: str) -> int:
    """Return the logging level for a validated verbosity string."""
    return _VERBOSITY_TO_LEVEL[validate_verbosity(verbosity)]


@contextmanager
def workflow_logging(verbosity: str) -> Iterator[logging.Logger]:
    """Temporarily configure package logging for one workflow call.

    Args:
        verbosity: User-selected verbosity level.

    Yields:
        The package logger for ``xdqc``.
    """
    level = verbosity_to_level(verbosity)
    logger = logging.getLogger(_LOGGER_NAME)
    previous_level = logger.level
    temporary_handler: logging.Handler | None = None

    if level < logging.WARNING and not logger.hasHandlers():
        temporary_handler = logging.StreamHandler()
        temporary_handler.setLevel(level)
        temporary_handler.setFormatter(
            logging.Formatter(_LOG_FORMAT, datefmt=_LOG_DATE_FORMAT)
        )
        logger.addHandler(temporary_handler)

    logger.setLevel(level)
    try:
        yield logger
    finally:
        if temporary_handler is not None:
            logger.removeHandler(temporary_handler)
        logger.setLevel(previous_level)
