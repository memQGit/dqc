# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Static interaction-graph partitioning implementation."""

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
from memq_dqc.partition.subroutines import kl_partition
from memq_dqc.partition.utils import partition_cost
from memq_dqc.preprocessing.qasm import count_total_qubits
from memq_dqc.utils import create_initial_subcircuit_graph, get_windows

logger = logging.getLogger(__name__)


class InteractionStaticPartitioner(BasePartitioner):
    """Partition qubits once using the whole-circuit interaction graph."""

    def __init__(
        self,
        network: NetworkGraph,
        program: ast.Program,
        *,
        window_length: int | None = None,
    ) -> None:
        """Initialize the static interaction partitioner.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
            window_length: Number of two-qubit gates per reporting window.
        """
        super().__init__(network, program)
        self.window_length = window_length

    def run(self) -> None:
        """Run static whole-circuit interaction partitioning.

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
            "Interaction-static partitioning parameters: logical_qubits=%d "
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
            "Generated %d reporting windows in %.3fs.",
            len(windows),
            windows_timer.elapsed_seconds(),
        )
        self.windows = windows

        network_qpu_ids = sorted(
            {qubit.qpu_id for qubit in self.network.qubit_type_map}
        )

        def _remote_ebit_multiplier(part_a: int, part_b: int) -> float:
            qpu_a = network_qpu_ids[part_a]
            qpu_b = network_qpu_ids[part_b]
            return float(self.network.remote_gate_ebit_cost(qpu_a, qpu_b))

        graph_timer = StepTimer()
        interaction_graph = create_initial_subcircuit_graph(
            num_qubits,
            circuit.mono.ops,
        )
        logger.debug(
            "Built whole-circuit interaction graph in %.3fs: nodes=%d "
            "edges=%d.",
            graph_timer.elapsed_seconds(),
            interaction_graph.number_of_nodes(),
            interaction_graph.number_of_edges(),
        )

        partition_timer = StepTimer()
        static_partition = kl_partition(
            interaction_graph,
            partitions=partition_sizes,
        )
        reported_cost = partition_cost(
            interaction_graph,
            static_partition,
            edge_cost=_remote_ebit_multiplier,
        )
        logger.debug(
            "Static interaction partition computed in %.3fs with cost=%.3f: "
            "%s.",
            partition_timer.elapsed_seconds(),
            reported_cost,
            static_partition,
        )

        qpus = [QPU(id=qpu_id) for qpu_id in network_qpu_ids]
        schedule_timer = StepTimer()
        self.schedule = _build_schedule(
            [static_partition] * len(windows),
            qpus,
        )
        self.cost = reported_cost
        logger.debug(
            "Built interaction-static schedule with %d windows in %.3fs. "
            "Total cost=%.3f overall_runtime=%.3fs.",
            len(self.schedule),
            schedule_timer.elapsed_seconds(),
            reported_cost,
            overall_timer.elapsed_seconds(),
        )
