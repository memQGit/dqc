# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Benchmark random partitioning implementation."""

from __future__ import annotations

import math
import random

from openqasm3 import ast

from memq_dqc.network import NetworkGraph
from memq_dqc.partition.cisco.cisco import (
    _build_schedule,
    _effective_partition_sizes,
)
from memq_dqc.partition.partitioner import QPU, BasePartitioner
from memq_dqc.partition.utils import partition_cost
from memq_dqc.preprocessing.qasm import count_total_qubits
from memq_dqc.utils import create_initial_subcircuit_graph, get_windows


class BenchmarkRandomPartitioner(BasePartitioner):
    """Partition qubits into static, randomly initialized assignments."""

    def __init__(
        self,
        network: NetworkGraph,
        program: ast.Program,
        *,
        window_length: int | None = None,
        seed: int | None = None,
    ) -> None:
        """Initialize the benchmark random partitioner.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
            window_length: Number of two-qubit gates per window.
            seed: Optional RNG seed for reproducible random initialization.
        """
        super().__init__(network, program)
        self.window_length = window_length
        self.seed = seed

    def run(self) -> None:
        """Run the benchmark random partitioning algorithm.

        Updates:
            cost, schedule, and windows with the latest partitioning results.
        """
        num_qubits = count_total_qubits(self.circuit.mono.program)
        partition_sizes = _effective_partition_sizes(
            self.network.comp_qubits_per_qpu(),
            num_qubits,
        )
        circuit = self.circuit
        num_two_qubit_ops = circuit.mono.num_two_qubit_gates
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
        windows = get_windows(circuit, self.window_length)
        if not windows:
            raise ValueError(
                "No operation windows generated from the circuit."
            )
        network_qpu_ids = sorted(
            {qubit.qpu_id for qubit in self.network.qubit_type_map}
        )
        self.windows = windows

        qpus = [QPU(id=qpu_id) for qpu_id in network_qpu_ids]
        random_partition = _build_random_partition(
            partition_sizes,
            num_qubits,
            seed=self.seed,
        )

        def _remote_ebit_multiplier(part_a: int, part_b: int) -> float:
            qpu_a = network_qpu_ids[part_a]
            qpu_b = network_qpu_ids[part_b]
            return float(self.network.remote_gate_ebit_cost(qpu_a, qpu_b))

        total_entanglement_cost = 0.0
        for ops in windows:
            window_graph = create_initial_subcircuit_graph(num_qubits, ops)
            total_entanglement_cost += partition_cost(
                window_graph,
                random_partition,
                edge_cost=_remote_ebit_multiplier,
            )

        self.cost = total_entanglement_cost
        self.schedule = _build_schedule(
            [random_partition] * len(windows),
            qpus,
        )


def _build_random_partition(
    partition_sizes: list[int],
    num_logical_qubits: int,
    *,
    seed: int | None,
) -> list[set[int]]:
    """Build a static partition using random logical-qubit allocation.

    Args:
        partition_sizes: Number of logical qubits assigned to each QPU.
        num_logical_qubits: Number of logical qubits in the input circuit.
        seed: Optional RNG seed for reproducible assignments.

    Returns:
        Partition list where each element is a set of logical qubit indices.

    Raises:
        ValueError: If partition sizes do not cover logical qubits exactly.
    """
    if sum(partition_sizes) != num_logical_qubits:
        raise ValueError(
            "Random partition sizes must match logical qubit count: "
            f"sizes_sum={sum(partition_sizes)}, qubits={num_logical_qubits}."
        )

    logical_qubits = list(range(num_logical_qubits))
    random.Random(seed).shuffle(logical_qubits)

    partition: list[set[int]] = []
    start = 0
    for size in partition_sizes:
        stop = start + size
        partition.append(set(logical_qubits[start:stop]))
        start = stop

    return partition
