# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Circuit-level models and construction helpers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from openqasm3 import ast

from memq_dqc.circuit.dag import CircuitDAG, DistributedCircuitDAG
from memq_dqc.circuit.dag.distributed import (
    build_distributed_statements,
    count_remote_gates,
)
from memq_dqc.circuit.op import Op
from memq_dqc.preprocessing.qasm import extract_cleaned_statements
from memq_dqc.preprocessing.qasm.io import load_qasm_program
from memq_dqc.preprocessing.qasm.types import (
    CircuitQubit,
    CleanedQuantumGate,
    CleanedQuantumMeasurementStatement,
    CleanedStatement,
)

if TYPE_CHECKING:
    from memq_dqc.builder.extract_utils import SwapOp
    from memq_dqc.network import NetworkGraph
    from memq_dqc.partition.partitioner import QPU

_REMOTE_OP_NAMES = frozenset({"rcx", "rcp", "rcry", "rcz", "rswap"})


def extract_program_statements(
    program: ast.Program,
) -> list[CleanedStatement]:
    """Extract cleaned statements from the original program.

    Args:
        program: Parsed OpenQASM 3 program.

    Returns:
        The cleaned non-barrier statements.
    """
    cleaned_statements = extract_cleaned_statements(program)
    return [
        statement
        for statement in cleaned_statements
        if not isinstance(statement.node, ast.QuantumBarrier)
    ]


def extract_ops(statements: list[CleanedStatement]) -> list[Op]:
    """Extract operation objects from cleaned statements in source order.

    Quantum gates and measurements are considered operations. All other
    statements, such as barriers and gate definitions, are not operations.

    Args:
        statements: Cleaned non-barrier statements.

    Returns:
        Operations extracted in source order.

    Raises:
        ValueError: If a measurement statement is missing its qubit operand.
    """
    ops: list[Op] = []
    for statement_id, statement in enumerate(statements):
        if not statement.is_op:
            continue

        op_id = len(ops)

        # Measurement Operation
        if isinstance(statement, CleanedQuantumMeasurementStatement):
            if statement.qubit is None:
                raise ValueError("Measurement statement missing qubit.")
            qubits: tuple[CircuitQubit, ...] = (
                CircuitQubit(
                    statement.qubit.register_name,
                    statement.qubit.index,
                ),
            )
            name = statement.name
            is_remote = False

        # Quantum Gate Operation
        elif isinstance(statement, CleanedQuantumGate):
            qubits = tuple(
                CircuitQubit(qubit.register_name, qubit.index)
                for qubit in statement.qubits
            )
            name = statement.name
            is_remote = _is_remote_op_name(name)
        else:
            raise ValueError("Unsupported operation statement type.")

        ops.append(
            Op(
                op_id=op_id,
                statement_id=statement_id,
                name=name,
                is_remote=is_remote,
                qubits=qubits,
                node=statement.node,
            )
        )
    return ops


def _is_remote_op_name(name: str) -> bool:
    """Return whether an operation name denotes a remote distributed op."""
    return name in _REMOTE_OP_NAMES


def count_two_qubit_ops(ops: list[Op]) -> int:
    """Count operations that act on exactly two qubits.

    Args:
        ops: Circuit operations.

    Returns:
        The number of two-qubit operations.
    """
    return sum(1 for op in ops if op.is_two_qubit)


@dataclass(slots=True)
class MonoCircuit:
    """Monolithic (original) circuit representation and associated metadata.

    Attributes:
        program: Parsed OpenQASM 3 program for the original circuit.
        statements: Cleaned program statements in source order.
        ops: Operations extracted from the cleaned statements.
        num_two_qubit_gates: Number of two-qubit operations in the circuit.
        dag: DAG derived from ``ops``.
    """

    program: ast.Program
    statements: list[CleanedStatement]
    ops: list[Op]
    num_two_qubit_gates: int
    dag: CircuitDAG


@dataclass(slots=True)
class DistributedCircuit:
    """Distributed circuit representation and associated metadata.

    Attributes:
        program: Parsed OpenQASM 3 program for the distributed circuit.
        statements: Cleaned distributed statements in emitted order.
        ops: Operations extracted for the distributed circuit.
        num_two_qubit_gates: Number of two-qubit operations in the circuit.
        num_remote_gates: Number of operations marked as remote gates.
        num_local_swaps_added: Number of local swaps inserted during routing.
        dag: DAG derived from the distributed operations.
    """

    program: ast.Program
    statements: list[CleanedStatement]
    ops: list[Op]
    num_two_qubit_gates: int
    num_remote_gates: int
    num_local_swaps_added: int
    dag: DistributedCircuitDAG


class Circuit:
    """Primary circuit model for memq-dqc.

    A ``Circuit`` owns grouped monolithic and distributed representations.
    The monolithic representation is always populated at construction time.
    The distributed representation is populated on demand after partitioning
    and extraction.
    """

    def __init__(self, program_or_path: str | ast.Program) -> None:
        """Initialize a circuit from a program or QASM file path.

        Args:
            program_or_path: Parsed OpenQASM 3 program or filesystem path.
        """
        if isinstance(program_or_path, ast.Program):
            program = program_or_path
        else:
            program = load_qasm_program(program_or_path)

        statements = extract_program_statements(program)
        ops = extract_ops(statements)
        self.mono = MonoCircuit(
            program=program,
            statements=statements,
            ops=ops,
            num_two_qubit_gates=count_two_qubit_ops(ops),
            dag=CircuitDAG(ops),
        )
        self.distributed: DistributedCircuit | None = None

    def build_distributed(
        self,
        remote_statement_ids: set[int],
        swaps_schedule: list[list[SwapOp]],
        windows: list[list[Op]],
        schedule: list[dict[QPU, set[int]]],
        network: NetworkGraph,
        comp_qubits_per_qpu: list[int] | None = None,
        comm_qubits_per_qpu: list[int] | None = None,
    ) -> DistributedCircuit:
        """Populate the distributed representation for this circuit.

        Args:
            remote_statement_ids: Statement indices to rename as remote gates.
            swaps_schedule: Swap operations organized by scheduling windows.
            windows: Operation windows for distributed execution.
            schedule: Per-window QPU assignments for logical qubits.
            network: Network graph used to route communication.
            comp_qubits_per_qpu: Optional computation-qubit capacities by QPU.
            comm_qubits_per_qpu: Optional communication-qubit capacities by
                QPU.

        Returns:
            The populated distributed circuit representation.
        """
        statements, num_local_swaps_added = build_distributed_statements(
            statements=self.mono.statements,
            remote_statement_ids=remote_statement_ids,
            windows=windows,
            swaps_schedule=swaps_schedule,
            schedule=schedule,
            network=network,
            comp_qubits_per_qpu=comp_qubits_per_qpu,
            comm_qubits_per_qpu=comm_qubits_per_qpu,
        )
        ops = extract_ops(statements)
        distributed_program = ast.Program(
            version=self.mono.program.version,
            statements=[statement.node for statement in statements],
        )
        distributed = DistributedCircuit(
            program=distributed_program,
            statements=statements,
            ops=ops,
            num_two_qubit_gates=count_two_qubit_ops(ops),
            num_remote_gates=count_remote_gates(ops),
            num_local_swaps_added=num_local_swaps_added,
            dag=DistributedCircuitDAG(ops),
        )
        self.distributed = distributed
        return distributed


def build_circuit(program_or_path: str | ast.Program) -> Circuit:
    """Build a Circuit from a program or QASM file path.

    Args:
        program_or_path: OpenQASM 3 program or filesystem path.

    Returns:
        The constructed Circuit.
    """
    return Circuit(program_or_path)
