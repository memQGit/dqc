# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Layered circuit scheduling structures."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from xdqc.circuit.op import Op


@dataclass(frozen=True, slots=True)
class Layer(Sequence[Op]):
    """A layer of operations that can be executed in parallel.

    Attributes:
        ops: Operations contained in the layer, in scheduling order.
    """

    ops: tuple[Op, ...]

    def __iter__(self) -> Iterator[Op]:
        """Return an iterator over operations in the layer."""
        return iter(self.ops)

    def __len__(self) -> int:
        """Return the number of operations in the layer."""
        return len(self.ops)

    def __getitem__(self, index: int) -> Op:
        """Return the operation at a given index."""
        return self.ops[index]

    @property
    def qubits(self) -> list[int]:
        """Return the sorted unique qubits used by the layer.

        Returns:
            Sorted unique qubit indices used by operations in the layer.
        """
        return sorted({q for op in self.ops for q in op.qubit_indices})
