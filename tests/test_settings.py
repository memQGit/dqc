# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

import pytest

from xdqc import (
    default_settings_path,
    load_settings,
    load_settings_file,
)


def test_load_settings_parses_packaged_toml() -> None:
    settings = load_settings()

    assert settings.global_settings.time_unit == "us"
    assert settings.des_simulation.entanglement_time_step == pytest.approx(1.0)
    assert settings.verification.shots == 10_000_000
    assert settings.verification.fidelity_threshold == pytest.approx(0.95)


def test_load_settings_resolves_profiles() -> None:
    settings = load_settings()

    ba_profile = settings.modality_profile("trapped_ion", "ba")
    time_bin_profile = settings.entanglement_profile("ion.time_bin")

    assert ba_profile.one_qubit_gate_time == pytest.approx(10.0)
    assert ba_profile.two_qubit_gate_time == pytest.approx(500.0)
    assert time_bin_profile.entanglement_rate == pytest.approx(3.5e-6)
    assert time_bin_profile.epr_lifetime == pytest.approx(50.0)


def test_default_settings_path_points_to_packaged_file() -> None:
    settings_path = default_settings_path()

    assert isinstance(settings_path, Path)
    assert settings_path.name == "settings.toml"
    assert settings_path.is_file()


def test_load_settings_file_rejects_invalid_toml(tmp_path: Path) -> None:
    settings_path = tmp_path / "bad_settings.toml"
    settings_path.write_text(
        "[verification]\nshots = 1e7 * 2\n", encoding="utf-8"
    )

    with pytest.raises(ValueError, match="Invalid TOML"):
        load_settings_file(settings_path)


def test_load_settings_file_rejects_missing_required_keys(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "missing_keys.toml"
    settings_path.write_text(
        """
[modality.trapped_ion.ba]
1q_gate_time = 10
2q_gate_time = 500

[scheduler.des]
entanglement_time_step = 1.0

[entanglement_gen.ion.time_bin]
entanglement_rate = 3.5e-6
epr_lifetime = 50
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="Missing required settings table"):
        load_settings_file(settings_path)


def test_load_settings_file_rejects_nonpositive_des_time_step(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "bad_des_settings.toml"
    settings_path.write_text(
        """
[global]
time_unit = "us"

[scheduler.des]
entanglement_time_step = 0.0

[modality.trapped_ion.ba]
1q_gate_time = 10
2q_gate_time = 500

[entanglement_gen.ion.time_bin]
entanglement_rate = 3.5e-6
epr_lifetime = 50

[verification]
shots = 100
fidelity_threshold = 0.95
""".strip(),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="entanglement_time_step"):
        load_settings_file(settings_path)


def test_profile_selectors_reject_unknown_profiles() -> None:
    settings = load_settings()

    with pytest.raises(ValueError, match="Unknown modality profile"):
        settings.modality_profile("trapped_ion", "ca")

    with pytest.raises(ValueError, match="Unknown entanglement profile"):
        settings.entanglement_profile("ion", "unknown")
