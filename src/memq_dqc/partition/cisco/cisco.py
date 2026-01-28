# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Cisco-style partitioning implementation."""

from __future__ import annotations

import math

from openqasm3 import ast

from memq_dqc.circuit import CircuitDAG
from memq_dqc.graph import NetworkGraph
from memq_dqc.partition.algos import kl_partition
from memq_dqc.partition.partitioner import BasePartitioner, PartitionResult
from memq_dqc.utils import (
    count_total_qubits,
    create_initial_subcircuit_graph,
    get_windows,
    movement_cost,
    partition_cost,
    qubit_partition_set_to_map,
)
from memq_dqc.utils.circuit_utils import build_window_interaction_graph


class CiscoPartitioner(BasePartitioner):
    """Partition qubits using the Cisco (TODO: cite) algorithm."""

    def __init__(
        self,
        network: NetworkGraph,
        program: ast.Program,
        *,
        window_length: int = None,
    ) -> None:
        """Initialize the Cisco partitioner.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
            window_length: Number of two-qubit gates per window.
        """
        super().__init__(network, program)
        self.window_length = window_length

    def run(self) -> PartitionResult:
        """Run the Cisco partitioning algorithm.

        Returns:
            The entanglement cost and partition schedule.
        """
        num_qubits = count_total_qubits(self.program)
        partition_sizes = self.network.comp_qubits_per_qpu()
        dag = CircuitDAG(self.program)
        num_2q_ops = dag.num_two_qubit_gates
        # Determining optimal window size
        if self.window_length is None:
            if num_2q_ops == 0:
                self.window_length = 1
            else:
                gate_density = num_2q_ops / max(1, num_qubits)
                density_scale = max(0.5, min(math.sqrt(gate_density), 2.0))
                base_window = math.sqrt(num_2q_ops) * density_scale
                min_window = 1 if num_2q_ops < 10 else 10
                max_window = min(100, num_2q_ops)
                self.window_length = max(
                    min_window, min(int(round(base_window)), max_window)
                )
        windows = get_windows(dag, self.window_length)
        if not windows:
            print("No operations in circuit; returning trivial partition.")
            return 0.0, [set(range(num_qubits))]
        initial_subcircuit = create_initial_subcircuit_graph(
            num_qubits, windows[0]
        )
        partition_result = kl_partition(
            initial_subcircuit, partitions=partition_sizes
        )

        total_entanglement_cost = partition_cost(
            initial_subcircuit, partition_result
        )
        window_partitions = [partition_result]

        idx = 0
        for ops in windows[1:]:
            p_old = window_partitions[-1]
            partition_map = qubit_partition_set_to_map(p_old)
            g, active_qubits = build_window_interaction_graph(
                ops, partition_map
            )
            if not active_qubits:
                window_partitions.append(p_old)
                continue

            new_partition_sizes = [len(p & active_qubits) for p in p_old]
            p_new_active = kl_partition(g, partitions=new_partition_sizes)
            p_new = _merge_partitions_with_active(
                p_old, p_new_active, active_qubits
            )

            old_cost = partition_cost(g, p_old)
            new_cost = partition_cost(g, p_new) + movement_cost(p_new, p_old)
            if new_cost <= old_cost:
                window_partitions.append(p_new)
                total_entanglement_cost += new_cost
            else:
                window_partitions.append(p_old)
                total_entanglement_cost += old_cost
            idx += 1

        return total_entanglement_cost, window_partitions


def _merge_partitions_with_active(
    p_old: list[set[int]],
    p_new_active: list[set[int]],
    active_qubits: set[int],
) -> list[set[int]]:
    """Merge active-qubit partitions into the previous full partition."""
    p_new = [set(p) for p in p_old]
    for idx in range(len(p_new)):
        p_new[idx] -= active_qubits
    for idx, part in enumerate(p_new_active):
        p_new[idx].update(part)
    return p_new
