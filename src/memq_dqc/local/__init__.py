# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Local compilation passes."""

from .local_pass import local_transpile

__all__ = [
    # TODO: change name to compile
    "local_transpile",
]
