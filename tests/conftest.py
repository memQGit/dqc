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


# TODO: must replace all fixtures with update JSON (also in samples)
@pytest.fixture()
def three_comp_one_comm_x2_network_path() -> Path:
    return (
        Path(__file__).parent / "fixtures" / "networks" / "3comp_1comm_x2.json"
    )


@pytest.fixture()
def hundred_qubit_network_path() -> Path:
    return Path(__file__).parent / "fixtures" / "networks" / "50x2.json"


@pytest.fixture()
def bell_circuit_path() -> Path:
    return Path(__file__).parent / "fixtures" / "circuits" / "bell.qasm"


@pytest.fixture()
def simple1_circuit_path() -> Path:
    return Path(__file__).parent / "fixtures" / "circuits" / "simple1.qasm"


@pytest.fixture()
def qv_100_circuit_path() -> Path:
    return Path(__file__).parent / "fixtures" / "circuits" / "qv_100.qasm"


@pytest.fixture()
def two_reg_circuit_path() -> Path:
    return Path(__file__).parent / "fixtures" / "circuits" / "two_reg.qasm"
