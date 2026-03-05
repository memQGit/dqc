# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""DAG representation for OpenQASM 3 quantum circuits."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

import networkx as nx
from openqasm3 import ast

from memq_dqc.builder.extract_utils import (
    SwapOp,
    logical_physical_map,
    window_final_op_id_map,
)
from memq_dqc.circuit.layers import Layer
from memq_dqc.circuit.ops import Op
from memq_dqc.preprocessing.qasm import (
    CleanedIncludeStatement,
    CleanedQuantumGate,
    CleanedQuantumMeasurementStatement,
    CleanedQubitDeclaration,
    CleanedStatement,
    clone_statement_node,
    extract_cleaned_statements,
    extract_qubit_index,
    rename_quantum_gate,
)
from memq_dqc.qasm.types import LogicalQubit
from memq_dqc.utils.common import window_op_map

if TYPE_CHECKING:
    from memq_dqc.graph import NetworkGraph, PhysicalQubit
    from memq_dqc.partition.types import QPU


_REMOTE_TWO_QUBIT_GATE_NAME_MAP = {
    "cx": "rcx",
    "cp": "rcp",
    "cry": "rcry",
    "cz": "rcz",
    "swap": "rswap",
}


class CircuitDAG:
    """Directed Acyclic Graph (DAG) for an OpenQASM 3 circuit.

    The DAG captures operation dependencies and provides layered views suitable
    for scheduling and partitioning.
    """

    def __init__(self, program: ast.Program) -> None:
        """Initialize the DAG representation for a quantum program.

        Args:
            program: The OpenQASM 3 program from which to extract operations
                and build the corresponding directed acyclic graph.
        """
        self.program = program
        cleaned_statements = extract_cleaned_statements(program)
        self.num_barrier_statements = sum(
            1
            for statement in cleaned_statements
            if isinstance(statement, CleanedStatement)
            and isinstance(statement.node, ast.QuantumBarrier)
        )
        self.statements = [
            statement
            for statement in cleaned_statements
            if not isinstance(statement.node, ast.QuantumBarrier)
        ]
        self.ops: list[Op] = self._extract_ops()
        self.num_two_qubit_gates = self._count_two_qubit_gates()
        self.graph: nx.DiGraph = self._build_dag()
        self.layers: list[Layer] = self._extract_layers()
        self.depth = len(self.layers)

    # Private Methods
    def _build_dag(self) -> nx.DiGraph:
        """Build the dependency graph for the circuit operations.

        Returns:
            Directed acyclic graph of operation dependencies.
        """
        graph = nx.DiGraph()

        for op in self.ops:
            graph.add_node(op.op_id, op=op, name=op.name, qubits=op.qubits)

        # Track the last operation touching each qubit.
        last_op_on_qubit: dict[LogicalQubit, int] = {}
        for op in self.ops:
            for qubit in op.qubits:
                # Previous op exists on this qubit, so current op depends on it.
                if qubit in last_op_on_qubit:
                    prev_op_id = last_op_on_qubit[qubit]
                    # If edge already exists, add qubit to dependency edge data.
                    if graph.has_edge(prev_op_id, op.op_id):
                        graph[prev_op_id][op.op_id]["qubits"].add(qubit)
                    # Otherwise, create new edge with set containing this qubit
                    else:
                        graph.add_edge(prev_op_id, op.op_id, qubits={qubit})
                last_op_on_qubit[qubit] = op.op_id

        return graph

    def _extract_ops(self) -> list[Op]:
        """Extract operations from the program in source order.

        Returns:
            Operations extracted in program order.
        """
        ops: list[Op] = []

        # Extract operations (gates & measurements) from statements
        for statement_id, statement in enumerate(self.statements):
            if not statement.is_op:
                continue
            op_id = len(ops)
            if statement.name == "measure":
                if statement.qubit is None:
                    raise ValueError("Measurement statement missing qubit.")
                qubits: tuple[LogicalQubit, ...] = (
                    LogicalQubit(
                        statement.qubit.register_name,
                        statement.qubit.index,
                    ),
                )
            else:
                qubits = tuple(
                    LogicalQubit(qubit.register_name, qubit.index)
                    for qubit in statement.qubits
                )
            ops.append(
                Op(
                    op_id=op_id,
                    statement_id=statement_id,
                    name=statement.name,
                    qubits=qubits,
                    node=statement.node,
                )
            )
        return ops

    def _count_two_qubit_gates(self) -> int:
        """Count operations that act on exactly two qubits.

        Returns:
            The number of two-qubit operations in the circuit.
        """
        return sum(1 for op in self.ops if op.is_two_qubit)

    def _extract_layers(self) -> list[Layer]:
        """Extract layers of operations from the DAG.

        Returns:
            Layers of operations that can be executed in parallel.
        """
        in_degree_map = dict(self.graph.in_degree())
        # Initial Nodes have in-degree of 0
        ready_nodes = [
            node_id for node_id, degree in in_degree_map.items() if degree == 0
        ]

        layers: list[Layer] = []

        while ready_nodes:
            current_layer: list[Op] = []
            next_layer_nodes: set[int] = set()

            for node_id in ready_nodes:
                op = self.graph.nodes[node_id]["op"]
                current_layer.append(op)

                # Move to next layer by reducing in-degrees of successor nodes
                for successor in self.graph.successors(node_id):
                    in_degree_map[successor] -= 1
                    if in_degree_map[successor] == 0:
                        next_layer_nodes.add(successor)

            layers.append(Layer(tuple(current_layer)))
            ready_nodes = list(next_layer_nodes)

        return layers

    def extract_layers(self) -> list[Layer]:
        """Return the extracted operation layers for the circuit.

        Returns:
            Operation layers that can be executed in parallel.
        """
        return self.layers


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


def _replace_statement_node(
    statement: CleanedStatement,
    node: ast.Statement,
) -> CleanedStatement:
    """Return a statement with its AST node replaced.

    Args:
        statement: Original cleaned statement.
        node: Replacement AST statement node.

    Returns:
        The original statement if the node is unchanged, otherwise a copied
        statement with the new node.
    """
    if statement.node is node:
        return statement
    return replace(statement, node=node)


def _remap_cleaned_qubits(
    qubits: list[LogicalQubit],
    logical_to_physical: dict[int, tuple[int, int]],
) -> list[LogicalQubit]:
    """Remap a list of logical qubits to QPU-local register coordinates.

    Args:
        qubits: Logical qubits to remap.
        logical_to_physical: Mapping from logical index to ``(qpu_id, slot)``.

    Returns:
        Remapped logical qubits using per-QPU register names and indices.
    """
    return [
        _remap_cleaned_qubit(qubit, logical_to_physical) for qubit in qubits
    ]


def _remap_cleaned_qubit(
    qubit: LogicalQubit | None,
    logical_to_physical: dict[int, tuple[int, int]],
) -> LogicalQubit | None:
    """Remap one logical qubit to its current physical placement.

    Args:
        qubit: Logical qubit to remap, if present.
        logical_to_physical: Mapping from logical index to ``(qpu_id, slot)``.

    Returns:
        Remapped logical qubit, or ``None`` when the input is ``None``.
    """
    if qubit is None:
        return None
    qpu_id, slot_idx = logical_to_physical[qubit.index]
    return LogicalQubit(register_name=f"q{qpu_id}", index=slot_idx)


def _logical_to_physical_qubit(
    qubit: LogicalQubit,
    schedule_to_network_qpu_id: dict[int, int],
) -> PhysicalQubit:
    """Convert a logical qubit reference to a physical network qubit.

    Args:
        qubit: Logical qubit in schedule register space.
        schedule_to_network_qpu_id: Optional remapping from schedule QPU IDs to
            network QPU IDs.

    Returns:
        Physical computation qubit reference for network queries.

    Raises:
        ValueError: If the logical register name is not in ``q<int>`` format.
    """
    # TODO: should reconcile the different qubit objects in the program ...
    register = qubit.register_name.removeprefix("q")
    if not register.isdigit():
        raise ValueError(
            "LogicalQubit computation register must be q<int>. "
            f"Received {qubit.register_name!r}."
        )
    register_qpu_id = int(register)
    qpu_id = _map_qpu_id(register_qpu_id, schedule_to_network_qpu_id)
    from memq_dqc.graph import PhysicalQubit

    return PhysicalQubit(
        qpu_id=qpu_id,
        qubit_id=qubit.index,
        qubit_type="computation",
    )


def _physical_to_logical_qubit(
    qubit: PhysicalQubit,
    network_to_schedule_qpu_id: dict[int, int],
) -> LogicalQubit:
    # NOTE: This performs a representational mapping from a PhysicalQubit to
    # a LogicalQubit reference; no additional semantic information is added.
    """Convert a physical network qubit to a logical register reference.

    Args:
        qubit: Physical qubit to convert.
        network_to_schedule_qpu_id: Optional remapping from network QPU IDs to
            schedule QPU IDs.

    Returns:
        Logical qubit using ``q`` registers for computation qubits and ``c``
        registers for communication qubits.
    """
    qpu_id = _map_qpu_id(qubit.qpu_id, network_to_schedule_qpu_id)
    prefix = "c" if qubit.qubit_type == "communication" else "q"
    return LogicalQubit(
        register_name=f"{prefix}{qpu_id}", index=qubit.qubit_id
    )


def _order_comm_pair(
    mapped_qubits: list[LogicalQubit],
    comm_pair: tuple[PhysicalQubit, PhysicalQubit],
    network_to_schedule_qpu_id: dict[int, int],
) -> tuple[PhysicalQubit, PhysicalQubit]:
    """Align communication qubit ordering with logical gate operand order.

    Args:
        mapped_qubits: Mapped logical operands for a two-qubit gate.
        comm_pair: Communication qubit pair returned by the network.
        network_to_schedule_qpu_id: Optional remapping from network QPU IDs to
            schedule QPU IDs.

    Returns:
        Communication pair ordered to match ``mapped_qubits`` operand order.

    Raises:
        ValueError: If fewer than two operands are provided or the pair cannot
            be aligned to the operand QPU IDs.
    """
    if len(mapped_qubits) < 2:
        raise ValueError(
            "Remote gate must include at least two mapped computation qubits."
        )

    qpu_a = _qpu_id_from_register_name(mapped_qubits[0].register_name)
    qpu_b = _qpu_id_from_register_name(mapped_qubits[1].register_name)
    comm_a, comm_b = comm_pair

    comm_a_qpu_id = _map_qpu_id(comm_a.qpu_id, network_to_schedule_qpu_id)
    comm_b_qpu_id = _map_qpu_id(comm_b.qpu_id, network_to_schedule_qpu_id)

    if comm_a_qpu_id == qpu_a and comm_b_qpu_id == qpu_b:
        return comm_a, comm_b

    if comm_a_qpu_id == qpu_b and comm_b_qpu_id == qpu_a:
        return comm_b, comm_a

    raise ValueError(
        "Communication pair QPU IDs do not match mapped qubit QPU IDs: "
        f"mapped=({mapped_qubits[0].register_name}, "
        f"{mapped_qubits[1].register_name}), "
        f"comm=({comm_a_qpu_id}, {comm_b_qpu_id})."
    )


def _qpu_id_from_register_name(register_name: str) -> int:
    """Extract the integer QPU ID from a logical register name.

    Args:
        register_name: Register identifier such as ``q0`` or ``c2``.

    Returns:
        Parsed QPU ID.

    Raises:
        ValueError: If the register name is empty or malformed.
    """
    if not register_name:
        raise ValueError("LogicalQubit register name cannot be empty.")
    prefix = register_name[0]
    if prefix not in {"q", "c"}:
        raise ValueError(
            "LogicalQubit register name must start with 'q' or 'c': "
            f"{register_name!r}."
        )
    suffix = register_name[1:]
    if not suffix.isdigit():
        raise ValueError(
            "LogicalQubit register suffix must be an integer. "
            f"Received {register_name!r}."
        )
    return int(suffix)


def _ordered_network_qpu_ids(network: NetworkGraph) -> list[int]:
    """Return sorted QPU IDs discovered from a network graph.

    Args:
        network: Network graph containing physical qubit mappings.

    Returns:
        Sorted unique QPU IDs present in the network.
    """
    qpu_ids = {qubit.qpu_id for qubit in network.qubit_type_map}
    return sorted(qpu_ids)


def _sorted_qpu_ids(qpu_ids: list[int]) -> list[int]:
    """Return QPU IDs in ascending order.

    Args:
        qpu_ids: QPU IDs to sort.

    Returns:
        Sorted QPU IDs.
    """
    return sorted(qpu_ids)


def _map_qpu_id(
    qpu_id: int,
    mapping: dict[int, int],
) -> int:
    """Map a QPU ID through an optional mapping.

    Args:
        qpu_id: QPU ID to map.
        mapping: Mapping dictionary from source to target QPU IDs.

    Returns:
        Mapped ID when present, otherwise the original ID.
    """
    return mapping.get(qpu_id, qpu_id)


def _to_ast_qubit_ref(qubit: LogicalQubit) -> ast.IndexedIdentifier:
    """Build an AST indexed identifier for a logical qubit.

    Args:
        qubit: Logical qubit to convert.

    Returns:
        OpenQASM indexed identifier referencing the qubit.
    """
    return ast.IndexedIdentifier(
        name=ast.Identifier(qubit.register_name),
        indices=[[ast.IntegerLiteral(qubit.index)]],
    )


def _remap_statement_qubits(
    statement: ast.Statement,
    logical_to_physical: dict[int, tuple[int, int]],
) -> ast.Statement:
    """Clone and remap qubit references inside a supported AST statement.

    Args:
        statement: Statement to clone and remap.
        logical_to_physical: Mapping from logical index to ``(qpu_id, slot)``.

    Returns:
        Remapped statement clone.
    """
    mapped = clone_statement_node(statement)
    if isinstance(mapped, ast.QuantumGate):
        mapped.qubits = [
            _map_qubit_ref(qubit, logical_to_physical)
            for qubit in mapped.qubits
        ]
        return mapped
    if isinstance(mapped, ast.QuantumMeasurementStatement):
        mapped.measure = ast.QuantumMeasurement(
            qubit=_map_qubit_ref(mapped.measure.qubit, logical_to_physical)
        )
        return mapped
    if isinstance(mapped, ast.QuantumBarrier):
        mapped.qubits = [
            _map_qubit_ref(qubit, logical_to_physical)
            for qubit in mapped.qubits
        ]
        return mapped
    if isinstance(mapped, ast.QuantumReset):
        mapped.qubits = _map_qubit_ref(mapped.qubits, logical_to_physical)
        return mapped
    if isinstance(mapped, ast.QuantumPhase):
        mapped.qubits = [
            _map_qubit_ref(qubit, logical_to_physical)
            for qubit in mapped.qubits
        ]
        return mapped
    return mapped


def _map_qubit_ref(
    qubit: ast.IndexedIdentifier | ast.Identifier,
    logical_to_physical: dict[int, tuple[int, int]],
) -> ast.IndexedIdentifier:
    """Map one indexed qubit reference to per-QPU register space.

    Args:
        qubit: Qubit AST reference to remap.
        logical_to_physical: Mapping from logical index to ``(qpu_id, slot)``.

    Returns:
        Remapped qubit AST reference.

    Raises:
        NotImplementedError: If the input qubit is not indexed.
    """
    # TODO: handle unindexed identifers (eg c = measure q)
    if isinstance(qubit, ast.Identifier):
        raise NotImplementedError("Cannot remap unindexed qubit identifiers.")
    logical_index = extract_qubit_index(qubit)
    qpu_id, slot_idx = logical_to_physical[logical_index]
    return ast.IndexedIdentifier(
        name=ast.Identifier(f"q{qpu_id}"),
        indices=[[ast.IntegerLiteral(slot_idx)]],
    )


def _replace_qubit_declarations(
    statements: list[CleanedStatement],
    schedule: list[dict[QPU, set[int]]],
    comp_qubits_per_qpu: list[int] | None = None,
    comm_qubits_per_qpu: list[int] | None = None,
) -> list[CleanedStatement]:
    """Replace original qubit declaration with new declarations for each QPU.

    Args:
        statements: List of cleaned statements to process.
        schedule: Partition schedule; for each window, a mapping of QPUs to sets of logical qubit indices.
        comp_qubits_per_qpu: Number of computation qubits for each QPU
            indexed by QPU ID.
        comm_qubits_per_qpu: Number of communication qubits for each QPU
            indexed by QPU ID.

    Returns:
        Updated list of cleaned statements with new qubit declarations.
    """
    if not schedule:
        raise ValueError("schedule must contain at least one window.")

    qpu_qubits = {qpu: set(qubits) for qpu, qubits in schedule[0].items()}
    qpu_ids = sorted(qpu.id for qpu in qpu_qubits)
    if comp_qubits_per_qpu is None:
        comp_counts_by_qpu = {
            qpu.id: len(qubits) for qpu, qubits in qpu_qubits.items()
        }
    else:
        if len(comp_qubits_per_qpu) != len(qpu_ids):
            raise ValueError(
                "comp_qubits_per_qpu length must match the number of QPUs "
                f"in schedule: {len(comp_qubits_per_qpu)} != {len(qpu_ids)}."
            )
        comp_counts_by_qpu = {
            qpu_id: comp_qubits_per_qpu[idx]
            for idx, qpu_id in enumerate(qpu_ids)
        }

    for qpu, qubits in qpu_qubits.items():
        capacity = comp_counts_by_qpu[qpu.id]
        if len(qubits) > capacity:
            raise ValueError(
                "Schedule assigns more computation qubits than available "
                f"on QPU {qpu.id}: assigned={len(qubits)}, "
                f"capacity={capacity}."
            )

    if comm_qubits_per_qpu is None:
        comm_counts_by_qpu = {qpu_id: 0 for qpu_id in qpu_ids}
    else:
        if len(comm_qubits_per_qpu) != len(qpu_ids):
            raise ValueError(
                "comm_qubits_per_qpu length must match the number of QPUs "
                f"in schedule: {len(comm_qubits_per_qpu)} != {len(qpu_ids)}."
            )
        comm_counts_by_qpu = {
            qpu_id: comm_qubits_per_qpu[idx]
            for idx, qpu_id in enumerate(qpu_ids)
        }

    def _build_declaration(
        register_name: str,
        size: int,
    ) -> CleanedQubitDeclaration:
        """Build a cleaned qubit declaration statement.

        Args:
            register_name: Qubit register name.
            size: Register size.

        Returns:
            Cleaned qubit declaration for the provided register.
        """
        size_expr = ast.IntegerLiteral(size)
        node = clone_statement_node(
            ast.QubitDeclaration(
                qubit=ast.Identifier(register_name),
                size=size_expr,
            )
        )
        return CleanedQubitDeclaration(
            statement_type=ast.QubitDeclaration,
            node=node,
            is_op=False,
            name=register_name,
            size=size,
        )

    new_declarations: list[CleanedStatement] = []
    for qpu, _qubits in sorted(
        qpu_qubits.items(), key=lambda item: item[0].id
    ):
        comp_size = comp_counts_by_qpu[qpu.id]
        new_declarations.append(_build_declaration(f"q{qpu.id}", comp_size))

    for qpu_id in qpu_ids:
        comm_size = comm_counts_by_qpu[qpu_id]
        if comm_size > 0:
            new_declarations.append(
                _build_declaration(f"c{qpu_id}", comm_size)
            )

    filtered = [
        statement
        for statement in statements
        if not isinstance(statement, CleanedQubitDeclaration)
    ]

    insert_idx = 0
    while insert_idx < len(filtered) and isinstance(
        filtered[insert_idx], CleanedIncludeStatement
    ):
        insert_idx += 1
    return filtered[:insert_idx] + new_declarations + filtered[insert_idx:]


def _build_remote_gate_statements(
    statement: CleanedQuantumGate,
    mapped_node: ast.Statement,
    network_qubit_a: PhysicalQubit,
    network_qubit_b: PhysicalQubit,
    gate_qubits: list[LogicalQubit],
    network: NetworkGraph,
    network_to_schedule_qpu_id: dict[int, int],
) -> tuple[list[CleanedStatement], int]:
    """Build statements for one remote two-qubit gate execution."""
    _, raw_comm_pair, local_paths = network.get_comm_pair(
        network_qubit_a, network_qubit_b
    )
    if not _remote_local_paths_are_valid(local_paths):
        for (
            _,
            candidate_pair,
            candidate_paths,
        ) in network.get_comm_pair_options(network_qubit_a, network_qubit_b):
            if _remote_local_paths_are_valid(candidate_paths):
                raw_comm_pair = candidate_pair
                local_paths = candidate_paths
                break
        if not _remote_local_paths_are_valid(local_paths):
            raise ValueError(
                "No valid direct remote-gate path keeps data operands on "
                "computation qubits."
            )
    updated_gate_qubit_a = (
        local_paths[0][-2] if len(local_paths[0]) > 1 else network_qubit_a
    )
    updated_gate_qubit_b = (
        local_paths[1][-2] if len(local_paths[1]) > 1 else network_qubit_b
    )
    remote_gate_qubits = [
        _physical_to_logical_qubit(
            updated_gate_qubit_a, network_to_schedule_qpu_id
        ),
        _physical_to_logical_qubit(
            updated_gate_qubit_b, network_to_schedule_qpu_id
        ),
    ]

    gate_statements: list[CleanedStatement] = []
    swap_gate_statements: list[CleanedStatement] = []
    local_swaps_added = 0
    for local_path in local_paths:
        if len(local_path) <= 2:
            continue

        # Move the data qubit along the local path one edge at a time.
        for comp_qubit_pos in range(len(local_path) - 2):
            q0 = _physical_to_logical_qubit(
                local_path[comp_qubit_pos],
                network_to_schedule_qpu_id,
            )
            q1 = _physical_to_logical_qubit(
                local_path[comp_qubit_pos + 1],
                network_to_schedule_qpu_id,
            )
            _validate_local_swap_pair(q0, q1)
            swap_node, swap_qubits = _build_local_swap_gate(q0, q1)
            swap_gate_statement = CleanedQuantumGate(
                statement_type=ast.QuantumGate,
                node=swap_node,
                is_op=True,
                name="swap",
                qubits=swap_qubits,
            )
            gate_statements.append(swap_gate_statement)
            swap_gate_statements.append(swap_gate_statement)
            local_swaps_added += 1

    comm_pair = _order_comm_pair(
        gate_qubits,
        raw_comm_pair,
        network_to_schedule_qpu_id,
    )
    remote_gate_qubits.extend(
        [
            _physical_to_logical_qubit(
                comm_pair[0], network_to_schedule_qpu_id
            ),
            _physical_to_logical_qubit(
                comm_pair[1], network_to_schedule_qpu_id
            ),
        ]
    )
    remote_gate_name = _REMOTE_TWO_QUBIT_GATE_NAME_MAP.get(statement.name)
    if remote_gate_name is None:
        raise ValueError(
            "Unsupported remote two-qubit gate "
            f"{statement.name!r}. Supported gates are: "
            f"{sorted(_REMOTE_TWO_QUBIT_GATE_NAME_MAP)}."
        )
    updated_node = rename_quantum_gate(mapped_node, remote_gate_name)
    updated_node.qubits = [
        _to_ast_qubit_ref(qubit) for qubit in remote_gate_qubits
    ]
    gate_statements.append(
        CleanedQuantumGate(
            statement_type=statement.statement_type,
            node=updated_node,
            is_op=statement.is_op,
            name=remote_gate_name,
            qubits=remote_gate_qubits,
        )
    )

    swap_gate_statements.reverse()
    for swap_gate_statement in swap_gate_statements:
        gate_statements.append(swap_gate_statement)
        local_swaps_added += 1

    return gate_statements, local_swaps_added


def _remote_local_paths_are_valid(
    local_paths: tuple[list[PhysicalQubit], list[PhysicalQubit]],
) -> bool:
    """Return whether both local paths keep data qubits on computation nodes."""
    return all(_remote_local_path_is_valid(path) for path in local_paths)


def _remote_local_path_is_valid(local_path: list[PhysicalQubit]) -> bool:
    """Return whether one local path is valid for remote gate execution."""
    if len(local_path) < 2:
        return False
    if not local_path[0].is_computation:
        return False
    if not local_path[-1].is_communication:
        return False
    if not local_path[-2].is_computation:
        return False
    return all(qubit.is_computation for qubit in local_path[:-1])


def _is_non_routable_direct_remote_gate_error(error: ValueError) -> bool:
    """Return whether a direct remote-gate error should not trigger routing."""
    return (
        "No valid direct remote-gate path keeps data operands on "
        "computation qubits."
        in str(error)
        or "Unsupported remote two-qubit gate " in str(error)
    )


def _build_routed_remote_gate_statements(
    statement: CleanedQuantumGate,
    mapped_node: ast.Statement,
    gate_qubits: list[LogicalQubit],
    logical_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
    network: NetworkGraph,
    schedule_to_network_qpu_id: dict[int, int],
    network_to_schedule_qpu_id: dict[int, int],
    moving_operand_idx: int,
) -> tuple[list[CleanedStatement], int]:
    # TODO: cleanup / check (made by Codex)
    """Build statements for a routed remote gate via intermediary QPUs."""
    static_operand_idx = 1 - moving_operand_idx
    moving_gate_qubit = gate_qubits[moving_operand_idx]
    static_gate_qubit = gate_qubits[static_operand_idx]
    moving_network_qubit = _logical_to_physical_qubit(
        moving_gate_qubit,
        schedule_to_network_qpu_id,
    )
    static_network_qubit = _logical_to_physical_qubit(
        static_gate_qubit,
        schedule_to_network_qpu_id,
    )
    route_qpu_ids = network.get_directional_remote_gate_qpu_route(
        moving_network_qubit.qpu_id,
        static_network_qubit.qpu_id,
    )
    if len(route_qpu_ids) <= 2:
        raise ValueError(
            "Routed remote-gate execution requires at least one intermediary "
            f"QPU for directional movement {route_qpu_ids!r}."
        )

    moved_pos = (
        _qpu_id_from_register_name(moving_gate_qubit.register_name),
        moving_gate_qubit.index,
    )
    static_pos = (
        _qpu_id_from_register_name(static_gate_qubit.register_name),
        static_gate_qubit.index,
    )
    routed_statements: list[CleanedStatement] = []
    forward_hop_positions: list[tuple[tuple[int, int], tuple[int, int]]] = []
    for hop_idx in range(len(route_qpu_ids) - 2):
        next_network_qpu_id = route_qpu_ids[hop_idx + 1]
        next_schedule_qpu_id = _map_qpu_id(
            next_network_qpu_id, network_to_schedule_qpu_id
        )
        candidate_slots = _candidate_comp_slots_for_qpu(
            qpu_id=next_schedule_qpu_id,
            logical_to_physical_window=logical_to_physical_window,
            comp_capacity_by_schedule_qpu=comp_capacity_by_schedule_qpu,
        )
        if not candidate_slots:
            raise ValueError(
                "No computation slot available on intermediary QPU "
                f"{next_schedule_qpu_id} while routing remote gate."
            )

        hop_built = False
        for candidate_slot in candidate_slots:
            if (
                next_schedule_qpu_id == static_pos[0]
                and candidate_slot == static_pos[1]
            ):
                continue
            try:
                rswap_statement = _build_rswap_statement_from_positions(
                    pos0=moved_pos,
                    pos1=(next_schedule_qpu_id, candidate_slot),
                    network=network,
                    schedule_to_network_qpu_id=schedule_to_network_qpu_id,
                    network_to_schedule_qpu_id=network_to_schedule_qpu_id,
                )
            except ValueError:
                continue
            routed_statements.append(rswap_statement)
            forward_hop_positions.append(
                (moved_pos, (next_schedule_qpu_id, candidate_slot))
            )
            moved_pos = (next_schedule_qpu_id, candidate_slot)
            hop_built = True
            break
        if not hop_built:
            raise ValueError(
                "Unable to build routed remote gate hop from "
                f"position {moved_pos} to QPU {next_schedule_qpu_id}."
            )

    moved_gate_qubit = LogicalQubit(
        register_name=f"q{moved_pos[0]}",
        index=moved_pos[1],
    )
    moved_network_qubit = _logical_to_physical_qubit(
        moved_gate_qubit,
        schedule_to_network_qpu_id,
    )

    if moving_operand_idx == 0:
        ordered_gate_qubits = [moved_gate_qubit, static_gate_qubit]
        network_gate_qubits = (moved_network_qubit, static_network_qubit)
    else:
        ordered_gate_qubits = [static_gate_qubit, moved_gate_qubit]
        network_gate_qubits = (static_network_qubit, moved_network_qubit)

    routed_gate_statements, added_local_swaps = _build_remote_gate_statements(
        statement=statement,
        mapped_node=mapped_node,
        network_qubit_a=network_gate_qubits[0],
        network_qubit_b=network_gate_qubits[1],
        gate_qubits=ordered_gate_qubits,
        network=network,
        network_to_schedule_qpu_id=network_to_schedule_qpu_id,
    )
    routed_statements.extend(routed_gate_statements)

    for pos0, pos1 in reversed(forward_hop_positions):
        routed_statements.append(
            _build_rswap_statement_from_positions(
                pos0=pos0,
                pos1=pos1,
                network=network,
                schedule_to_network_qpu_id=schedule_to_network_qpu_id,
                network_to_schedule_qpu_id=network_to_schedule_qpu_id,
            )
        )

    return routed_statements, added_local_swaps


def _candidate_comp_slots_for_qpu(
    qpu_id: int,
    logical_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
) -> list[int]:
    """Return candidate computation slots on a schedule QPU."""
    mapped_slots = sorted(
        slot
        for mapped_qpu_id, slot in logical_to_physical_window.values()
        if mapped_qpu_id == qpu_id
    )
    mapped_slots_set = set(mapped_slots)

    if comp_capacity_by_schedule_qpu is None:
        return mapped_slots

    if qpu_id not in comp_capacity_by_schedule_qpu:
        raise ValueError(
            f"Missing computation capacity for schedule QPU {qpu_id}."
        )
    capacity = comp_capacity_by_schedule_qpu[qpu_id]
    return sorted(
        range(capacity),
        key=lambda slot: (slot not in mapped_slots_set, slot),
    )


def _build_rswap_statement_from_positions(
    pos0: tuple[int, int],
    pos1: tuple[int, int],
    network: NetworkGraph,
    schedule_to_network_qpu_id: dict[int, int],
    network_to_schedule_qpu_id: dict[int, int],
) -> CleanedQuantumGate:
    """Build a routed ``rswap`` statement from two schedule-space positions."""
    swap_node, swap_qubits = _build_swap_gate(
        SwapOp(q0=-1, q1=-1, pos0=pos0, pos1=pos1),
        network,
        schedule_to_network_qpu_id,
        network_to_schedule_qpu_id,
    )
    return CleanedQuantumGate(
        statement_type=ast.QuantumGate,
        node=swap_node,
        is_op=True,
        name="rswap",
        qubits=swap_qubits,
    )


def _build_rswap_statements_for_swap(
    swap: SwapOp,
    network: NetworkGraph,
    schedule_to_network_qpu_id: dict[int, int],
    network_to_schedule_qpu_id: dict[int, int],
    logical_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
) -> list[CleanedQuantumGate]:
    """Build one or more ``rswap`` statements for a schedule-space swap.

    For adjacent QPUs, this emits a single ``rswap``. For non-adjacent QPUs,
    this emits a routed chain of adjacent ``rswap`` operations that preserves
    all intermediary placements while swapping only the endpoint positions.

    Args:
        swap: Swap operation to realize.
        network: Network graph used to resolve communication pairs and routes.
        schedule_to_network_qpu_id: Mapping from schedule QPU IDs to network
            QPU IDs.
        network_to_schedule_qpu_id: Mapping from network QPU IDs to schedule
            QPU IDs.
        logical_to_physical_window: Logical-to-physical map for the current
            window.
        comp_capacity_by_schedule_qpu: Optional computation capacity per
            schedule QPU.

    Returns:
        A non-empty list of ``rswap`` statements implementing ``swap``.
    """
    try:
        return [
            _build_rswap_statement_from_positions(
                pos0=swap.pos0,
                pos1=swap.pos1,
                network=network,
                schedule_to_network_qpu_id=schedule_to_network_qpu_id,
                network_to_schedule_qpu_id=network_to_schedule_qpu_id,
            )
        ]
    except ValueError as direct_swap_error:
        if not (
            hasattr(network, "_remote_comm_pair_counts")
            and hasattr(network, "_shortest_qpu_path_with_min_pairs")
        ):
            raise direct_swap_error
        routed_positions = _routed_swap_positions(
            pos0=swap.pos0,
            pos1=swap.pos1,
            network=network,
            schedule_to_network_qpu_id=schedule_to_network_qpu_id,
            network_to_schedule_qpu_id=network_to_schedule_qpu_id,
            logical_to_physical_window=logical_to_physical_window,
            comp_capacity_by_schedule_qpu=comp_capacity_by_schedule_qpu,
        )
        if len(routed_positions) < 2:
            raise direct_swap_error

        routed_statements: list[CleanedQuantumGate] = []
        for idx in range(len(routed_positions) - 1):
            routed_statements.append(
                _build_rswap_statement_from_positions(
                    pos0=routed_positions[idx],
                    pos1=routed_positions[idx + 1],
                    network=network,
                    schedule_to_network_qpu_id=schedule_to_network_qpu_id,
                    network_to_schedule_qpu_id=network_to_schedule_qpu_id,
                )
            )

        for idx in range(len(routed_positions) - 3, -1, -1):
            routed_statements.append(
                _build_rswap_statement_from_positions(
                    pos0=routed_positions[idx],
                    pos1=routed_positions[idx + 1],
                    network=network,
                    schedule_to_network_qpu_id=schedule_to_network_qpu_id,
                    network_to_schedule_qpu_id=network_to_schedule_qpu_id,
                )
            )

        return routed_statements


def _routed_swap_positions(
    pos0: tuple[int, int],
    pos1: tuple[int, int],
    network: NetworkGraph,
    schedule_to_network_qpu_id: dict[int, int],
    network_to_schedule_qpu_id: dict[int, int],
    logical_to_physical_window: dict[int, tuple[int, int]],
    comp_capacity_by_schedule_qpu: dict[int, int] | None,
) -> list[tuple[int, int]]:
    """Resolve intermediary positions for a routed non-adjacent swap.

    Args:
        pos0: First endpoint position in schedule space.
        pos1: Second endpoint position in schedule space.
        network: Network graph used to compute QPU hop routes.
        schedule_to_network_qpu_id: Mapping from schedule QPU IDs to network
            QPU IDs.
        network_to_schedule_qpu_id: Mapping from network QPU IDs to schedule
            QPU IDs.
        logical_to_physical_window: Logical-to-physical map for the current
            window.
        comp_capacity_by_schedule_qpu: Optional computation capacity per
            schedule QPU.

    Returns:
        Ordered positions from source to target, including intermediaries.
    """
    source_network_qpu_id = _map_qpu_id(pos0[0], schedule_to_network_qpu_id)
    target_network_qpu_id = _map_qpu_id(pos1[0], schedule_to_network_qpu_id)
    pair_counts = network._remote_comm_pair_counts()
    route_network_qpu_ids = network._shortest_qpu_path_with_min_pairs(
        source_qpu_id=source_network_qpu_id,
        target_qpu_id=target_network_qpu_id,
        min_pairs=2,
        pair_counts=pair_counts,
    )
    if len(route_network_qpu_ids) <= 2:
        return [pos0, pos1]

    routed_positions = [pos0]
    for network_qpu_id in route_network_qpu_ids[1:-1]:
        schedule_qpu_id = _map_qpu_id(
            network_qpu_id, network_to_schedule_qpu_id
        )
        candidate_slots = _candidate_comp_slots_for_qpu(
            qpu_id=schedule_qpu_id,
            logical_to_physical_window=logical_to_physical_window,
            comp_capacity_by_schedule_qpu=comp_capacity_by_schedule_qpu,
        )
        if not candidate_slots:
            raise ValueError(
                "No computation slot available on intermediary QPU "
                f"{schedule_qpu_id} while routing partition swap."
            )
        routed_positions.append((schedule_qpu_id, candidate_slots[0]))
    routed_positions.append(pos1)
    return routed_positions


def _build_swap_gate(
    swap: SwapOp,
    network: NetworkGraph,
    schedule_to_network_qpu_id: dict[int, int],
    network_to_schedule_qpu_id: dict[int, int],
) -> tuple[ast.QuantumGate, list[LogicalQubit]]:
    """Build an ``rswap`` gate node and logical-qubit payload.

    Args:
        swap: Swap operation describing two physical positions.
        network: Network graph used to resolve communication pairs.
        schedule_to_network_qpu_id: Mapping from schedule QPU IDs to network
            QPU IDs.
        network_to_schedule_qpu_id: Mapping from network QPU IDs to schedule
            QPU IDs.

    Returns:
        AST gate node and cleaned logical qubits for the swap.

    Raises:
        ValueError: If fewer than two disjoint communication pairs are
            available for state teleportation.
    """
    q0_qpu, q0_slot = swap.pos0
    q1_qpu, q1_slot = swap.pos1
    data_qubits = [
        LogicalQubit(register_name=f"q{q0_qpu}", index=q0_slot),
        LogicalQubit(register_name=f"q{q1_qpu}", index=q1_slot),
    ]

    network_qubit_a = _logical_to_physical_qubit(
        data_qubits[0],
        schedule_to_network_qpu_id,
    )
    network_qubit_b = _logical_to_physical_qubit(
        data_qubits[1],
        schedule_to_network_qpu_id,
    )
    pair_options = network.get_comm_pair_options(
        network_qubit_a,
        network_qubit_b,
    )
    selected_pairs = []
    used_comm_qubits = set()
    for _, comm_pair, _ in pair_options:
        comm_a, comm_b = comm_pair
        if comm_a in used_comm_qubits or comm_b in used_comm_qubits:
            continue
        selected_pairs.append(comm_pair)
        used_comm_qubits.update({comm_a, comm_b})
        if len(selected_pairs) == 2:
            break
    if len(selected_pairs) < 2:
        raise ValueError(
            "State teleportation not supported - currently requires "
            "2 e-bit pairs."
        )

    comm_qubits = [
        _physical_to_logical_qubit(comm_qubit, network_to_schedule_qpu_id)
        for comm_pair in selected_pairs
        for comm_qubit in comm_pair
    ]
    qubits = [*data_qubits, *comm_qubits]
    node = clone_statement_node(
        ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("rswap"),
            arguments=[],
            qubits=[_to_ast_qubit_ref(qubit) for qubit in qubits],
        )
    )
    return node, qubits


def _build_local_swap_gate(
    q0: LogicalQubit,
    q1: LogicalQubit,
) -> tuple[ast.QuantumGate, list[LogicalQubit]]:
    """Build a local ``swap`` gate node and cleaned qubit payload."""
    qubits = [q0, q1]
    node = clone_statement_node(
        ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("swap"),
            arguments=[],
            qubits=[
                _to_ast_qubit_ref(q0),
                _to_ast_qubit_ref(q1),
            ],
        )
    )
    return node, qubits


def _validate_local_swap_pair(q0: LogicalQubit, q1: LogicalQubit) -> None:
    """Validate that a local swap pair is on the same QPU."""
    if _qpu_id_from_register_name(
        q0.register_name
    ) != _qpu_id_from_register_name(q1.register_name):
        raise ValueError(
            "Local swap operands must be on the same QPU: "
            f"{q0.register_name!r}, {q1.register_name!r}."
        )
