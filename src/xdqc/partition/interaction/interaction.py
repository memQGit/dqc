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

"""Interaction partitioning implementation."""

from __future__ import annotations

import logging
import math

from openqasm3 import ast

# TODO: these imports should be as limited and repeatable as possible
from xdqc._logging import StepTimer
from xdqc.network import NetworkGraph
from xdqc.partition.partitioner import QPU, BasePartitioner
from xdqc.partition.subroutines import kl_partition
from xdqc.partition.utils import partition_cost
from xdqc.preprocessing.qasm import count_total_qubits
from xdqc.utils import (
    create_initial_subcircuit_graph,
    get_windows,
    movement_cost,
    qubit_partition_map,
)
from xdqc.utils.circuit_utils import build_window_interaction_graph

logger = logging.getLogger(__name__)

# Historical default seed for the randomized initial KL partitioning, used when
# no explicit seed is provided so prior behavior is preserved bit-for-bit.
_DEFAULT_KL_SEED = 42


class InteractionPartitioner(BasePartitioner):
    """Partition qubits using the Interaction (TODO: cite) algorithm."""

    # TODO: both state teleportation AND remote gates must account for required rswaps to get there
    def __init__(
        self,
        network: NetworkGraph,
        program: ast.Program,
        *,
        window_length: int | None = None,
        seed: int | None = None,
    ) -> None:
        """Initialize the Interaction partitioner.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
            window_length: Number of two-qubit gates per window.
            seed: Optional seed for the randomized initial partitioning. When
                omitted the historical default seed is used, preserving prior
                behavior.
        """
        super().__init__(network, program, seed=seed)
        self.window_length = window_length

    def run(self) -> None:
        """Run the Interaction partitioning algorithm.

        Updates:
            cost, schedule, and windows with the latest partitioning results.
        """
        overall_timer = StepTimer()
        num_qubits = count_total_qubits(self.circuit.mono.program)
        partition_sizes = _effective_partition_sizes(
            self.network.comp_qubits_per_qpu(),
            num_qubits,
        )
        circuit = self.circuit
        num_two_qubit_ops = circuit.mono.num_two_qubit_gates
        window_length_mode = "provided"
        # Determining optimal window size
        if self.window_length is None:
            window_length_mode = "auto"
            if num_two_qubit_ops == 0:
                self.window_length = 1
            else:
                gate_density = num_two_qubit_ops / max(1, num_qubits)
                # TODO: parameterize this function
                density_scale = max(0.5, min(math.sqrt(gate_density), 2.0))
                base_window = math.sqrt(num_two_qubit_ops) * density_scale
                min_window = 1 if num_two_qubit_ops < 10 else 10
                max_window = min(100, num_two_qubit_ops)
                self.window_length = max(
                    min_window, min(int(round(base_window)), max_window)
                )

        logger.debug(
            "Interaction partitioning parameters: logical_qubits=%d "
            "two_qubit_ops=%d window_length=%d mode=%s partition_sizes=%s.",
            num_qubits,
            num_two_qubit_ops,
            self.window_length,
            window_length_mode,
            partition_sizes,
        )

        windows_timer = StepTimer()
        windows = get_windows(circuit, self.window_length)
        if not windows:
            raise ValueError(
                "No operation windows generated from the circuit."
            )
        logger.debug(
            "Generated %d partition windows in %.3fs.",
            len(windows),
            windows_timer.elapsed_seconds(),
        )
        # QPU IDs must share the ordering of ``partition_sizes`` (both come
        # from the network's processor order) so a partition index maps to
        # the correct QPU when scoring crossing edges below.
        network_qpu_ids = self.network.qpu_ids()
        if len(network_qpu_ids) != len(partition_sizes):
            raise ValueError(
                "Network QPU count does not match partition count: "
                f"{len(network_qpu_ids)} QPUs vs "
                f"{len(partition_sizes)} partitions."
            )

        def _remote_ebit_multiplier(part_a: int, part_b: int) -> float:
            qpu_a = network_qpu_ids[part_a]
            qpu_b = network_qpu_ids[part_b]
            return float(self.network.remote_gate_ebit_cost(qpu_a, qpu_b))

        self.windows = windows
        qpus = [QPU(id=qpu_id) for qpu_id in network_qpu_ids]
        initial_partition_timer = StepTimer()
        initial_subcircuit = create_initial_subcircuit_graph(
            num_qubits, windows[0]
        )
        kl_seed = self.seed if self.seed is not None else _DEFAULT_KL_SEED
        partition_result = kl_partition(
            initial_subcircuit, partitions=partition_sizes, seed=kl_seed
        )

        total_entanglement_cost = partition_cost(
            initial_subcircuit,
            partition_result,
            edge_cost=_remote_ebit_multiplier,
        )
        logger.debug(
            "Initial partition computed in %.3fs with cost=%.3f.",
            initial_partition_timer.elapsed_seconds(),
            total_entanglement_cost,
        )
        window_partitions = [partition_result]

        follow_on_timer = StepTimer()
        for window_idx, ops in enumerate(windows[1:], start=1):
            window_timer = StepTimer()
            previous_partition = window_partitions[-1]
            partition_map = qubit_partition_map(previous_partition)
            window_graph, active_qubits = build_window_interaction_graph(
                ops, partition_map
            )
            if not active_qubits:
                window_partitions.append(previous_partition)
                logger.debug(
                    "Window %d reused previous partition in %.3fs: "
                    "no active qubits.",
                    window_idx,
                    window_timer.elapsed_seconds(),
                )
                continue

            active_partition_sizes = [
                len(partition & active_qubits)
                for partition in previous_partition
            ]
            active_partition = kl_partition(
                window_graph,
                partitions=active_partition_sizes,
                seed=kl_seed,
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
            ) + movement_cost(
                candidate_partition,
                previous_partition,
                network=self.network,
                qpu_ids=network_qpu_ids,
            )
            if candidate_cost <= previous_cost:
                window_partitions.append(candidate_partition)
                total_entanglement_cost += candidate_cost
                decision = "accepted"
            else:
                window_partitions.append(previous_partition)
                total_entanglement_cost += previous_cost
                decision = "reused_previous"

            logger.debug(
                "Window %d processed in %.3fs: active_qubits=%d "
                "previous_cost=%.3f candidate_cost=%.3f decision=%s.",
                window_idx,
                window_timer.elapsed_seconds(),
                len(active_qubits),
                previous_cost,
                candidate_cost,
                decision,
            )

        logger.debug(
            "Processed %d follow-on windows in %.3fs.",
            max(0, len(windows) - 1),
            follow_on_timer.elapsed_seconds(),
        )

        self.cost = total_entanglement_cost
        schedule_timer = StepTimer()
        self.schedule = _build_schedule(window_partitions, qpus)
        logger.debug(
            "Built schedule with %d windows in %.3fs. Total cost=%.3f "
            "overall_runtime=%.3fs.",
            len(self.schedule),
            schedule_timer.elapsed_seconds(),
            total_entanglement_cost,
            overall_timer.elapsed_seconds(),
        )


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
