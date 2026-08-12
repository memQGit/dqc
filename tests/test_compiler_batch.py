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

"""Tests for batch scheduling-instance compilation and caching."""

from pathlib import Path

import pytest

from xdqc import (
    SchedulingCompileRequest,
    compile_scheduling_batch,
    scheduling_instance_to_json,
)


def _requests(
    simple1: Path,
    bell: Path,
    net: Path,
) -> list[SchedulingCompileRequest]:
    return [
        SchedulingCompileRequest("simple1", simple1, net),
        SchedulingCompileRequest("bell", bell, net),
    ]


def test_batch_preserves_order_and_succeeds(
    simple1_circuit_path: Path,
    bell_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    results = compile_scheduling_batch(
        _requests(
            simple1_circuit_path,
            bell_circuit_path,
            three_comp_one_comm_x2_network_path,
        )
    )
    assert [result.request_id for result in results] == ["simple1", "bell"]
    assert all(result.error is None for result in results)
    assert all(result.instance is not None for result in results)


def test_cache_miss_then_hit(
    simple1_circuit_path: Path,
    bell_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
    tmp_path: Path,
) -> None:
    requests = _requests(
        simple1_circuit_path,
        bell_circuit_path,
        three_comp_one_comm_x2_network_path,
    )
    first = compile_scheduling_batch(requests, cache_dir=tmp_path)
    assert all(not result.cache_hit for result in first)
    assert list(tmp_path.glob("*.json"))

    second = compile_scheduling_batch(requests, cache_dir=tmp_path)
    assert all(result.cache_hit for result in second)
    for before, after in zip(first, second, strict=True):
        assert scheduling_instance_to_json(
            before.instance, indent=None
        ) == scheduling_instance_to_json(after.instance, indent=None)


def test_duplicate_request_hits_cache_within_batch(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
    tmp_path: Path,
) -> None:
    requests = [
        SchedulingCompileRequest(
            "first", simple1_circuit_path, three_comp_one_comm_x2_network_path
        ),
        SchedulingCompileRequest(
            "second", simple1_circuit_path, three_comp_one_comm_x2_network_path
        ),
    ]
    results = compile_scheduling_batch(requests, cache_dir=tmp_path)
    assert results[0].cache_hit is False
    assert results[1].cache_hit is True


def test_per_request_error_captured(
    bell_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
    tmp_path: Path,
) -> None:
    requests = [
        SchedulingCompileRequest(
            "ok", bell_circuit_path, three_comp_one_comm_x2_network_path
        ),
        SchedulingCompileRequest(
            "bad",
            tmp_path / "missing.qasm",
            three_comp_one_comm_x2_network_path,
        ),
    ]
    results = compile_scheduling_batch(requests)
    assert results[0].error is None
    assert results[0].instance is not None
    assert results[1].error is not None
    assert results[1].instance is None


def test_fail_fast_raises(
    bell_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
    tmp_path: Path,
) -> None:
    requests = [
        SchedulingCompileRequest(
            "bad",
            tmp_path / "missing.qasm",
            three_comp_one_comm_x2_network_path,
        ),
    ]
    with pytest.raises(RuntimeError, match="failed"):
        compile_scheduling_batch(requests, fail_fast=True)


def test_invalid_worker_count_rejected(
    bell_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    with pytest.raises(ValueError, match="workers"):
        compile_scheduling_batch(
            [
                SchedulingCompileRequest(
                    "bell",
                    bell_circuit_path,
                    three_comp_one_comm_x2_network_path,
                )
            ],
            workers=0,
        )


def test_parallel_matches_sequential(
    simple1_circuit_path: Path,
    bell_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
) -> None:
    requests = _requests(
        simple1_circuit_path,
        bell_circuit_path,
        three_comp_one_comm_x2_network_path,
    )
    sequential = compile_scheduling_batch(requests, workers=1)
    parallel = compile_scheduling_batch(requests, workers=2)

    assert [r.request_id for r in parallel] == ["simple1", "bell"]
    for seq, par in zip(sequential, parallel, strict=True):
        assert par.error is None
        assert scheduling_instance_to_json(
            seq.instance, indent=None
        ) == scheduling_instance_to_json(par.instance, indent=None)
