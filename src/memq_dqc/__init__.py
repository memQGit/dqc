# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Public package interface for memq-dqc.

This module exposes the core workflow objects and configuration types
needed for distributed quantum compilation. The recommended entry point is
``Compiler`` (compile -> verify) together with ``Scheduler``; ``Compiler``
wraps the lower-level ``Partitioner``, which stays available for callers who
want direct control over partitioning. Supporting helpers remain importable
from their own subpackages (e.g. ``memq_dqc.network``, ``memq_dqc.verify``).
"""

from .compiler import Compiler
from .partition import Partitioner
from .scheduler import Scheduler
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

__all__ = [
    "Compiler",
    "DESSimulationSettings",
    "EntanglementGenerationProfile",
    "GlobalSettings",
    "ModalityProfile",
    "Partitioner",
    "Scheduler",
    "Settings",
    "VerificationSettings",
    "default_settings_path",
    "load_settings",
    "load_settings_file",
]
