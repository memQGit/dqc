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

"""Tests for scheduling-instance JSON persistence."""

import dataclasses
import json
import math
from pathlib import Path

import pytest

from memq_dqc import compile_scheduling_instance
from memq_dqc.scheduler import (
    scheduling_instance_from_json,
    scheduling_instance_to_json,
)


@pytest.fixture()
def instance(
    simple1_circuit_path: Path,
    three_comp_one_comm_x2_network_path: Path,
):
    return compile_scheduling_instance(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )


def test_round_trip_equality(instance) -> None:
    document = scheduling_instance_to_json(instance)
    assert scheduling_instance_from_json(document) == instance


def test_compact_round_trip_equality(instance) -> None:
    document = scheduling_instance_to_json(instance, indent=None)
    assert "\n" not in document
    assert scheduling_instance_from_json(document) == instance


def test_top_level_shape(instance) -> None:
    document = json.loads(scheduling_instance_to_json(instance))
    assert document["type"] == "scheduling_instance"
    assert document["schema_version"] == instance.schema_version
    assert {
        "operations",
        "dependencies",
        "resources",
        "epr_demands",
        "nominal_makespan",
        "instance_id",
        "compiler_version",
        "source_fingerprint",
        "time_unit",
        "metadata",
    } <= set(document)


def test_file_round_trip(instance, tmp_path: Path) -> None:
    path = tmp_path / "instance.json"
    scheduling_instance_to_json(instance, path)
    assert scheduling_instance_from_json(path) == instance
    assert scheduling_instance_from_json(str(path)) == instance


def test_mapping_round_trip(instance) -> None:
    document = json.loads(scheduling_instance_to_json(instance))
    assert scheduling_instance_from_json(document) == instance


def test_non_finite_rejected_on_write(instance) -> None:
    broken = dataclasses.replace(instance, nominal_makespan=math.inf)
    with pytest.raises(ValueError):
        scheduling_instance_to_json(broken)


def test_non_finite_literal_rejected_on_read(instance) -> None:
    document = scheduling_instance_to_json(instance)
    corrupted = document.replace(
        f'"nominal_makespan": {instance.nominal_makespan}',
        '"nominal_makespan": Infinity',
    )
    assert "Infinity" in corrupted
    with pytest.raises(ValueError, match="non-finite"):
        scheduling_instance_from_json(corrupted)


def test_unsupported_schema_version_rejected(instance) -> None:
    document = json.loads(scheduling_instance_to_json(instance))
    document["schema_version"] = 999
    with pytest.raises(ValueError, match="schema version"):
        scheduling_instance_from_json(document)


def test_unsupported_type_rejected(instance) -> None:
    document = json.loads(scheduling_instance_to_json(instance))
    document["type"] = "not_an_instance"
    with pytest.raises(ValueError, match="Unsupported document type"):
        scheduling_instance_from_json(document)
