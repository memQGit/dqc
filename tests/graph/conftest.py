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
    return (
        Path(__file__).resolve().parents[1]
        / "data"
        / "networks"
        / "simple1.json"
    )
