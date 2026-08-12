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

"""Balances equal-cost communication-link choices during DAG construction."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from xdqc.network import PhysicalQubit

_CommPair = tuple["PhysicalQubit", "PhysicalQubit"]
_LocalPaths = tuple[list["PhysicalQubit"], list["PhysicalQubit"]]
_RankedOption = tuple[int, _CommPair, _LocalPaths]


def _link_key(comm_pair: _CommPair) -> tuple[str, str]:
    """Return a stable, order-independent key for a communication link."""
    first, second = sorted((comm_pair[0].label, comm_pair[1].label))
    return first, second


class LinkSelector:
    """Spreads remote gates across equal-cost communication links.

    Remote two-qubit gates often have several communication-qubit pairs
    ("links") tied on cost. Always taking the first would overuse a single
    link, so this selector prefers the least-used link among the cheapest
    options, balancing load deterministically across one distributed build.
    """

    def __init__(self) -> None:
        """Initialize an empty per-link usage tally."""
        self._use_counts: dict[tuple[str, str], int] = {}

    def select(
        self, options: list[_RankedOption]
    ) -> tuple[
        _CommPair,
        _LocalPaths,
    ]:
        """Choose the least-used link among the cheapest options.

        Args:
            options: Non-empty ranked ``(cost, comm_pair, local_paths)``
                entries sorted by increasing cost and deterministic label
                tie-breakers, as returned by
                ``NetworkGraph.get_comm_pair_options`` and already filtered to
                options with valid local paths.

        Returns:
            The chosen ``(comm_pair, local_paths)`` pair.
        """
        min_cost = options[0][0]
        _, comm_pair, local_paths = min(
            (option for option in options if option[0] == min_cost),
            key=lambda option: self._use_counts.get(_link_key(option[1]), 0),
        )
        key = _link_key(comm_pair)
        self._use_counts[key] = self._use_counts.get(key, 0) + 1
        return comm_pair, local_paths
