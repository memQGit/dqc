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

"""Utility functions for xdqc.

This module provides utility functions for working with quantum circuits,
graph partitioning, and other common operations throughout the library.
"""

# Circuit utilities
from xdqc.utils.circuit_utils import (
    count_two_qubit_pairs,
    create_initial_subcircuit_graph,
    distribute,
    get_windows,
    movement_cost,
)
from xdqc.utils.common import qubit_partition_map, window_op_map

__all__ = [
    "count_two_qubit_pairs",
    "create_initial_subcircuit_graph",
    "distribute",
    "get_windows",
    "movement_cost",
    "qubit_partition_map",
    "window_op_map",
]
