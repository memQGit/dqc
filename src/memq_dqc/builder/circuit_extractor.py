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

from typing import TYPE_CHECKING

from openqasm3 import ast

from memq_dqc.builder.extract_utils import (
    identify_remote_gates,
    synthesize_state_teleportation_swaps,
)
from memq_dqc.circuit.dag import DistributedCircuitDAG
from memq_dqc.partition import Partitioner

if TYPE_CHECKING:
    from memq_dqc.circuit.dag import CircuitDAG
    from memq_dqc.partition.partitioner import (
        PartitionSchedule,
        PartitionWindows,
    )


def extract_distributed_circuit(partitioner: Partitioner) -> ast.Program:
    """Extract distributed circuit from partitioning assignment.

    Args:
        partitioner: Partitioner with partitioning results.

    Returns:
        Distributed OpenQASM 3 program with remote gate names applied.
    """
    dag, schedule, windows = _validated_partitioner_outputs(partitioner)

    remote_gates = identify_remote_gates(dag, partitioner)
    swap_schedule = synthesize_state_teleportation_swaps(schedule)
    num_swaps = sum(len(timestep_swaps) for timestep_swaps in swap_schedule)
    remote_statement_ids = {op.statement_id for op, _ in remote_gates}
    comp_qubits_per_qpu = partitioner.network.comp_qubits_per_qpu()
    comm_qubits_per_qpu = partitioner.network.comm_qubits_per_qpu()
    num_comm_registers = sum(1 for count in comm_qubits_per_qpu if count > 0)
    # TODO: update DAG to take partitioner object directly for cleaner footprint
    distributed_dag = DistributedCircuitDAG(
        dag,
        remote_statement_ids,
        swap_schedule,
        windows,
        schedule,
        comp_qubits_per_qpu,
        comm_qubits_per_qpu,
    )

    # Number of QPUs should equal number of partitions
    num_qpus = len(schedule[0])

    # TODO: handle any number of input registers (or enforce 1)
    num_qubit_registers = 1

    include_dist_gates = len(remote_gates) > 0 or num_swaps > 0
    # Add statement for each swap and replace one qubit register per QPU.
    expected_statement_count = (
        len(dag.statements)  # TODO: clean this up
        + int(include_dist_gates)
        + num_swaps
        + num_qpus
        + num_comm_registers
        - num_qubit_registers
    )

    assert len(distributed_dag.statements) == expected_statement_count
    return ast.Program(
        version=distributed_dag.program.version,
        statements=[
            statement.node for statement in distributed_dag.statements
        ],
    )


def _validated_partitioner_outputs(
    partitioner: Partitioner,
) -> tuple["CircuitDAG", "PartitionSchedule", "PartitionWindows"]:
    """Validate that partitioning outputs needed for extraction are present."""
    dag = partitioner.dag
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

    return dag, schedule, windows
