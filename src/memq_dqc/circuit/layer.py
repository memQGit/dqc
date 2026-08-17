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

"""Layered circuit scheduling structures."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

from memq_dqc.circuit.op import Op


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
