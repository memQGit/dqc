# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""DAG representation for OpenQASM 3 quantum circuits."""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from dataclasses import dataclass

import networkx as nx
from openqasm3 import ast

from memq_dqc.utils import extract_qubit_index


@dataclass(frozen=True, slots=True)
class Op:
    """A quantum operation in the DAG extracted from an OpenQASM circuit.

    Attributes:
        op_id: Unique operation index in program order.
        name: Gate or instruction name.
        qubits: Qubit indices the operation applies to.
        node: Original OpenQASM AST node.
    """

    op_id: int
    name: str
    qubits: tuple[int, ...]
    node: ast.QASMNode

    @property
    def is_two_qubit(self) -> bool:
        """Return True when the operation acts on two qubits.

        Returns:
            True if the operation spans two qubits, otherwise False.
        """
        return len(self.qubits) == 2


@dataclass(frozen=True, slots=True)
class Layer(Sequence[Op]):
    """A layer of operations that can be executed in parallel.

    Attributes:
        ops: Operations contained in the layer, in scheduling order.
    """

    ops: tuple[Op, ...]

    def __iter__(self) -> Iterator[Op]:
        """Return an iterator over operations in the layer."""
        return iter(self.ops)

    def __len__(self) -> int:
        """Return the number of operations in the layer."""
        return len(self.ops)

    def __getitem__(self, index: int) -> Op:
        """Return the operation at a given index."""
        return self.ops[index]

    @property
    def qubits(self) -> list[int]:
        """Return the sorted unique qubits used by the layer.

        Returns:
            Sorted list of qubit indices used by operations in the layer.
        """
        return sorted({q for op in self.ops for q in op.qubits})


class CircuitDAG:
    """Directed Acyclic Graph (DAG) for an OpenQASM 3 circuit.

    Args:
        program: Parsed OpenQASM 3 program to analyze.
    """

    def __init__(self, program: ast.Program) -> None:
        """Initialize the DAG representation for a quantum program.

        Args:
            program: The OpenQASM 3 program from which to extract operations
                and build the corresponding directed acyclic graph.
        """
        self.program = program
        self.ops: list[Op] = self._extract_ops()
        self.num_two_qubit_gates = self._count_two_qubit_gates()
        self.graph: nx.DiGraph = self._build_dag()
        self.layers: list[Layer] = self._extract_layers()
        self.depth = len(self.layers)

    # Private Methods
    def _build_dag(self) -> nx.DiGraph:
        """Build the dependency graph for the circuit operations.

        Args:
            None.

        Returns:
            Directed acyclic graph of operation dependencies.
        """
        g = nx.DiGraph()

        for op in self.ops:
            g.add_node(op.op_id, op=op, name=op.name, qubits=op.qubits)

        # track last operation on each qubit
        last_op_on_qubit: dict[int, int] = {}
        for op in self.ops:
            for q in op.qubits:
                # Previous op exists on this qubit, so current op depends on it
                if q in last_op_on_qubit:
                    prev_op_id = last_op_on_qubit[q]
                    # Check if edge already exists, add qubit to set of qubits
                    if g.has_edge(prev_op_id, op.op_id):
                        g[prev_op_id][op.op_id]["qubits"].add(q)
                    # Otherwise, create new edge with set containing this qubit
                    else:
                        g.add_edge(prev_op_id, op.op_id, qubits={q})
                last_op_on_qubit[q] = op.op_id

        return g

    def _extract_ops(self) -> list[Op]:
        """Extract operations from the program in source order.

        Returns:
            List of extracted operations in program order.
        """
        program = self.program
        ops: list[Op] = []
        num_qubits = 0
        qubits = []

        for statement in program.statements:
            if isinstance(statement, ast.QubitDeclaration):
                name = statement.qubit.name
                size = 1 if statement.size is None else statement.size.value

                # QASM indices are 0..size-1 for that declared register
                for i in range(size):
                    qubits.append(f"{name}[{i}]")

                num_qubits += size

            elif isinstance(statement, ast.QuantumGate):
                gate_name = statement.name.name
                qubit_indices = [
                    extract_qubit_index(q) for q in statement.qubits
                ]
                ops.append(
                    Op(
                        op_id=len(ops),
                        name=gate_name,
                        qubits=tuple(qubit_indices),
                        node=statement,
                    )
                )

            elif isinstance(statement, ast.QuantumMeasurementStatement):
                qubit_index = extract_qubit_index(statement.measure.qubit)
                ops.append(
                    Op(
                        op_id=len(ops),
                        name="measure",
                        qubits=(qubit_index,),
                        node=statement,
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
            A list of layers, where each layer contains operations that can be
            executed in parallel.
        """
        in_degree_map = dict(self.graph.in_degree())
        # Initial Nodes have in-degree of 0
        degree_zero_nodes = [
            node for node, degree in in_degree_map.items() if degree == 0
        ]

        layers: list[Layer] = []

        while degree_zero_nodes:
            current_layer: list[Op] = []
            next_layer_nodes: set[int] = set()

            for node in degree_zero_nodes:
                op = self.graph.nodes[node]["op"]
                current_layer.append(op)

                # Move to next layer by reducing in-degrees of successor nodes
                for _, succ in self.graph.edges(node):
                    in_degree_map[succ] -= 1
                    if in_degree_map[succ] == 0:
                        next_layer_nodes.add(succ)

            layers.append(Layer(tuple(current_layer)))
            degree_zero_nodes = list(next_layer_nodes)

        return layers

    def extract_layers(self) -> list[Layer]:
        """Return the extracted operation layers for the circuit.

        Returns:
            A list of layers, where each layer contains operations that can be
            executed in parallel.
        """
        return self.layers
