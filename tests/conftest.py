# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

import pytest


@pytest.fixture()
def simple1_network_path() -> Path:
    return Path(__file__).parent / "fixtures" / "networks" / "simple1.json"


@pytest.fixture()
def bell_circuit_path() -> Path:
    return Path(__file__).parent / "fixtures" / "circuits" / "bell.qasm"


@pytest.fixture()
def simple1_circuit_path() -> Path:
    return Path(__file__).parent / "fixtures" / "circuits" / "simple1.qasm"
