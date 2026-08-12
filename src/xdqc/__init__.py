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

"""Public package interface for xdqc.

This module exposes the core workflow objects and configuration types
needed for distributed quantum compilation. The recommended entry point is
``Compiler`` (compile -> verify) together with ``Scheduler``; ``Compiler``
wraps the lower-level ``Partitioner``, which stays available for callers who
want direct control over partitioning. Supporting helpers remain importable
from their own subpackages (e.g. ``xdqc.network``, ``xdqc.verify``).
"""

from .compiler import (
    Compiler,
    VerificationArtifacts,
    compile_scheduling_instance,
    compute_scheduling_source_fingerprint,
    get_verification_artifacts,
    recompile_scheduling_instance,
)
from .compiler_batch import (
    SchedulingCompileRequest,
    SchedulingCompileResult,
    compile_scheduling_batch,
)
from .partition import Partitioner
from .scheduler import (
    Scheduler,
    SchedulerHardwareProfile,
    SchedulingCompileOptions,
    SchedulingInstance,
    scheduling_instance_from_json,
    scheduling_instance_to_json,
    validate_scheduling_instance,
)
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
    "SchedulerHardwareProfile",
    "SchedulingCompileOptions",
    "SchedulingCompileRequest",
    "SchedulingCompileResult",
    "SchedulingInstance",
    "Settings",
    "VerificationArtifacts",
    "VerificationSettings",
    "compile_scheduling_batch",
    "compile_scheduling_instance",
    "compute_scheduling_source_fingerprint",
    "default_settings_path",
    "get_verification_artifacts",
    "load_settings",
    "load_settings_file",
    "recompile_scheduling_instance",
    "scheduling_instance_from_json",
    "scheduling_instance_to_json",
    "validate_scheduling_instance",
]
