# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Hypergraph partitioning implementation built from grouped gates."""

from __future__ import annotations

import importlib
import logging
from collections import Counter
from collections.abc import Mapping
from os import PathLike
from pathlib import Path
from typing import Any

from openqasm3 import ast

from memq_dqc._logging import StepTimer
from memq_dqc.circuit.op import Op
from memq_dqc.network import NetworkGraph
from memq_dqc.partition.partitioner import QPU, BasePartitioner
from memq_dqc.preprocessing.qasm import count_total_qubits
from memq_dqc.utils import get_windows

logger = logging.getLogger(__name__)

DEFAULT_KAHYPAR_CONFIG = "kahypar_config.ini"
DIAGONAL_GATES = {
    "id",
    "p",
    "phase",
    "z",
    "s",
    "sdg",
    "t",
    "tdg",
    "rz",
    "u1",
}
ANTIDIAGONAL_GATES = {"x", "y"}
REVERSIBLE_TARGET_TWO_QUBIT_GATES = {"cz"}

PacketCounter = Counter[tuple[str, ...]]


class HypergraphPartitioner(BasePartitioner):
    """Partition qubits once using a grouped-gate hypergraph."""

    def __init__(
        self,
        network: NetworkGraph,
        program: ast.Program,
        *,
        config_path: str | PathLike[str] | None = None,
        epsilon: float = 0.03,
        max_group_size: int | None = None,
        window_length: int | None = None,
    ) -> None:
        """Initialize the hypergraph partitioner.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
            config_path: Optional KahyPar INI configuration path. When
                omitted, the packaged hypergraph configuration is used.
            epsilon: Allowed KahyPar partition imbalance.
            max_group_size: Optional maximum two-qubit gates per group.
            window_length: Optional window length used only to adapt the
                static assignment to the existing schedule interface.
        """
        super().__init__(network, program)
        self.config_path = config_path
        self.epsilon = epsilon
        self.max_group_size = max_group_size
        self.window_length = window_length

    def run(self) -> None:
        """Run grouped-gate hypergraph partitioning.

        Updates:
            cost, schedule, and windows with the latest partitioning results.
        """
        timer = StepTimer()
        num_qubits = count_total_qubits(self.circuit.mono.program)
        qpu_ids = _network_qpu_ids(self.network)
        qpu_capacities = dict(
            zip(qpu_ids, self.network.comp_qubits_per_qpu(), strict=True)
        )

        gate_packets = build_gate_packets(
            self.circuit.mono.ops,
            max_size=self.max_group_size,
        )
        packet_counter = packets_to_hypergraph(gate_packets)
        partition_result = partition_hypergraph(
            packet_counter,
            k=len(qpu_ids),
            config_path=resolve_kahypar_config_path(self.config_path),
            epsilon=self.epsilon,
        )
        assignment = partition_result_to_assignment(partition_result, qpu_ids)
        _assign_missing_qubits(
            assignment,
            logical_qubits=set(range(num_qubits)),
            qpu_capacities=qpu_capacities,
        )
        _validate_assignment(
            assignment,
            logical_qubits=set(range(num_qubits)),
            qpu_capacities=qpu_capacities,
        )

        if self.window_length is None:
            self.windows = [self.circuit.mono.ops]
        else:
            self.windows = get_windows(self.circuit, self.window_length)
        if not self.windows:
            raise ValueError(
                "No operation windows generated from the circuit."
            )
        self.schedule = [
            {QPU(id=qpu_id): set(assignment[qpu_id]) for qpu_id in qpu_ids}
            for _ in self.windows
        ]
        self.cost = 0.0
        logger.debug(
            "Hypergraph partitioning completed in %.3fs: groups=%d "
            "hyperedges=%d qpus=%d.",
            timer.elapsed_seconds(),
            len(gate_packets),
            len(packet_counter),
            len(qpu_ids),
        )


def build_gate_packets(
    ops: list[Op],
    *,
    max_size: int | None = None,
) -> list[list[set[int]]]:
    """Group operations into packets of logical qubit sets.

    Args:
        ops: Circuit operations in program order.
        max_size: Optional maximum two-qubit gates per group.

    Returns:
        Gate packets where each packet is a list of operation qubit sets.
    """
    packets: list[list[set[int]]] = []
    idx = 0
    while idx < len(ops):
        op = ops[idx]
        if op.is_two_qubit:
            control, target = _control_and_target(op)
            group_ops, ignored_ops = _search_for_group_gate(
                ops,
                idx + 1,
                control,
                target,
                max_size=max_size,
            )
            packets.append(
                [set(group_op.qubit_indices) for group_op in group_ops]
            )
            idx += len(group_ops) + len(ignored_ops)
        else:
            idx += 1

    return packets


def packets_to_hypergraph(packets: list[list[set[int]]]) -> PacketCounter:
    """Convert grouped gate packets into weighted hyperedges.

    Args:
        packets: Gate packets from grouped operations.

    Returns:
        Hyperedge counts keyed by sorted stringified logical qubit IDs.
    """
    packet_counter: PacketCounter = Counter()
    for packet in packets:
        packet_qubits = sorted(set().union(*packet))
        packet_counter[tuple(str(qubit) for qubit in packet_qubits)] += 1
    return packet_counter


def partition_hypergraph(
    packet_counter: PacketCounter,
    *,
    k: int,
    config_path: str | PathLike[str],
    epsilon: float = 0.03,
) -> dict[str, int]:
    """Partition hypergraph nodes with KahyPar.

    Args:
        packet_counter: Hyperedges and their weights.
        k: Number of partitions.
        config_path: KahyPar INI configuration path.
        epsilon: Allowed KahyPar partition imbalance.

    Returns:
        Mapping from logical qubit string IDs to partition block IDs.

    Raises:
        ImportError: If KahyPar is not installed.
    """
    if not packet_counter:
        return {}

    try:
        kahypar: Any = importlib.import_module("kahypar")
    except ImportError as exc:
        raise ImportError(
            "The hypergraph partitioner requires the 'kahypar' package to run."
        ) from exc

    edges, edge_weights = zip(*packet_counter.items(), strict=True)
    nodes = {
        node: idx
        for idx, node in enumerate(
            sorted({node for edge in edges for node in edge})
        )
    }
    hyperedges = [nodes[node] for edge in edges for node in edge]
    hyperedge_indices = [0]
    for edge in edges:
        hyperedge_indices.append(hyperedge_indices[-1] + len(edge))

    hypergraph = kahypar.Hypergraph(
        len(nodes),
        len(edges),
        hyperedge_indices,
        hyperedges,
        k,
        list(edge_weights),
        [1] * len(nodes),
    )
    context = kahypar.Context()
    context.loadINIconfiguration(str(config_path))
    context.setK(k)
    context.setEpsilon(epsilon)
    context.suppressOutput(True)
    kahypar.partition(hypergraph, context)

    return {node: int(hypergraph.blockID(idx)) for node, idx in nodes.items()}


def resolve_kahypar_config_path(
    config_path: str | PathLike[str] | None = None,
) -> Path:
    """Return the explicit or packaged KahyPar configuration path.

    Args:
        config_path: Optional caller-provided KahyPar INI path.

    Returns:
        Resolved KahyPar configuration path.
    """
    if config_path is not None:
        return Path(config_path)
    return Path(__file__).with_name(DEFAULT_KAHYPAR_CONFIG)


def partition_result_to_assignment(
    partition_result: Mapping[str, int],
    qpu_ids: list[int],
) -> dict[int, set[int]]:
    """Convert KahyPar node assignments into QPU-keyed qubit sets.

    Args:
        partition_result: Mapping from logical qubit string ID to block ID.
        qpu_ids: Network QPU IDs ordered by partition block.

    Returns:
        Mapping from network QPU ID to logical qubit indices.

    Raises:
        ValueError: If a partition block or qubit ID is invalid.
    """
    assignment = {qpu_id: set[int]() for qpu_id in qpu_ids}
    for node, block_id in partition_result.items():
        if block_id < 0 or block_id >= len(qpu_ids):
            raise ValueError(
                f"Partition block {block_id} is outside 0..{len(qpu_ids) - 1}."
            )
        if not node.isdigit():
            raise ValueError(f"Logical qubit ID must be numeric: {node!r}.")
        assignment[qpu_ids[block_id]].add(int(node))
    return assignment


def _search_for_group_gate(
    ops: list[Op],
    start_index: int,
    control: int,
    target: int,
    *,
    max_size: int | None,
) -> tuple[list[Op], list[Op]]:
    group_ops = [ops[start_index - 1]]
    ignored_ops: list[Op] = []
    targets = {target}
    group_two_qubit_count = 1
    pending_one_qubit_ops: list[Op] = []

    for offset, op in enumerate(ops[start_index:]):
        if op.is_two_qubit:
            op_control, op_target = _control_and_target(op)
            if _shares_group_control(op, op_control, op_target, control):
                if max_size is not None and group_two_qubit_count >= max_size:
                    ignored_ops.extend(pending_one_qubit_ops)
                    return group_ops, ignored_ops
                group_ops.extend(pending_one_qubit_ops)
                pending_one_qubit_ops = []
                group_ops.append(op)
                group_two_qubit_count += 1
                targets.add(op_target)
                continue

            return _try_commute_later_gate(
                ops,
                start_index,
                offset,
                op,
                control,
                group_ops,
                pending_one_qubit_ops,
                group_two_qubit_count,
                max_size,
            )

        if len(op.qubits) == 1:
            qubit = op.qubit_indices[0]
            if qubit == control:
                if op.name in DIAGONAL_GATES.union(ANTIDIAGONAL_GATES):
                    pending_one_qubit_ops.append(op)
                else:
                    ignored_ops.extend(pending_one_qubit_ops)
                    return group_ops, ignored_ops
            elif qubit in targets:
                pending_one_qubit_ops.append(op)
            else:
                ignored_ops.append(op)

    ignored_ops.extend(pending_one_qubit_ops)
    return group_ops, ignored_ops


def _try_commute_later_gate(
    ops: list[Op],
    start_index: int,
    offset: int,
    terminating_op: Op,
    control: int,
    group_ops: list[Op],
    pending_one_qubit_ops: list[Op],
    group_two_qubit_count: int,
    max_size: int | None,
) -> tuple[list[Op], list[Op]]:
    ignored_ops: list[Op] = []
    one_qubit_ops_between: list[Op] = []
    for next_op in ops[start_index + offset + 1 :]:
        if len(next_op.qubits) == 1:
            one_qubit_ops_between.append(next_op)
            continue
        if not next_op.is_two_qubit:
            continue

        next_control, next_target = _control_and_target(next_op)
        blocking_one_qubit_ops = [
            op
            for op in one_qubit_ops_between
            if not _ops_disjoint(next_op, op)
        ]
        if (
            _ops_disjoint(terminating_op, next_op)
            and _shares_group_control(
                next_op,
                next_control,
                next_target,
                control,
            )
            and not blocking_one_qubit_ops
            and (max_size is None or group_two_qubit_count < max_size)
        ):
            group_ops.extend(pending_one_qubit_ops)
            group_ops.append(next_op)
            ignored_ops.extend([terminating_op, *one_qubit_ops_between])
        else:
            ignored_ops.extend(pending_one_qubit_ops)
        return group_ops, ignored_ops

    ignored_ops.extend(pending_one_qubit_ops)
    return group_ops, ignored_ops


def _assign_missing_qubits(
    assignment: dict[int, set[int]],
    *,
    logical_qubits: set[int],
    qpu_capacities: Mapping[int, int],
) -> None:
    assigned = set().union(*assignment.values()) if assignment else set()
    missing_qubits = sorted(logical_qubits - assigned)

    for logical_qubit in missing_qubits:
        for qpu_id in sorted(assignment):
            if len(assignment[qpu_id]) < qpu_capacities[qpu_id]:
                assignment[qpu_id].add(logical_qubit)
                break
        else:
            raise ValueError(
                "Insufficient computation-qubit capacity in network: "
                f"unassigned logical qubit {logical_qubit}."
            )


def _validate_assignment(
    assignment: Mapping[int, set[int]],
    *,
    logical_qubits: set[int],
    qpu_capacities: Mapping[int, int],
) -> None:
    seen: set[int] = set()
    for qpu_id, qubits in assignment.items():
        if len(qubits) > qpu_capacities[qpu_id]:
            raise ValueError(
                "Hypergraph partition exceeds QPU computation capacity: "
                f"qpu={qpu_id}, assigned={len(qubits)}, "
                f"capacity={qpu_capacities[qpu_id]}."
            )
        duplicates = seen & qubits
        if duplicates:
            raise ValueError(
                "Logical qubits assigned to multiple QPUs: "
                f"{sorted(duplicates)}."
            )
        seen.update(qubits)

    if seen != logical_qubits:
        raise ValueError(
            "Hypergraph partition must assign every logical qubit exactly "
            f"once: missing={sorted(logical_qubits - seen)}, "
            f"extra={sorted(seen - logical_qubits)}."
        )


def _control_and_target(op: Op) -> tuple[int, int]:
    return op.qubit_indices[0], op.qubit_indices[1]


def _get_op_qubits(op: Op) -> set[int]:
    return set(op.qubit_indices)


def _ops_disjoint(left: Op, right: Op) -> bool:
    return _get_op_qubits(left).isdisjoint(_get_op_qubits(right))


def _shares_group_control(
    op: Op,
    op_control: int,
    op_target: int,
    group_control: int,
) -> bool:
    return op_control == group_control or (
        op_target == group_control
        and op.name in REVERSIBLE_TARGET_TWO_QUBIT_GATES
    )


def _network_qpu_ids(network: NetworkGraph) -> list[int]:
    return sorted({qubit.qpu_id for qubit in network.qubit_type_map})
