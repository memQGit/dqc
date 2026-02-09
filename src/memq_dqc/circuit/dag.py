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
from memq_dqc.qasm.types import Qubit
from memq_dqc.utils.common import window_op_map

if TYPE_CHECKING:
    from memq_dqc.partition.types import QPU


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
        last_op_on_qubit: dict[Qubit, int] = {}
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
                qubits: tuple[Qubit, ...] = (
                    Qubit(
                        statement.qubit.register_name,
                        statement.qubit.index,
                    ),
                )
            else:
                qubits = tuple(
                    Qubit(qubit.register_name, qubit.index)
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
    """

    def __init__(
        # TODO: see if we can avoid passing along so much data here =
        self,
        base_dag: CircuitDAG,
        remote_statement_ids: set[int],
        swaps_schedule: list[list[SwapOp]],
        windows: list[list[Op]],
        schedule: list[dict[QPU, set[int]]],
    ) -> None:
        """Initialize a distributed DAG from an existing DAG.

        Args:
            base_dag: Original circuit DAG.
            remote_statement_ids: Statement indices to rename as remote gates.
            swaps_schedule: List of swap operations organized by scheduling windows.
            windows: List of operation windows for distributed execution.
            schedule: Mapping of QPUs to sets of qubit indices for each scheduling step.
        """
        self.program = base_dag.program
        self.statements = self._build_statements(
            base_dag.statements,
            remote_statement_ids,
            windows,
            swaps_schedule,
            schedule,
        )
        self.ops = self._build_ops(base_dag.ops, remote_statement_ids)
        self.num_remote_gates = self._count_remote_gates(remote_statement_ids)
        self.num_two_qubit_gates = self._count_two_qubit_gates()
        self.graph = self._build_dag()
        self.layers = self._extract_layers()
        self.depth = len(self.layers)

    @staticmethod
    def _build_statements(
        statements: list[CleanedStatement],
        remote_statement_ids: set[int],
        windows: list[list[Op]],
        swaps_schedule: list[list[SwapOp]],
        schedule: list[dict[QPU, set[int]]],
    ) -> list[CleanedStatement]:
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
        final_ops_in_windows = set(window_final_op_id_map(windows).values())
        window_map = window_op_map(windows)
        logical_to_physical = logical_physical_map(schedule, swaps_schedule)
        distributed_statements = []
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
                # TODO: must handle specific 2q gates
                updated_node = rename_quantum_gate(
                    mapped_node,
                    f"r{statement.name}",
                )
                distributed_statements.append(
                    CleanedQuantumGate(
                        statement_type=statement.statement_type,
                        node=updated_node,
                        is_op=statement.is_op,
                        name=f"r{statement.name}",
                        qubits=_remap_cleaned_qubits(
                            statement.qubits,
                            logical_to_physical[current_window_idx],
                        ),
                    )
                )
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
            # If we find final op in window, insert swaps to reach next partition
            if statement.is_op and op_id in final_ops_in_windows:
                swaps = swaps_schedule[swap_window_idx]
                for swap in swaps:
                    swap_node, swap_qubits = _build_swap_gate(
                        swap,
                    )
                    distributed_statements.append(
                        CleanedQuantumGate(
                            statement_type=ast.QuantumGate,
                            node=swap_node,
                            is_op=True,
                            name="rswap",
                            qubits=swap_qubits,
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
        )
        return distributed_statements

    @staticmethod
    def _build_ops(
        ops: list[Op],
        remote_statement_ids: set[int],
    ) -> list[Op]:
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
    if statement.node is node:
        return statement
    return replace(statement, node=node)


def _remap_cleaned_qubits(
    qubits: list[Qubit],
    logical_to_physical: dict[int, tuple[int, int]],
) -> list[Qubit]:
    return [
        _remap_cleaned_qubit(qubit, logical_to_physical) for qubit in qubits
    ]


def _remap_cleaned_qubit(
    qubit: Qubit | None,
    logical_to_physical: dict[int, tuple[int, int]],
) -> Qubit | None:
    if qubit is None:
        return None
    qpu_id, slot_idx = logical_to_physical[qubit.index]
    return Qubit(register_name=f"q{qpu_id}", index=slot_idx)


def _remap_statement_qubits(
    statement: ast.Statement,
    logical_to_physical: dict[int, tuple[int, int]],
) -> ast.Statement:
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
) -> list[CleanedStatement]:
    """Replace original qubit declaration with new declarations for each QPU.

    Args:
        statements: List of cleaned statements to process.
        schedule: Partition schedule; for each window, a mapping of QPUs to sets of logical qubit indices.

    Returns:
        Updated list of cleaned statements with new qubit declarations.
    """
    if not schedule:
        raise ValueError("schedule must contain at least one window.")

    qpu_qubits = {qpu: set(qubits) for qpu, qubits in schedule[0].items()}
    new_declarations: list[CleanedStatement] = []
    for qpu, qubits in sorted(qpu_qubits.items(), key=lambda item: item[0].id):
        size = len(qubits)
        size_expr = ast.IntegerLiteral(size) if size != 1 else None
        node = clone_statement_node(
            ast.QubitDeclaration(
                qubit=ast.Identifier(f"q{qpu.id}"),
                size=size_expr,
            )
        )
        new_declarations.append(
            CleanedQubitDeclaration(
                statement_type=ast.QubitDeclaration,
                node=node,
                is_op=False,
                name=f"q{qpu.id}",
                size=size,
            )
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


def _build_swap_gate(
    swap: SwapOp,
) -> tuple[ast.QuantumGate, list[Qubit]]:
    q0_qpu, q0_slot = swap.pos0
    q1_qpu, q1_slot = swap.pos1
    qubits = [
        Qubit(register_name=f"q{q0_qpu}", index=q0_slot),
        Qubit(register_name=f"q{q1_qpu}", index=q1_slot),
    ]
    node = clone_statement_node(
        ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("rswap"),
            arguments=[],
            qubits=[
                ast.IndexedIdentifier(
                    name=ast.Identifier(f"q{q0_qpu}"),
                    indices=[[ast.IntegerLiteral(q0_slot)]],
                ),
                ast.IndexedIdentifier(
                    name=ast.Identifier(f"q{q1_qpu}"),
                    indices=[[ast.IntegerLiteral(q1_slot)]],
                ),
            ],
        )
    )
    return node, qubits
