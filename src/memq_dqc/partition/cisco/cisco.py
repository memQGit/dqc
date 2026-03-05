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

from memq_dqc.graph import NetworkGraph
from memq_dqc.partition.algos import kl_partition
from memq_dqc.partition.partitioner import QPU, BasePartitioner
from memq_dqc.partition.utils import partition_cost
from memq_dqc.preprocessing.qasm import count_total_qubits
from memq_dqc.utils import (
    create_initial_subcircuit_graph,
    get_windows,
    movement_cost,
    qubit_partition_map,
)
from memq_dqc.utils.circuit_utils import build_window_interaction_graph


class CiscoPartitioner(BasePartitioner):
    """Partition qubits using the Cisco (TODO: cite) algorithm."""

    # TODO: both state teleportation AND remote gates must account for required rswaps to get there
    def __init__(
        self,
        network: NetworkGraph,
        program: ast.Program,
        *,
        window_length: int | None = None,
    ) -> None:
        """Initialize the Cisco partitioner.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
            window_length: Number of two-qubit gates per window.
        """
        super().__init__(network, program)
        self.window_length = window_length

    def run(self) -> None:
        """Run the Cisco partitioning algorithm.

        Updates:
            cost, schedule, and windows with the latest partitioning results.
        """
        num_qubits = count_total_qubits(self.program)
        partition_sizes = _effective_partition_sizes(
            self.network.comp_qubits_per_qpu(),
            num_qubits,
        )
        dag = self.dag
        num_two_qubit_ops = dag.num_two_qubit_gates
        # Determining optimal window size
        if self.window_length is None:
            if num_two_qubit_ops == 0:
                self.window_length = 1
            else:
                gate_density = num_two_qubit_ops / max(1, num_qubits)
                density_scale = max(0.5, min(math.sqrt(gate_density), 2.0))
                base_window = math.sqrt(num_two_qubit_ops) * density_scale
                min_window = 1 if num_two_qubit_ops < 10 else 10
                max_window = min(100, num_two_qubit_ops)
                self.window_length = max(
                    min_window, min(int(round(base_window)), max_window)
                )
        windows = get_windows(dag, self.window_length)
        if not windows:
            raise ValueError(
                "No operation windows generated from the circuit."
            )
        network_qpu_ids = sorted(
            {qubit.qpu_id for qubit in self.network.qubit_type_map}
        )

        def _remote_ebit_multiplier(part_a: int, part_b: int) -> float:
            # TODO: go through this - relied on codex refactor for time crunch
            # TODO: remove redunancy, and no nested functions
            qpu_a = network_qpu_ids[part_a]
            qpu_b = network_qpu_ids[part_b]
            return float(self.network.remote_gate_ebit_cost(qpu_a, qpu_b))

        self.windows = windows
        qpus = [QPU(id=idx) for idx in range(len(partition_sizes))]
        initial_subcircuit = create_initial_subcircuit_graph(
            num_qubits, windows[0]
        )
        partition_result = kl_partition(
            initial_subcircuit, partitions=partition_sizes
        )

        total_entanglement_cost = partition_cost(
            initial_subcircuit,
            partition_result,
            # TODO: go through this - relied on codex refactor for time crunch
            edge_cost=_remote_ebit_multiplier,
        )
        window_partitions = [partition_result]

        for ops in windows[1:]:
            previous_partition = window_partitions[-1]
            partition_map = qubit_partition_map(previous_partition)
            window_graph, active_qubits = build_window_interaction_graph(
                ops, partition_map
            )
            if not active_qubits:
                window_partitions.append(previous_partition)
                continue

            active_partition_sizes = [
                len(partition & active_qubits)
                for partition in previous_partition
            ]
            active_partition = kl_partition(
                window_graph, partitions=active_partition_sizes
            )
            candidate_partition = _merge_partitions_with_active(
                previous_partition, active_partition, active_qubits
            )

            previous_cost = partition_cost(
                window_graph,
                previous_partition,
                edge_cost=_remote_ebit_multiplier,
            )
            candidate_cost = partition_cost(
                window_graph,
                candidate_partition,
                edge_cost=_remote_ebit_multiplier,
            ) + movement_cost(candidate_partition, previous_partition)
            if candidate_cost <= previous_cost:
                window_partitions.append(candidate_partition)
                total_entanglement_cost += candidate_cost
            else:
                window_partitions.append(previous_partition)
                total_entanglement_cost += previous_cost

        self.cost = total_entanglement_cost
        self.schedule = _build_schedule(window_partitions, qpus)


def _effective_partition_sizes(
    qpu_comp_capacities: list[int],
    num_logical_qubits: int,
) -> list[int]:
    """Build partition sizes that fit logical qubits within QPU capacities.

    Args:
        qpu_comp_capacities: Available computation-qubit capacities per QPU.
        num_logical_qubits: Number of logical qubits in the input circuit.

    Returns:
        Effective partition sizes for logical-qubit partitioning.

    Raises:
        ValueError: If network capacity is insufficient for logical qubits.
    """
    total_capacity = sum(qpu_comp_capacities)
    if total_capacity < num_logical_qubits:
        raise ValueError(
            "Insufficient computation-qubit capacity in network: "
            f"required={num_logical_qubits}, available={total_capacity}."
        )
    if total_capacity == num_logical_qubits:
        return list(qpu_comp_capacities)

    effective_sizes = list(qpu_comp_capacities)
    excess = total_capacity - num_logical_qubits
    for idx in reversed(range(len(effective_sizes))):
        if excess == 0:
            break
        removable = min(effective_sizes[idx], excess)
        effective_sizes[idx] -= removable
        excess -= removable

    return effective_sizes


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


def _build_schedule(
    partitions: list[list[set[int]]],
    qpus: list[QPU],
) -> list[dict[QPU, set[int]]]:
    """Convert partitions to a schedule keyed by QPU objects."""
    return [
        {qpu: set(part) for qpu, part in zip(qpus, partition, strict=True)}
        for partition in partitions
    ]
