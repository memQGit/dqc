# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Partitioning algorithms for interaction and network graphs."""

from typing import TYPE_CHECKING

from .partitioner import Partitioner
from .types import QPU

if TYPE_CHECKING:
    from .cisco import CiscoPartitioner

__all__ = ["CiscoPartitioner", "Partitioner", "QPU"]


def __getattr__(name: str) -> object:  # pragma: no cover
    if name == "CiscoPartitioner":
        from .cisco import CiscoPartitioner

        return CiscoPartitioner
    raise AttributeError(name)
