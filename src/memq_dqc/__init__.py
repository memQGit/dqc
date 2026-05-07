# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Public package interface for memq-dqc.

This module provides a small, stable surface for imports and package
metadata.
"""

from .settings import (
    DESSimulationSettings,
    EntanglementGenerationProfile,
    GlobalSettings,
    ModalityProfile,
    Settings,
    VerificationSettings,
    default_settings_path,
    load_settings,
    load_settings_file,
)


def hello() -> str:
    """Return a simple greeting used for sanity checks.

    Returns:
        A friendly greeting string.
    """
    # TODO: update this
    return "Hello from memq-dqc!"


__all__ = [
    "DESSimulationSettings",
    "EntanglementGenerationProfile",
    "GlobalSettings",
    "ModalityProfile",
    "Settings",
    "VerificationSettings",
    "default_settings_path",
    "hello",
    "load_settings",
    "load_settings_file",
]
