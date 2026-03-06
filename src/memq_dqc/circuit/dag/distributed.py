# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Distributed DAG representation and statement-building orchestration."""

from __future__ import annotations

from typing import TYPE_CHECKING

from openqasm3 import ast

from memq_dqc.builder.extract_utils import (
    SwapOp,
    logical_physical_map,
    window_final_op_id_map,
)
from memq_dqc.circuit.dag.mono import CircuitDAG
from memq_dqc.circuit.dag.remap import (
    _logical_to_physical_qubit,
    _ordered_network_qpu_ids,
    _remap_cleaned_qubit,
    _remap_cleaned_qubits,
    _remap_statement_qubits,
    _replace_qubit_declarations,
    _replace_statement_node,
    _sorted_qpu_ids,
)
from memq_dqc.circuit.dag.routing import (
    _build_remote_gate_statements,
    _build_routed_remote_gate_statements,
    _is_non_routable_direct_remote_gate_error,
)
from memq_dqc.circuit.dag.swap_builders import (
    _build_rswap_statements_for_swap,
)
from memq_dqc.circuit.ops import Op
from memq_dqc.preprocessing.qasm import clone_statement_node
from memq_dqc.preprocessing.qasm.types import (
    CleanedIncludeStatement,
    CleanedQuantumGate,
    CleanedQuantumMeasurementStatement,
    CleanedStatement,
)
from memq_dqc.utils.common import window_op_map

if TYPE_CHECKING:
    from memq_dqc.network import NetworkGraph
    from memq_dqc.partition.partitioner import QPU


class DistributedCircuitDAG(CircuitDAG):
    """DAG representation with remote gate names applied.

    A distributed circuit DAG extends the base CircuitDAG to handle circuits
    that have been partitioned across multiple quantum processing units (QPUs).
    It tracks which operations are designated as remote gates and maintains
    the scheduling information for distributed execution.

    Attributes:
        num_remote_gates: Number of operations tagged as remote gates.
        num_local_swaps_added: Number of local swaps inserted from
            communication-path local swap sequences.
    """

    # TODO: this whole class needs review and cleanup
    def __init__(
        # TODO: see if we can avoid passing along so much data here =
        self,
        base_dag: CircuitDAG,
        remote_statement_ids: set[int],
        swaps_schedule: list[list[SwapOp]],
        windows: list[list[Op]],
        schedule: list[dict[QPU, set[int]]],
        comp_qubits_per_qpu: list[int] | None = None,
        comm_qubits_per_qpu: list[int] | None = None,
        network: NetworkGraph | None = None,
    ) -> None:
        """Initialize a distributed DAG from an existing DAG.

        Args:
            base_dag: Original circuit DAG.
            remote_statement_ids: Statement indices to rename as remote gates.
            swaps_schedule: List of swap operations organized by scheduling windows.
            windows: List of operation windows for distributed execution.
            schedule: Mapping of QPUs to sets of qubit indices for each scheduling step.
            comp_qubits_per_qpu: Number of computation qubits for each QPU
                indexed by QPU ID.
            comm_qubits_per_qpu: Number of communication qubits for each QPU
                indexed by QPU ID.
            network: Network graph used to resolve communication pairs for
                remote gates.
        """
        self.program = base_dag.program
        self.statements, self.num_local_swaps_added = self._build_statements(
            base_dag.statements,
            remote_statement_ids,
            windows,
            swaps_schedule,
            schedule,
            comp_qubits_per_qpu,
            comm_qubits_per_qpu,
            network,
        )
        self.ops = self._build_ops(base_dag.ops, remote_statement_ids)
        self.num_remote_gates = self._count_remote_gates(remote_statement_ids)
        self.num_two_qubit_gates = self._count_two_qubit_gates()
        self.graph = self._build_dag()
        self.layers = self._extract_layers()
        self.depth = len(self.layers)

    # TODO: this is wayyyyyy to much to have in DAG - must abstract elsewhere
    @staticmethod
    def _build_statements(
        statements: list[CleanedStatement],
        remote_statement_ids: set[int],
        windows: list[list[Op]],
        swaps_schedule: list[list[SwapOp]],
        schedule: list[dict[QPU, set[int]]],
        comp_qubits_per_qpu: list[int] | None = None,
        comm_qubits_per_qpu: list[int] | None = None,
        network: NetworkGraph | None = None,
    ) -> tuple[list[CleanedStatement], int]:
        """Build distributed statements with remapped qubits and remote gates.

        Args:
            statements: Input cleaned statements from the base circuit.
            remote_statement_ids: Statement indices that should be converted to
                remote gate variants.
            windows: Operation windows used for schedule-aware remapping.
            swaps_schedule: Swap operations inserted between adjacent windows.
            schedule: Per-window mapping from QPU to assigned logical qubits.
            comp_qubits_per_qpu: Optional computation-qubit capacities by QPU.
            comm_qubits_per_qpu: Optional communication-qubit counts by QPU.
            network: Optional network graph used to derive communication pairs.

        Returns:
            The updated cleaned statements and the number of inserted local
            swaps.

        Raises:
            ValueError: If window, schedule, or swap dimensions are invalid.
        """
        # TODO: this needs to be thoroughly fixed and refactored ... messy
        if not windows:
            raise ValueError("windows must contain at least one window.")
        if len(schedule) != len(windows):
            raise ValueError(
                "schedule/windows length mismatch: "
                f"len(schedule)={len(schedule)} != len(windows)={len(windows)}."
            )
        expected_swaps_windows = len(windows) - 1
        if len(swaps_schedule) != expected_swaps_windows:
            raise ValueError(
                "swaps_schedule length mismatch: "
                f"len(swaps_schedule)={len(swaps_schedule)} != "
                f"len(windows)-1={expected_swaps_windows}."
            )

        # Get list of all ids to insert swaps (final op of each window except last)
        num_swaps = sum(len(swaps) for swaps in swaps_schedule)
        if num_swaps > 0 and network is None:
            raise ValueError(
                "Network graph is required to build remote swaps with "
                "communication qubits."
            )
        final_ops_in_windows = set(window_final_op_id_map(windows).values())
        window_map = window_op_map(windows)
        logical_to_physical = logical_physical_map(schedule, swaps_schedule)
        schedule_qpu_ids = _sorted_qpu_ids(
            [qpu.id for qpu in schedule[0].keys()]
        )
        comp_capacity_by_schedule_qpu: dict[int, int] | None = None
        if comp_qubits_per_qpu is not None:
            if len(comp_qubits_per_qpu) != len(schedule_qpu_ids):
                raise ValueError(
                    "comp_qubits_per_qpu length must match the number of "
                    "QPUs in schedule: "
                    f"{len(comp_qubits_per_qpu)} != "
                    f"{len(schedule_qpu_ids)}."
                )
            comp_capacity_by_schedule_qpu = {
                schedule_qpu_id: comp_qubits_per_qpu[idx]
                for idx, schedule_qpu_id in enumerate(schedule_qpu_ids)
            }
        schedule_to_network_qpu_id: dict[int, int] = {}
        network_to_schedule_qpu_id: dict[int, int] = {}
        if network is not None:
            network_qpu_ids = _ordered_network_qpu_ids(network)
            if len(schedule_qpu_ids) != len(network_qpu_ids):
                raise ValueError(
                    "Schedule QPU count does not match network QPU count: "
                    f"{len(schedule_qpu_ids)} != {len(network_qpu_ids)}."
                )
            schedule_to_network_qpu_id = {
                schedule_qpu_id: network_qpu_ids[idx]
                for idx, schedule_qpu_id in enumerate(schedule_qpu_ids)
            }
            network_to_schedule_qpu_id = {
                network_qpu_id: schedule_qpu_id
                for schedule_qpu_id, network_qpu_id in (
                    schedule_to_network_qpu_id.items()
                )
            }
        distributed_statements = []
        local_swaps_added = 0
        op_id = -1
        swap_window_idx = 0
        current_window_idx = 0
        for idx, statement in enumerate(statements):
            # Update statement node with correct physical qubit mapping
            mapped_node = statement.node
            if statement.is_op:
                op_id += 1
                current_window_idx = window_map.get(op_id, current_window_idx)
            mapped_node = _remap_statement_qubits(
                mapped_node,
                logical_to_physical[current_window_idx],
            )

            # Rebuild list of statements using appropriate remote gates
            if idx in remote_statement_ids and isinstance(
                statement, CleanedQuantumGate
            ):
                if network is None:
                    raise ValueError(
                        "Network graph is required to build remote gates."
                    )
                # get the physical qubits mapped to appropriate logical qubits
                gate_qubits = _remap_cleaned_qubits(
                    statement.qubits,
                    logical_to_physical[current_window_idx],
                )

                # Convert the physical strings to PhysicalQubit objects
                network_qubit_a = _logical_to_physical_qubit(
                    gate_qubits[0],
                    schedule_to_network_qpu_id,
                )
                network_qubit_b = _logical_to_physical_qubit(
                    gate_qubits[1],
                    schedule_to_network_qpu_id,
                )
                try:
                    remote_gate_statements, added_local_swaps = (
                        _build_remote_gate_statements(
                            statement=statement,
                            mapped_node=mapped_node,
                            network_qubit_a=network_qubit_a,
                            network_qubit_b=network_qubit_b,
                            gate_qubits=gate_qubits,
                            network=network,
                            network_to_schedule_qpu_id=(
                                network_to_schedule_qpu_id
                            ),
                        )
                    )
                    distributed_statements.extend(remote_gate_statements)
                    local_swaps_added += added_local_swaps
                except ValueError as direct_gate_error:
                    if _is_non_routable_direct_remote_gate_error(
                        direct_gate_error
                    ):
                        raise direct_gate_error
                    routed_error: ValueError | None = None
                    routed_built = False
                    for moving_operand_idx in (0, 1):
                        try:
                            routed_statements, added_local_swaps = (
                                _build_routed_remote_gate_statements(
                                    statement=statement,
                                    mapped_node=mapped_node,
                                    gate_qubits=gate_qubits,
                                    logical_to_physical_window=(
                                        logical_to_physical[current_window_idx]
                                    ),
                                    comp_capacity_by_schedule_qpu=(
                                        comp_capacity_by_schedule_qpu
                                    ),
                                    network=network,
                                    schedule_to_network_qpu_id=(
                                        schedule_to_network_qpu_id
                                    ),
                                    network_to_schedule_qpu_id=(
                                        network_to_schedule_qpu_id
                                    ),
                                    moving_operand_idx=moving_operand_idx,
                                )
                            )
                            distributed_statements.extend(routed_statements)
                            local_swaps_added += added_local_swaps
                            routed_built = True
                            break
                        except ValueError as route_err:
                            routed_error = route_err
                    if not routed_built:
                        if routed_error is not None:
                            raise routed_error from direct_gate_error
                        raise direct_gate_error
            # Insert non-remote gates
            else:
                if isinstance(statement, CleanedQuantumGate):
                    distributed_statements.append(
                        CleanedQuantumGate(
                            statement_type=statement.statement_type,
                            node=mapped_node,
                            is_op=statement.is_op,
                            name=statement.name,
                            qubits=_remap_cleaned_qubits(
                                statement.qubits,
                                logical_to_physical[current_window_idx],
                            ),
                        )
                    )
                elif isinstance(statement, CleanedQuantumMeasurementStatement):
                    distributed_statements.append(
                        CleanedQuantumMeasurementStatement(
                            statement_type=statement.statement_type,
                            node=mapped_node,
                            is_op=statement.is_op,
                            qubit=_remap_cleaned_qubit(
                                statement.qubit,
                                logical_to_physical[current_window_idx],
                            ),
                            cbit=statement.cbit,
                        )
                    )
                else:
                    distributed_statements.append(
                        _replace_statement_node(statement, mapped_node)
                    )
            # If we find final op in window, insert remote swaps to reach next partition
            if statement.is_op and op_id in final_ops_in_windows:
                swaps = swaps_schedule[swap_window_idx]
                network_graph = network
                if swaps and network_graph is None:
                    raise ValueError(
                        "Network graph is required to build remote swaps "
                        "with communication qubits."
                    )
                for swap in swaps:
                    distributed_statements.extend(
                        _build_rswap_statements_for_swap(
                            swap=swap,
                            network=network_graph,
                            schedule_to_network_qpu_id=(
                                schedule_to_network_qpu_id
                            ),
                            network_to_schedule_qpu_id=(
                                network_to_schedule_qpu_id
                            ),
                            logical_to_physical_window=(
                                logical_to_physical[current_window_idx]
                            ),
                            comp_capacity_by_schedule_qpu=(
                                comp_capacity_by_schedule_qpu
                            ),
                        )
                    )
                current_window_idx += 1
                swap_window_idx += 1
        # Add custom distributed gateset if remote gates or swaps are present
        if remote_statement_ids or num_swaps > 0:
            include_node = clone_statement_node(
                ast.Include(filename="builder/distgates.inc")
            )
            dist_include = CleanedIncludeStatement(
                statement_type=ast.Include,
                node=include_node,
                is_op=False,
                filename="builder/distgates.inc",
            )
            distributed_statements = [dist_include] + distributed_statements
        distributed_statements = _replace_qubit_declarations(
            distributed_statements,
            schedule,
            comp_qubits_per_qpu,
            comm_qubits_per_qpu,
        )
        return distributed_statements, local_swaps_added

    @staticmethod
    def _build_ops(
        ops: list[Op],
        remote_statement_ids: set[int],
    ) -> list[Op]:
        """Build operation metadata with remote gate names applied.

        Args:
            ops: Base operations from the original DAG.
            remote_statement_ids: Statement indices corresponding to remote
                operations.

        Returns:
            Operations with names rewritten for remote statements.
        """
        distributed_ops = []
        for op in ops:
            name = op.name
            if op.statement_id in remote_statement_ids:
                name = f"r{name}"
            distributed_ops.append(
                Op(
                    op_id=op.op_id,
                    statement_id=op.statement_id,
                    name=name,
                    qubits=op.qubits,
                    node=op.node,
                )
            )
        return distributed_ops

    def _count_remote_gates(
        self,
        remote_statement_ids: set[int],
    ) -> int:
        """Count operations marked as remote.

        Args:
            remote_statement_ids: Statement indices corresponding to remote
                operations.

        Returns:
            The number of operations tagged as remote gates.
        """
        return sum(
            1 for op in self.ops if op.statement_id in remote_statement_ids
        )
