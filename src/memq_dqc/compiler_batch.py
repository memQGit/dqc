# Copyright 2026 memQ Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""Batch compilation of scheduling instances with fingerprint caching.

Compiles many (circuit, network, options) requests into
:class:`~memq_dqc.scheduler.instance.SchedulingInstance` artifacts, preserving
input order, caching by ``source_fingerprint`` with atomic writes, and
optionally using process-based parallelism. The result artifacts are identical
regardless of worker count because compilation is deterministic. This module
imports no reinforcement-learning framework.
"""

from __future__ import annotations

import functools
import os
import tempfile
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from memq_dqc.compiler import (
    compile_scheduling_instance,
    compute_scheduling_source_fingerprint,
)
from memq_dqc.scheduler.instance_serialize import (
    scheduling_instance_from_json,
    scheduling_instance_to_json,
)

if TYPE_CHECKING:
    from collections.abc import Sequence
    from os import PathLike

    from memq_dqc.partition.partitioner import NetworkInput, ProgramInput
    from memq_dqc.scheduler.instance import (
        SchedulingCompileOptions,
        SchedulingInstance,
    )


@dataclass(frozen=True, slots=True)
class SchedulingCompileRequest:
    """One batch compilation request.

    Attributes:
        request_id: Caller-chosen identifier echoed back in the result.
        circuit: The input circuit (parsed program, path, or inline source).
            Use a file path when compiling with ``workers > 1`` so the request
            is picklable across processes.
        topology: The network topology (``NetworkGraph`` or path).
        options: Compilation options; ``None`` uses the defaults.
    """

    request_id: str
    circuit: ProgramInput
    topology: NetworkInput
    options: SchedulingCompileOptions | None = None


@dataclass(frozen=True, slots=True)
class SchedulingCompileResult:
    """The outcome of one batch compilation request.

    Attributes:
        request_id: Identifier of the originating request.
        instance: The compiled instance, or ``None`` when compilation failed.
        cache_hit: Whether the instance was loaded from the cache.
        elapsed_seconds: Wall-clock time spent on this request.
        error: A ``"TypeName: message"`` string when compilation failed, else
            ``None``.
    """

    request_id: str
    instance: SchedulingInstance | None
    cache_hit: bool
    elapsed_seconds: float
    error: str | None


def compile_scheduling_batch(
    requests: Sequence[SchedulingCompileRequest],
    *,
    workers: int = 1,
    cache_dir: str | PathLike[str] | None = None,
    fail_fast: bool = False,
) -> tuple[SchedulingCompileResult, ...]:
    """Compile a batch of scheduling-instance requests.

    Args:
        requests: Requests to compile. The returned results preserve this
            order.
        workers: Number of worker processes. ``1`` compiles sequentially;
            greater than ``1`` uses process-based parallelism.
        cache_dir: Optional directory for the fingerprint cache. When set,
            each artifact is cached by ``source_fingerprint`` with an atomic
            write and reused on a subsequent request with the same inputs.
        fail_fast: When ``True``, the first failing request raises instead of
            returning a per-request error.

    Returns:
        One :class:`SchedulingCompileResult` per request, in input order.

    Raises:
        ValueError: If ``workers`` is less than 1.
        RuntimeError: If ``fail_fast`` is ``True`` and a request fails.
    """
    if workers < 1:
        raise ValueError("workers must be at least 1.")

    resolved_cache_dir = _prepare_cache_dir(cache_dir)

    if workers == 1:
        results: list[SchedulingCompileResult] = []
        for request in requests:
            result = _compile_one(request, cache_dir=resolved_cache_dir)
            if fail_fast and result.error is not None:
                raise RuntimeError(
                    f"Request {request.request_id!r} failed: {result.error}"
                )
            results.append(result)
        return tuple(results)

    worker = functools.partial(_compile_one, cache_dir=resolved_cache_dir)
    with ProcessPoolExecutor(max_workers=workers) as executor:
        results = list(executor.map(worker, requests))

    if fail_fast:
        for result in results:
            if result.error is not None:
                raise RuntimeError(
                    f"Request {result.request_id!r} failed: {result.error}"
                )
    return tuple(results)


def _prepare_cache_dir(
    cache_dir: str | PathLike[str] | None,
) -> str | None:
    """Create the cache directory if needed and return it as a string.

    Returning a plain string keeps the value trivially picklable for process
    workers.

    Args:
        cache_dir: The requested cache directory, or ``None``.

    Returns:
        The cache directory path as a string, or ``None``.
    """
    if cache_dir is None:
        return None
    path = Path(cache_dir)
    path.mkdir(parents=True, exist_ok=True)
    return str(path)


def _compile_one(
    request: SchedulingCompileRequest,
    *,
    cache_dir: str | None,
) -> SchedulingCompileResult:
    """Compile a single request, using and populating the cache when set.

    Never raises: failures are captured in the returned result's ``error``.

    Args:
        request: The request to compile.
        cache_dir: The prepared cache directory, or ``None``.

    Returns:
        The compilation result for this request.
    """
    start = time.perf_counter()
    try:
        fingerprint = compute_scheduling_source_fingerprint(
            request.circuit, request.topology, request.options
        )
        cache_path = (
            None
            if cache_dir is None
            else Path(cache_dir) / f"{fingerprint}.json"
        )
        if cache_path is not None and cache_path.exists():
            instance = scheduling_instance_from_json(cache_path)
            return SchedulingCompileResult(
                request_id=request.request_id,
                instance=instance,
                cache_hit=True,
                elapsed_seconds=time.perf_counter() - start,
                error=None,
            )

        instance = compile_scheduling_instance(
            request.circuit,
            request.topology,
            options=request.options,
        )
        if cache_path is not None:
            _atomic_write(
                cache_path,
                scheduling_instance_to_json(instance, indent=None),
            )
        return SchedulingCompileResult(
            request_id=request.request_id,
            instance=instance,
            cache_hit=False,
            elapsed_seconds=time.perf_counter() - start,
            error=None,
        )
    except Exception as exc:  # noqa: BLE001 - reported as a per-request error
        return SchedulingCompileResult(
            request_id=request.request_id,
            instance=None,
            cache_hit=False,
            elapsed_seconds=time.perf_counter() - start,
            error=f"{type(exc).__name__}: {exc}",
        )


def _atomic_write(path: Path, content: str) -> None:
    """Write ``content`` to ``path`` atomically via a temporary file.

    Args:
        path: Destination file path.
        content: UTF-8 text to write.
    """
    directory = path.parent
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=directory,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    )
    try:
        with handle:
            handle.write(content)
        os.replace(handle.name, path)
    finally:
        if os.path.exists(handle.name):
            os.unlink(handle.name)
