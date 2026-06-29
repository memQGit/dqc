# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Benchmark static partitioning implementation."""

from __future__ import annotations

import logging
import math

from openqasm3 import ast

from memq_dqc._logging import StepTimer
from memq_dqc.network import NetworkGraph
from memq_dqc.partition.interaction.interaction import (
    _build_schedule,
    _effective_partition_sizes,
)
from memq_dqc.partition.partitioner import QPU, BasePartitioner
from memq_dqc.partition.utils import partition_cost
from memq_dqc.preprocessing.qasm import count_total_qubits
from memq_dqc.utils import create_initial_subcircuit_graph, get_windows

logger = logging.getLogger(__name__)


class BenchmarkStaticPartitioner(BasePartitioner):
    """Partition qubits into static, capacity-bounded QPU assignments."""

    def __init__(
        self,
        network: NetworkGraph,
        program: ast.Program,
        *,
        window_length: int | None = None,
    ) -> None:
        """Initialize the benchmark static partitioner.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
            window_length: Number of two-qubit gates per window.
        """
        super().__init__(network, program)
        self.window_length = window_length

    def run(self) -> None:
        """Run the benchmark static partitioning algorithm.

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
        if self.window_length is None:
            window_length_mode = "auto"
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
        logger.debug(
            "Benchmark static partitioning parameters: logical_qubits=%d "
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
        network_qpu_ids = sorted(
            {qubit.qpu_id for qubit in self.network.qubit_type_map}
        )
        self.windows = windows

        qpus = [QPU(id=qpu_id) for qpu_id in network_qpu_ids]
        static_partition = _build_static_partition(partition_sizes, num_qubits)
        logger.debug("Static partition assignment: %s.", static_partition)

        def _remote_ebit_multiplier(part_a: int, part_b: int) -> float:
            qpu_a = network_qpu_ids[part_a]
            qpu_b = network_qpu_ids[part_b]
            return float(self.network.remote_gate_ebit_cost(qpu_a, qpu_b))

        total_entanglement_cost = 0.0
        for window_idx, ops in enumerate(windows):
            window_timer = StepTimer()
            window_graph = create_initial_subcircuit_graph(num_qubits, ops)
            window_cost = partition_cost(
                window_graph,
                static_partition,
                edge_cost=_remote_ebit_multiplier,
            )
            total_entanglement_cost += window_cost
            logger.debug(
                "Window %d processed in %.3fs with cost=%.3f.",
                window_idx,
                window_timer.elapsed_seconds(),
                window_cost,
            )

        self.cost = total_entanglement_cost
        schedule_timer = StepTimer()
        self.schedule = _build_schedule(
            [static_partition] * len(windows),
            qpus,
        )
        logger.debug(
            "Built static schedule with %d windows in %.3fs. "
            "Total cost=%.3f overall_runtime=%.3fs.",
            len(self.schedule),
            schedule_timer.elapsed_seconds(),
            total_entanglement_cost,
            overall_timer.elapsed_seconds(),
        )


def _build_static_partition(
    partition_sizes: list[int],
    num_logical_qubits: int,
) -> list[set[int]]:
    """Build a static partition using sequential logical-qubit allocation.

    Args:
        partition_sizes: Number of logical qubits assigned to each QPU.
        num_logical_qubits: Number of logical qubits in the input circuit.

    Returns:
        Partition list where each element is a set of logical qubit indices.

    Raises:
        ValueError: If partition sizes do not cover logical qubits exactly.
    """
    partition: list[set[int]] = []
    next_qubit = 0

    for size in partition_sizes:
        partition.append(set(range(next_qubit, next_qubit + size)))
        next_qubit += size

    if next_qubit != num_logical_qubits:
        raise ValueError(
            "Static partition sizes must match logical qubit count: "
            f"sizes_sum={next_qubit}, qubits={num_logical_qubits}."
        )

    return partition
