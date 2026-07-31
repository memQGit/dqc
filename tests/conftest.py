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
def chain_3qpu_2pairs_network_path() -> Path:
    # 0-1 and 1-2 each carry two disjoint pairs; 0 and 2 are not directly
    # linked, so a swap between them is only reachable by routing.
    return (
        Path(__file__).parent
        / "fixtures"
        / "networks"
        / "chain_3qpu_2pairs.json"
    )


@pytest.fixture()
def hundred_qubit_network_path() -> Path:
    return Path(__file__).parent / "fixtures" / "networks" / "50x2.json"


@pytest.fixture()
def eight_comp_four_comm_network_path() -> Path:
    return (
        Path(__file__).parent
        / "fixtures"
        / "networks"
        / "simple_8comp_4comm.json"
    )


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
