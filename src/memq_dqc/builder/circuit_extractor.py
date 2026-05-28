# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Circuit extractor module to create distributed circuit from partitioning.

This module takes a partitioning assignment and an original circuit, and
reconstructs a distributed circuit using remote operations (gate & state
teleportation)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Literal

from openqasm3 import ast

from memq_dqc._logging import StepTimer, workflow_logging
from memq_dqc.builder.extract_utils import (
    identify_gate_groups,
    identify_remote_gates,
    synthesize_state_teleportation_swaps,
)
from memq_dqc.partition import Partitioner
from memq_dqc.preprocessing.qasm.types import CleanedQuantumGate

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from memq_dqc.circuit import Circuit, DistributedCircuit
    from memq_dqc.partition.partitioner import (
        PartitionSchedule,
        PartitionWindows,
    )


def extract_distributed_circuit(
    partitioner: Partitioner,
    *,
    ebit_assignment: bool = True,
    verbosity: Literal["quiet", "info", "debug"] = "quiet",
) -> ast.Program:
    """Extract distributed circuit from partitioning assignment.

    Args:
        partitioner: Partitioner with partitioning results.
        ebit_assignment: Whether the compiler assigns concrete e-bit pairs
            into the scheduler DAG. If false, schedulers choose from viable
            e-bit pair candidates.
        verbosity: Logging verbosity for this workflow call.

    Returns:
        Distributed OpenQASM 3 program with remote gate names applied.
    """
    with workflow_logging(verbosity):
        overall_timer = StepTimer()
        logger.info("Starting distributed circuit extraction.")

        # TODO: MUST DEAL WITH CASE OF ORIGINAL REGISTERS NAMED C
        circuit, schedule, windows = _validated_partitioner_outputs(
            partitioner
        )
        logger.debug(
            "Validated partitioner outputs: schedule_steps=%d windows=%d.",
            len(schedule),
            len(windows),
        )

        remote_analysis_timer = StepTimer()
        remote_gates = identify_remote_gates(circuit, partitioner)
        swap_schedule = synthesize_state_teleportation_swaps(schedule)
        num_swaps = sum(
            len(timestep_swaps) for timestep_swaps in swap_schedule
        )
        logger.debug(
            "Identified %d remote gates and %d synthesized swaps in %.3fs.",
            len(remote_gates),
            num_swaps,
            remote_analysis_timer.elapsed_seconds(),
        )

        _, group_indices, _ = identify_gate_groups(
            circuit, partitioner, verbose=True
        )
        total_grouped_gates = sum(end - start for start, end in group_indices)
        average_group_size = (
            total_grouped_gates / len(group_indices) if group_indices else 0
        )
        remote_statement_ids = {op.statement_id for op, _ in remote_gates}
        comp_qubits_per_qpu = partitioner.network.comp_qubits_per_qpu()
        comm_qubits_per_qpu = partitioner.network.comm_qubits_per_qpu()
        num_comm_registers = (
            sum(1 for count in comm_qubits_per_qpu if count > 0)
            if ebit_assignment
            else 0
        )

        build_timer = StepTimer()
        distributed = circuit.build_distributed(
            remote_statement_ids=remote_statement_ids,
            swaps_schedule=swap_schedule,
            windows=windows,
            schedule=schedule,
            comp_qubits_per_qpu=comp_qubits_per_qpu,
            comm_qubits_per_qpu=comm_qubits_per_qpu,
            network=partitioner.network,
            ebit_assignment=ebit_assignment,
        )
        logger.debug(
            "Built distributed circuit in %.3fs.",
            build_timer.elapsed_seconds(),
        )

        num_qpus = len(schedule[0])
        num_qubit_registers = 1
        local_swaps_added = distributed.num_local_swaps_added
        include_dist_gates = len(remote_gates) > 0 or num_swaps > 0
        expected_statement_count = (
            len(circuit.mono.statements)
            + int(include_dist_gates)
            + num_swaps
            + num_qpus
            + num_comm_registers
            - num_qubit_registers
            + local_swaps_added
        )
        actual_statement_count = len(distributed.statements)
        logger.debug(
            "Distributed statement count: expected_min=%d actual=%d "
            "include_dist_gates=%s local_swaps_added=%d num_qpus=%d "
            "num_comm_registers=%d remote_statement_ids=%d.",
            expected_statement_count,
            actual_statement_count,
            include_dist_gates,
            local_swaps_added,
            num_qpus,
            num_comm_registers,
            len(remote_statement_ids),
        )

        # Routed remote gates may add additional ``rswap`` statements beyond
        # schedule-synthesized swaps.
        # TODO: make this exact and confirm cost calculations
        assert actual_statement_count >= expected_statement_count
        exact_cost = _exact_entanglement_cost(distributed)
        partitioner._algorithm._set_exact_cost(exact_cost)
        logger.info(
            "Distributed circuit extraction completed in %.3fs: "
            "remote_gates=%d swaps=%d statements=%d exact_cost=%.3f "
            "avg_group_size=%.3f.",
            overall_timer.elapsed_seconds(),
            len(remote_gates),
            num_swaps,
            actual_statement_count,
            exact_cost,
            average_group_size,
        )
        return distributed.program


def _validated_partitioner_outputs(
    partitioner: Partitioner,
) -> tuple[Circuit, PartitionSchedule, PartitionWindows]:
    """Validate that partitioning outputs needed for extraction are present."""
    circuit = partitioner.circuit
    schedule = partitioner.schedule
    if schedule is None:
        raise ValueError("partitioner.run() must be called before extraction.")
    if not schedule:
        raise ValueError(
            "partitioner.schedule must contain at least one step."
        )

    windows = partitioner.windows
    if windows is None:
        raise ValueError(
            "partitioner.windows is missing; run partitioner first."
        )

    return circuit, schedule, windows


def _exact_entanglement_cost(distributed: DistributedCircuit) -> float:
    """Return exact entanglement cost from emitted distributed statements.

    Cost model:
        - Remote two-qubit gates (``rcx``, ``rcp``, ``rcry``, ``rcz``) cost
          1 e-bit pair.
        - ``rswap`` costs 2 e-bit pairs.
    """
    # TODO: this needs to be made comprehensive
    remote_gate_names = {"rcx", "rcp", "rcry", "rcz"}
    remote_gate_count = 0
    remote_swap_count = 0
    for statement in distributed.statements:
        if not isinstance(statement, CleanedQuantumGate):
            continue
        if statement.name in remote_gate_names:
            remote_gate_count += 1
        elif statement.name == "rswap":
            remote_swap_count += 1
    return float(remote_gate_count + (2 * remote_swap_count))
