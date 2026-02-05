# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Utility functions for circuit extraction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from memq_dqc.utils.common import qubit_partition_map, window_op_map

if TYPE_CHECKING:
    from memq_dqc.circuit import CircuitDAG, Op
    from memq_dqc.partition import Partitioner


def identify_state_tele_ops(
    schedule: list[list[set[int]]],
) -> list[dict[int, tuple[int, int]]]:
    """Identify state teleportation operations in the schedule.

    Args:
        schedule: A list of time steps, each containing a list of sets of logical
            qubits assigned to each QPU.

    Returns:
        A list of dictionaries mapping logical qubits to a tuple of (source QPU,
        destination QPU) for each state teleportation operation in each time step,
        starting with the 2nd time step.
    """
    tele_ops_per_timestep: list[dict[int, tuple[int, int]]] = []
    for t in range(1, len(schedule)):
        tele_ops: dict[int, tuple[int, int]] = {}
        prev_assignment = schedule[t - 1]
        curr_assignment = schedule[t]
        for qpu_idx_src, src_qubits in enumerate(prev_assignment):
            for qpu_idx_dst, dst_qubits in enumerate(curr_assignment):
                if qpu_idx_src == qpu_idx_dst:
                    continue
                teleported_qubits = src_qubits.intersection(dst_qubits)
                for logical_qubit in teleported_qubits:
                    tele_ops[logical_qubit] = (qpu_idx_src, qpu_idx_dst)
        tele_ops_per_timestep.append(tele_ops)
    return tele_ops_per_timestep


def identify_remote_gates(
    circuit_dag: CircuitDAG,
    partition: Partitioner,
) -> list[tuple[Op, dict[str, int]]]:
    """Identify remote gates in the scheduled circuit.

    Args:
        circuit_dag: The CircuitDAG representing the quantum circuit.
        partition: The Partitioner object containing the partitioning schedule.

    Returns:
        Augmented list of operations with two-qubit gates replaced with remote
        variants where applicable.
    """
    ops = circuit_dag.ops
    windows = partition.windows
    window_op_mapping = window_op_map(circuit_dag, windows)
    schedule = partition.schedule

    remote_gates: list[tuple[Op, dict[str, int]]] = []
    for op in ops:
        if len(op.qubits) == 1:
            continue
        if len(op.qubits) > 2:
            raise ValueError(
                "Only single- and two-qubit gates are supported currently."
            )
        q1, q2 = op.qubits
        op_window_idx = window_op_mapping[op.op_id]
        qubit_map = qubit_partition_map(schedule[op_window_idx])
        q1_qpu = qubit_map[q1.index]
        q2_qpu = qubit_map[q2.index]
        if q1_qpu == q2_qpu:
            continue
        # TODO: theres probably a cleaner, more efficient way to do this
        remote_gates.append((op, {"q1_qpu": q1_qpu, "q2_qpu": q2_qpu}))
    print(
        f"Identified {len(remote_gates)} remote gates. {len(ops)} total gates."
    )
    return remote_gates
