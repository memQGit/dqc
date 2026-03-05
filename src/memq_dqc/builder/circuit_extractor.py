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
from memq_dqc.preprocessing.qasm import CleanedQuantumGate

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
    # TODO: MUST DEAL WITH CASE OF ORIGINAL REGISTERS NAMED C (EG CLASSICAL)
    # TODO: figure out cleaner way of abstraction ... probably shouldn't all
    # ... be handled in circuit DAG
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
        partitioner.network,
    )

    # Number of QPUs should equal number of partitions
    num_qpus = len(schedule[0])

    # TODO: handle any number of input registers (or enforce 1)
    num_qubit_registers = 1
    local_swaps_added = distributed_dag.num_local_swaps_added
    include_dist_gates = len(remote_gates) > 0 or num_swaps > 0
    # Add statement for each swap and replace one qubit register per QPU.
    expected_statement_count = (
        len(dag.statements)  # TODO: clean this up
        + int(include_dist_gates)
        + num_swaps
        + num_qpus
        + num_comm_registers
        - num_qubit_registers
        + local_swaps_added
    )

    # Routed remote gates may add additional ``rswap`` statements beyond
    # schedule-synthesized swaps.
    assert len(distributed_dag.statements) >= expected_statement_count
    partitioner._algorithm.cost = _exact_entanglement_cost(distributed_dag)
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


def _exact_entanglement_cost(distributed_dag: DistributedCircuitDAG) -> float:
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
    for statement in distributed_dag.statements:
        if not isinstance(statement, CleanedQuantumGate):
            continue
        if statement.name in remote_gate_names:
            remote_gate_count += 1
        elif statement.name == "rswap":
            remote_swap_count += 1
    return float(remote_gate_count + (2 * remote_swap_count))
