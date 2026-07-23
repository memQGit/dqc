# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Circuit-level models and construction helpers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, TypeAlias

from openqasm3 import ast

from xdqc.circuit.dag import CircuitDAG, DistributedCircuitDAG
from xdqc.circuit.dag.distributed import (
    build_distributed_statements,
    count_remote_gates,
)
from xdqc.circuit.dag.remap import _circuit_qubit_to_physical_qubit
from xdqc.circuit.op import Op
from xdqc.preprocessing.qasm import extract_cleaned_statements
from xdqc.preprocessing.qasm.io import load_qasm_program
from xdqc.preprocessing.qasm.types import (
    CircuitQubit,
    CleanedClassicalDeclaration,
    CleanedQuantumGate,
    CleanedQuantumMeasurementStatement,
    CleanedStatement,
)

if TYPE_CHECKING:
    from xdqc.builder.extract_utils import SwapOp
    from xdqc.network import NetworkGraph, PhysicalQubit
    from xdqc.partition.partitioner import QPU

_REMOTE_OP_NAMES = frozenset({"rcx", "rcp", "rcry", "rcz", "rswap"})
EbitPair: TypeAlias = tuple["PhysicalQubit", "PhysicalQubit"]
EbitAssignment: TypeAlias = tuple[EbitPair, ...]
EbitCandidatesByOpId: TypeAlias = dict[int, tuple[EbitAssignment, ...]]


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


# The distributed builder emits its own per-QPU registers named ``q<qpu_id>``
# (computation) and ``c<qpu_id>`` (communication). Any input register sharing
# that shape would collide with an emitted register.
_RESERVED_REGISTER_PATTERN = re.compile(r"^[qc]\d+$")


def validate_register_names(statements: list[CleanedStatement]) -> None:
    """Reject register names that collide with builder-reserved namespaces.

    Only declarations that survive reconstruction are checked. Original
    qubit declarations are dropped and their references remapped to the
    generated ``q<qpu_id>`` registers, so they can never collide. Classical
    declarations survive verbatim, so a classical register whose name
    matches the ``q<int>`` / ``c<int>`` shape emitted by the distributed
    compiler would collide with a generated register and silently produce
    an invalid program; such names are rejected up front. Conventional bare
    ``q`` / ``c`` names and descriptive names are unaffected because emitted
    registers always carry a numeric suffix.

    Args:
        statements: Cleaned statements of the monolithic circuit.

    Raises:
        ValueError: If a surviving classical declaration uses the reserved
            namespace.
    """
    for statement in statements:
        if not isinstance(statement, CleanedClassicalDeclaration):
            continue
        if _RESERVED_REGISTER_PATTERN.match(statement.name):
            kind = (
                "communication"
                if statement.name.startswith("c")
                else "computation"
            )
            raise ValueError(
                f"Classical register {statement.name!r} uses the reserved "
                f"{kind}-register namespace '{statement.name[0]}<int>' "
                "emitted by the distributed compiler. Rename it to a bare "
                "'q'/'c' or a name without a numeric suffix."
            )


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
        ebit_candidates_by_op_id: Optional scheduler-facing e-bit candidates
            for remote operations when e-bit assignment is deferred.
    """

    program: ast.Program
    statements: list[CleanedStatement]
    ops: list[Op]
    num_two_qubit_gates: int
    num_remote_gates: int
    num_local_swaps_added: int
    dag: DistributedCircuitDAG
    ebit_candidates_by_op_id: EbitCandidatesByOpId | None = None


class Circuit:
    """Primary circuit model for xdqc.

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
        validate_register_names(statements)
        # TODO: think about how to make this easier to access (currently circuit.mono.program)
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
        ebit_assignment: bool = True,
        gate_group_op_ids: tuple[tuple[int, ...], ...] = (),
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
            ebit_assignment: Whether the compiler assigns concrete e-bit
                pairs into the scheduler DAG. If false, schedulers choose from
                viable e-bit pair candidates.
            gate_group_op_ids: Operation IDs for detected gate groups that may
                share cat-entanglement in the emitted program.

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
            ebit_assignment=ebit_assignment,
            gate_group_op_ids=gate_group_op_ids,
        )
        ops = extract_ops(statements)
        ebit_candidates_by_op_id = (
            None
            if ebit_assignment
            else _build_ebit_candidates_by_op_id(ops, network)
        )
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
            dag=DistributedCircuitDAG(
                ops,
                ignore_remote_ebit_dependencies=not ebit_assignment,
            ),
            ebit_candidates_by_op_id=ebit_candidates_by_op_id,
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


def _build_ebit_candidates_by_op_id(
    ops: list[Op],
    network: NetworkGraph,
) -> EbitCandidatesByOpId:
    """Build viable e-bit assignment candidates for EPR-backed operations."""
    candidates_by_op_id: EbitCandidatesByOpId = {}
    for index, op in enumerate(ops):
        if not (op.is_remote or op.name == "catent"):
            continue
        candidates_by_op_id[op.op_id] = _remote_ebit_candidates(
            op,
            network,
            expected_pairs=_expected_ebit_pair_count(ops, index),
        )
    return candidates_by_op_id


def _expected_ebit_pair_count(ops: list[Op], op_index: int) -> int:
    """Return the number of EPR pairs consumed by an EPR-backed operation."""
    op = ops[op_index]
    if op.name == "rswap":
        return 2
    if op.name == "catent" and op_index + 1 < len(ops):
        next_op = ops[op_index + 1]
        if next_op.name == "rswap":
            return 2
    return 1


def _remote_ebit_candidates(
    op: Op,
    network: NetworkGraph,
    *,
    expected_pairs: int | None = None,
) -> tuple[EbitAssignment, ...]:
    """Return viable e-bit assignments for one remote operation."""
    if len(op.qubits) < 2:
        raise ValueError(
            "Remote operation must contain at least two data operands."
        )

    network_qubit_a = _circuit_qubit_to_physical_qubit(op.qubits[0])
    network_qubit_b = _circuit_qubit_to_physical_qubit(op.qubits[1])
    pair_options = network.get_comm_pair_options(
        network_qubit_a,
        network_qubit_b,
    )
    pairs = tuple(comm_pair for _, comm_pair, _ in pair_options)
    if expected_pairs is not None:
        expected_pair_count = expected_pairs
    elif op.name == "rswap":
        expected_pair_count = 2
    else:
        expected_pair_count = 1
    if expected_pair_count == 1:
        return tuple((pair,) for pair in pairs)

    assignments: list[EbitAssignment] = []
    for first_index, first_pair in enumerate(pairs):
        used_qubits = set(first_pair)
        for second_pair in pairs[first_index + 1 :]:
            if second_pair[0] in used_qubits or second_pair[1] in used_qubits:
                continue
            assignments.append((first_pair, second_pair))

    if not assignments:
        raise ValueError(
            "Remote swap requires at least two disjoint e-bit pair candidates."
        )
    return tuple(assignments)
