# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Load and validate packaged xdqc settings."""

from __future__ import annotations

import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class GlobalSettings:
    """Optional global settings shared across workflows.

    Attributes:
        time_unit: Optional human-readable time unit label such as ``"us"``.
    """

    time_unit: str | None = None


@dataclass(frozen=True, slots=True)
class ModalityProfile:
    """Timing assumptions for one hardware modality profile.

    Attributes:
        path: Selector path used to identify the profile.
        one_qubit_gate_time: Duration of a single-qubit gate.
        two_qubit_gate_time: Duration of a two-qubit gate.
    """

    path: tuple[str, ...]
    one_qubit_gate_time: float
    two_qubit_gate_time: float


@dataclass(frozen=True, slots=True)
class EntanglementGenerationProfile:
    """Entanglement-generation assumptions for one link profile.

    Attributes:
        path: Selector path used to identify the profile.
        entanglement_rate: Nominal entanglement generation rate.
        epr_lifetime: Maximum lifetime of a generated EPR pair.
    """

    path: tuple[str, ...]
    entanglement_rate: float
    epr_lifetime: float


@dataclass(frozen=True, slots=True)
class VerificationSettings:
    """Verification defaults loaded from TOML.

    Attributes:
        shots: Number of simulator shots to use by default.
        fidelity_threshold: Minimum required fidelity threshold.
    """

    shots: int
    fidelity_threshold: float


@dataclass(frozen=True, slots=True)
class DESSimulationSettings:
    """Timing assumptions for DES scheduler simulation.

    Attributes:
        entanglement_time_step: Duration of one entanglement-attempt cycle.
    """

    entanglement_time_step: float


@dataclass(frozen=True, slots=True)
class Settings:
    """Validated settings loaded from TOML.

    Attributes:
        global_settings: Optional global configuration values.
        des_simulation: DES scheduler simulation timing settings.
        modality_profiles: Modality timing profiles indexed by selector path.
        entanglement_profiles: Entanglement profiles indexed by selector path.
        verification: Verification defaults.
    """

    global_settings: GlobalSettings
    des_simulation: DESSimulationSettings
    modality_profiles: dict[tuple[str, ...], ModalityProfile]
    entanglement_profiles: dict[tuple[str, ...], EntanglementGenerationProfile]
    verification: VerificationSettings

    def modality_profile(self, *path: str) -> ModalityProfile:
        """Return one modality profile selected by path.

        Args:
            *path: Selector components such as ``"trapped_ion", "ba"`` or a
                single dotted selector such as ``"trapped_ion.ba"``.

        Returns:
            The matching modality profile.

        Raises:
            ValueError: If the selector is empty or no matching profile exists.
        """
        selector = _normalize_selector(*path)
        try:
            return self.modality_profiles[selector]
        except KeyError as exc:
            raise ValueError(
                f"Unknown modality profile selector: {'.'.join(selector)!r}."
            ) from exc

    def entanglement_profile(
        self, *path: str
    ) -> EntanglementGenerationProfile:
        """Return one entanglement-generation profile selected by path.

        Args:
            *path: Selector components such as ``"ion", "time_bin"`` or a
                single dotted selector such as ``"ion.time_bin"``.

        Returns:
            The matching entanglement-generation profile.

        Raises:
            ValueError: If the selector is empty or no matching profile exists.
        """
        selector = _normalize_selector(*path)
        try:
            return self.entanglement_profiles[selector]
        except KeyError as exc:
            raise ValueError(
                "Unknown entanglement profile selector: "
                f"{'.'.join(selector)!r}."
            ) from exc


def default_settings_path() -> Path:
    """Return the packaged default settings file path."""
    return Path(__file__).with_name("settings.toml")


def load_settings() -> Settings:
    """Load and validate the packaged default settings."""
    return load_settings_file(default_settings_path())


def load_settings_file(path: str | Path) -> Settings:
    """Load and validate settings from a TOML file.

    Args:
        path: Filesystem path to the TOML file.

    Returns:
        The validated settings object.

    Raises:
        ValueError: If the TOML file is malformed or misses required fields.
    """
    settings_path = Path(path)
    try:
        with settings_path.open("rb") as handle:
            raw_settings = tomllib.load(handle)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(
            f"Invalid TOML in settings file {settings_path!s}: {exc}."
        ) from exc

    if not isinstance(raw_settings, dict):
        raise ValueError(
            f"Settings file {settings_path!s} must contain a TOML table."
        )

    return Settings(
        global_settings=_parse_global_settings(raw_settings),
        des_simulation=_parse_des_simulation_settings(raw_settings),
        modality_profiles=_parse_modality_profiles(raw_settings),
        entanglement_profiles=_parse_entanglement_profiles(raw_settings),
        verification=_parse_verification_settings(raw_settings),
    )


def _parse_global_settings(raw_settings: dict[str, Any]) -> GlobalSettings:
    """Parse optional global settings from TOML data."""
    global_settings = _require_table(raw_settings, "global", required=False)
    time_unit = global_settings.get("time_unit")
    if time_unit is not None and not isinstance(time_unit, str):
        raise ValueError("settings.global.time_unit must be a string.")
    return GlobalSettings(time_unit=time_unit)


def _parse_des_simulation_settings(
    raw_settings: dict[str, Any],
) -> DESSimulationSettings:
    """Parse DES scheduler simulation settings from TOML data."""
    scheduler = _require_table(raw_settings, "scheduler")
    des_settings = _require_table(scheduler, "des")
    return DESSimulationSettings(
        entanglement_time_step=_require_positive_number(
            des_settings,
            "entanglement_time_step",
            context="settings.scheduler.des",
        )
    )


def _parse_modality_profiles(
    raw_settings: dict[str, Any],
) -> dict[tuple[str, ...], ModalityProfile]:
    """Parse all modality timing profiles from TOML data."""
    modality_table = _require_table(raw_settings, "modality")
    profiles: dict[tuple[str, ...], ModalityProfile] = {}
    for path, leaf in _iter_leaf_tables(
        modality_table,
        required_keys=("1q_gate_time", "2q_gate_time"),
    ):
        profiles[path] = ModalityProfile(
            path=path,
            one_qubit_gate_time=_require_positive_number(
                leaf,
                "1q_gate_time",
                context=f"settings.modality.{'.'.join(path)}",
            ),
            two_qubit_gate_time=_require_positive_number(
                leaf,
                "2q_gate_time",
                context=f"settings.modality.{'.'.join(path)}",
            ),
        )
    if not profiles:
        raise ValueError("settings.modality must define at least one profile.")
    return profiles


def _parse_entanglement_profiles(
    raw_settings: dict[str, Any],
) -> dict[tuple[str, ...], EntanglementGenerationProfile]:
    """Parse all entanglement-generation profiles from TOML data."""
    entanglement_table = _require_table(raw_settings, "entanglement_gen")
    profiles: dict[tuple[str, ...], EntanglementGenerationProfile] = {}
    for path, leaf in _iter_leaf_tables(
        entanglement_table,
        required_keys=("entanglement_rate", "epr_lifetime"),
    ):
        profiles[path] = EntanglementGenerationProfile(
            path=path,
            entanglement_rate=_require_positive_number(
                leaf,
                "entanglement_rate",
                context=f"settings.entanglement_gen.{'.'.join(path)}",
            ),
            epr_lifetime=_require_positive_number(
                leaf,
                "epr_lifetime",
                context=f"settings.entanglement_gen.{'.'.join(path)}",
            ),
        )
    if not profiles:
        raise ValueError(
            "settings.entanglement_gen must define at least one profile."
        )
    return profiles


def _parse_verification_settings(
    raw_settings: dict[str, Any],
) -> VerificationSettings:
    """Parse verification defaults from TOML data."""
    verification = _require_table(raw_settings, "verification")
    shots = verification.get("shots")
    if isinstance(shots, bool) or not isinstance(shots, int):
        raise ValueError("settings.verification.shots must be an integer.")
    if shots <= 0:
        raise ValueError("settings.verification.shots must be greater than 0.")

    fidelity_threshold = _require_number(
        verification,
        "fidelity_threshold",
        context="settings.verification",
    )
    if not 0.0 <= fidelity_threshold <= 1.0:
        raise ValueError(
            "settings.verification.fidelity_threshold must be between 0 and 1."
        )

    return VerificationSettings(
        shots=shots,
        fidelity_threshold=fidelity_threshold,
    )


def _require_table(
    raw_settings: dict[str, Any],
    key: str,
    *,
    required: bool = True,
) -> dict[str, Any]:
    """Return a nested TOML table by key."""
    value = raw_settings.get(key)
    if value is None:
        if required:
            raise ValueError(f"Missing required settings table: {key!r}.")
        return {}
    if not isinstance(value, dict):
        raise ValueError(f"settings.{key} must be a table.")
    return value


def _iter_leaf_tables(
    table: dict[str, Any],
    *,
    required_keys: tuple[str, ...],
    prefix: tuple[str, ...] = (),
) -> Iterator[tuple[tuple[str, ...], dict[str, Any]]]:
    """Yield nested leaf tables that contain a required key set."""
    has_required_keys = all(key in table for key in required_keys)
    nested_items = [
        (key, value) for key, value in table.items() if isinstance(value, dict)
    ]

    if has_required_keys:
        yield prefix, table
        return

    for key, value in nested_items:
        yield from _iter_leaf_tables(
            value,
            required_keys=required_keys,
            prefix=prefix + (key,),
        )


def _require_number(
    table: dict[str, Any],
    key: str,
    *,
    context: str,
) -> float:
    """Return one numeric TOML field as a float."""
    value = table.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{context}.{key} must be numeric.")
    return float(value)


def _require_positive_number(
    table: dict[str, Any],
    key: str,
    *,
    context: str,
) -> float:
    """Return one positive numeric TOML field as a float."""
    value = _require_number(table, key, context=context)
    if value <= 0.0:
        raise ValueError(f"{context}.{key} must be greater than 0.")
    return value


def _normalize_selector(*path: str) -> tuple[str, ...]:
    """Normalize a selector path from components or one dotted string."""
    if len(path) == 1 and "." in path[0]:
        selector = tuple(
            part.strip() for part in path[0].split(".") if part.strip()
        )
    else:
        selector = tuple(part.strip() for part in path if part.strip())
    if not selector:
        raise ValueError("Selector path cannot be empty.")
    return selector
