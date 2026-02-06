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

from openqasm3 import ast

from memq_dqc.circuit.dag import DistributedCircuitDAG
from memq_dqc.partition import Partitioner
from memq_dqc.qasm.extract.extract_utils import (
    identify_remote_gates,
    synthesize_state_teleportation_swaps,
)


def extract_distributed_circuit(partitioner: Partitioner) -> ast.Program:
    """Extract distributed circuit from partitioning assignment.

    Args:
        partitioner: Partitioner with partitioning results.

    Returns:
        Distributed OpenQASM 3 program with remote gate names applied.
    """
    dag = partitioner.dag
    sched = partitioner.schedule
    windows = partitioner.windows
    remote_gates = identify_remote_gates(dag, partitioner)
    swap_sched = synthesize_state_teleportation_swaps(sched)
    num_swaps = sum(len(timestep_swaps) for timestep_swaps in swap_sched)
    remote_statement_ids = {op.statement_id for op, _ in remote_gates}
    # TODO: update DAG to take partitioner object direclty for cleaner footprint
    dist_dag = DistributedCircuitDAG(
        dag, remote_statement_ids, swap_sched, windows, sched
    )

    # Number of QPU's should equal number of partitions
    num_qpu = len(sched[0])

    # TODO: handle any number of input registers (or enforce 1)
    num_qbit_regs = 1

    include_dist_gates = 1 if len(remote_gates) > 0 else 0
    # Add statement for each swap, replace 1 qubit register w/ one per qpu
    assert (
        len(dist_dag.statements)
        == len(dag.statements)
        + include_dist_gates
        + num_swaps
        + num_qpu
        - num_qbit_regs
    )
    return ast.Program(
        version=dist_dag.program.version,
        statements=[statement.node for statement in dist_dag.statements],
    )
