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

from memq_dqc.circuit.dag import DistributedCircuitDAG
from memq_dqc.qasm.extract.extract_utils import identify_remote_gates
from memq_dqc.qasm.cleaning import CleanedQuantumGate


def extract_distributed_circuit(partitioner):
    """Extract distributed circuit from partitioning assignment.

    Args:
        dag (CircuitDAG): Original circuit DAG.
        program_statements (list[ast.Statement]): Original QASM program statements.
        partitioner (Partitioner): Partitioner with partitioning results.

    Returns:
        Distributed circuit DAG with remote gate names applied.
    """
    dag = partitioner.dag
    remote_gates = identify_remote_gates(dag, partitioner)
    remote_statement_ids = {op.statement_id for op, _ in remote_gates}
    dist_dag = DistributedCircuitDAG(dag, remote_statement_ids)
    count = 0

    for stmt in dist_dag.statements:
        if isinstance(stmt, CleanedQuantumGate):
            if stmt.name[0] == "r":
                print("Remote gate")
                count += 1
    print("remote gate count via remote_gates:", len(remote_gates))
    print("remote gates via statement_ids:", len(remote_statement_ids))
    print("remote gate count via dist_dag:", count)
    print("remote gates via dag attribute", dist_dag.num_remote_gates)
