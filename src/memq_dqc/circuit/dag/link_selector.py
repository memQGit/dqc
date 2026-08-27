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
    from memq_dqc.network import PhysicalQubit

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

    Balancing is suspended while a cat-entanglement gate group is open. Every
    gate in a group shares one ``catent``/``catdisent`` pair, which is only
    possible if each gate lands on the *same* communication qubits; handing
    consecutive members different equal-cost links would force the group to
    close after its first gate and emit one e-bit pair per remote gate. The
    builder therefore calls :meth:`hold` once a group is open and
    :meth:`release` when it closes, so load is balanced across groups rather
    than across the gates within one.
    """

    def __init__(self) -> None:
        """Initialize an empty per-link usage tally."""
        self._use_counts: dict[tuple[str, str], int] = {}
        self._held_key: tuple[str, str] | None = None
        self._last_key: tuple[str, str] | None = None

    def hold(self) -> None:
        """Pin the most recently selected link until :meth:`release`.

        While pinned, :meth:`select` returns that link whenever it is still
        among the cheapest options. No-op if nothing has been selected yet.
        """
        self._held_key = self._last_key

    def release(self) -> None:
        """Resume balancing across equal-cost links."""
        self._held_key = None

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
        cheapest = [option for option in options if option[0] == min_cost]

        # A pinned link wins outright while it remains among the cheapest, so
        # that an open gate group keeps reusing one catent/catdisent pair. If
        # it is no longer cheapest the pin is simply ignored and the group
        # will close on the mismatch, which is the correct outcome.
        chosen = None
        if self._held_key is not None:
            chosen = next(
                (
                    option
                    for option in cheapest
                    if _link_key(option[1]) == self._held_key
                ),
                None,
            )
        if chosen is None:
            chosen = min(
                cheapest,
                key=lambda option: self._use_counts.get(
                    _link_key(option[1]), 0
                ),
            )

        _, comm_pair, local_paths = chosen
        key = _link_key(comm_pair)
        self._use_counts[key] = self._use_counts.get(key, 0) + 1
        self._last_key = key
        return comm_pair, local_paths
