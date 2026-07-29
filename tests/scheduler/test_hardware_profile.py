# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Tests for custom hardware parameter overrides on the hardware profile."""

import math
from collections.abc import Callable

import pytest

from xdqc import SchedulerHardwareProfile, load_settings
from xdqc.scheduler.schedule import (
    _MEASUREMENT_TIME,
    _load_scheduler_timing_model,
    _resolve_scheduler_hardware_profile,
)

# One single-field constructor per overridable parameter, so each test can
# build a profile that sets exactly one value without dynamic kwargs.
_SINGLE_OVERRIDE_BUILDERS: dict[
    str, Callable[[float], SchedulerHardwareProfile]
] = {
    "one_qubit_gate_time": lambda value: SchedulerHardwareProfile(
        one_qubit_gate_time=value
    ),
    "two_qubit_gate_time": lambda value: SchedulerHardwareProfile(
        two_qubit_gate_time=value
    ),
    "measurement_time": lambda value: SchedulerHardwareProfile(
        measurement_time=value
    ),
    "entanglement_rate": lambda value: SchedulerHardwareProfile(
        entanglement_rate=value
    ),
    "epr_lifetime": lambda value: SchedulerHardwareProfile(epr_lifetime=value),
}

_TIMING_MODEL_ATTRIBUTES = {
    "one_qubit_gate_time": "local_one_qubit_gate_time",
    "two_qubit_gate_time": "local_two_qubit_gate_time",
    "measurement_time": "measurement_time",
    "entanglement_rate": "entanglement_generation_rate",
    "epr_lifetime": "epr_lifetime",
}


def test_default_profile_has_no_overrides() -> None:
    assert SchedulerHardwareProfile().overrides == {}


def test_defaults_resolve_from_settings() -> None:
    settings = load_settings()
    profile = SchedulerHardwareProfile()

    timing = _load_scheduler_timing_model(profile)
    modality = settings.modality_profile(profile.modality)
    entanglement = settings.entanglement_profile(profile.entanglement_profile)

    assert timing.local_one_qubit_gate_time == pytest.approx(
        modality.one_qubit_gate_time
    )
    assert timing.local_two_qubit_gate_time == pytest.approx(
        modality.two_qubit_gate_time
    )
    assert timing.entanglement_generation_rate == pytest.approx(
        entanglement.entanglement_rate
    )
    assert timing.epr_lifetime == pytest.approx(entanglement.epr_lifetime)
    assert timing.measurement_time == pytest.approx(_MEASUREMENT_TIME)


@pytest.mark.parametrize("field", _SINGLE_OVERRIDE_BUILDERS)
def test_each_override_reaches_the_timing_model(field: str) -> None:
    value = 0.125
    profile = _SINGLE_OVERRIDE_BUILDERS[field](value)

    timing = _load_scheduler_timing_model(profile)

    assert profile.overrides == {field: value}
    assert getattr(timing, _TIMING_MODEL_ATTRIBUTES[field]) == pytest.approx(
        value
    )


def test_unset_fields_still_come_from_the_selected_profile() -> None:
    settings = load_settings()
    profile = SchedulerHardwareProfile(two_qubit_gate_time=120.0)

    timing = _load_scheduler_timing_model(profile)
    modality = settings.modality_profile(profile.modality)
    entanglement = settings.entanglement_profile(profile.entanglement_profile)

    assert timing.local_two_qubit_gate_time == pytest.approx(120.0)
    assert timing.local_one_qubit_gate_time == pytest.approx(
        modality.one_qubit_gate_time
    )
    assert timing.epr_lifetime == pytest.approx(entanglement.epr_lifetime)
    assert timing.measurement_time == pytest.approx(_MEASUREMENT_TIME)


def test_des_time_step_is_not_overridable() -> None:
    settings = load_settings()
    profile = SchedulerHardwareProfile(two_qubit_gate_time=120.0)

    timing = _load_scheduler_timing_model(profile)

    assert timing.des_entanglement_time_step == pytest.approx(
        settings.des_simulation.entanglement_time_step
    )
    assert not hasattr(profile, "des_entanglement_time_step")


def test_gate_time_overrides_flow_into_derived_timings() -> None:
    profile = SchedulerHardwareProfile(
        one_qubit_gate_time=4.0,
        two_qubit_gate_time=100.0,
        measurement_time=1.0,
    )

    timing = _load_scheduler_timing_model(profile)

    assert timing.catent_time == pytest.approx(100.0 + 4.0 + 1.0)
    assert timing.catdisent_time == pytest.approx((2 * 4.0) + 1.0)
    assert timing.state_teleport_time == pytest.approx(100.0 + (2 * 4.0) + 1.0)


def test_entanglement_rate_override_flows_into_derived_timings() -> None:
    settings = load_settings()
    profile = SchedulerHardwareProfile(entanglement_rate=1e-3)

    timing = _load_scheduler_timing_model(profile)
    time_step = settings.des_simulation.entanglement_time_step

    assert timing.entanglement_time == pytest.approx(1.0 / 1e-3)
    assert timing.des_success_probability == pytest.approx(
        -math.expm1(-1e-3 * time_step)
    )


@pytest.mark.parametrize("field", _SINGLE_OVERRIDE_BUILDERS)
@pytest.mark.parametrize(
    "value", [0.0, -1.0, float("nan"), float("inf"), float("-inf")]
)
def test_non_positive_overrides_are_rejected(field: str, value: float) -> None:
    with pytest.raises(ValueError, match=f"{field} must be a positive number"):
        _SINGLE_OVERRIDE_BUILDERS[field](value)


@pytest.mark.parametrize(
    ("constructor", "modality"),
    [
        (SchedulerHardwareProfile.ba_trapped_ion, "trapped_ion.ba"),
        (SchedulerHardwareProfile.sr_trapped_ion, "trapped_ion.sr"),
        (SchedulerHardwareProfile.neutral_atom, "neutral_atom"),
    ],
)
def test_constructors_forward_overrides(
    constructor: Callable[..., SchedulerHardwareProfile], modality: str
) -> None:
    profile = constructor(two_qubit_gate_time=120.0, epr_lifetime=80.0)

    assert profile.modality == modality
    assert profile.overrides == {
        "two_qubit_gate_time": 120.0,
        "epr_lifetime": 80.0,
    }


def test_constructors_without_overrides_match_the_defaults() -> None:
    profile = SchedulerHardwareProfile.ba_trapped_ion()

    assert profile == SchedulerHardwareProfile()


def test_profile_with_overrides_still_rejects_scalar_selectors() -> None:
    profile = SchedulerHardwareProfile(two_qubit_gate_time=120.0)

    with pytest.raises(ValueError, match="cannot be combined"):
        _resolve_scheduler_hardware_profile(
            profile=profile,
            modality="neutral_atom",
            entanglement_profile="ion.time_bin",
        )


def test_profiles_differing_only_in_overrides_are_distinct() -> None:
    first = SchedulerHardwareProfile(two_qubit_gate_time=120.0)
    second = SchedulerHardwareProfile(two_qubit_gate_time=240.0)

    assert first != second
    assert hash(first) != hash(second)
    assert _load_scheduler_timing_model(
        first
    ) is not _load_scheduler_timing_model(second)
