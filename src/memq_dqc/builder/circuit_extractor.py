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

from __future__ import annotations

import logging
from collections.abc import Sequence
from typing import TYPE_CHECKING, Literal

from openqasm3 import ast

from memq_dqc._logging import StepTimer, workflow_logging
from memq_dqc.builder.extract_utils import (
    GroupDurationLimit,
    identify_gate_groups,
    identify_remote_gates,
    synthesize_state_teleportation_swaps,
)
from memq_dqc.circuit.op import Op
from memq_dqc.partition import Partitioner
from memq_dqc.preprocessing.qasm.types import (
    CleanedQuantumGate,
    CleanedQubitDeclaration,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from memq_dqc.circuit import Circuit, DistributedCircuit
    from memq_dqc.partition.partitioner import (
        PartitionSchedule,
        PartitionWindows,
    )
    from memq_dqc.scheduler.schedule import SchedulerHardwareProfile


def _resolve_group_duration_limit(
    profile: SchedulerHardwareProfile | None,
) -> GroupDurationLimit:
    """Return the EPR-lifetime gate-duration cap for one hardware profile.

    A gate group's scheduled block must fit within the EPR lifetime. The
    fixed per-block overhead is the entanglement generation time plus the
    ``catent`` and ``catdisent`` durations; whatever lifetime remains is the
    budget for the gates inside the group.

    Args:
        profile: Scheduler hardware profile whose timing drives the cap, or
            ``None`` to use the default ``neutral_atom.polarization`` config.

    Returns:
        The resolved gate-duration cap for group building.
    """
    from memq_dqc.scheduler.schedule import (
        SchedulerHardwareProfile,
        _load_scheduler_timing_model,
    )

    if profile is None:
        profile = SchedulerHardwareProfile.neutral_atom(
            entanglement_profile="neutral_atom.polarization",
        )
    timing = _load_scheduler_timing_model(profile)
    gate_duration_budget = (
        timing.epr_lifetime
        - timing.entanglement_time
        - timing.catent_time
        - timing.catdisent_time
    )
    return GroupDurationLimit(
        gate_duration_budget=gate_duration_budget,
        one_qubit_gate_time=timing.local_one_qubit_gate_time,
        two_qubit_gate_time=timing.local_two_qubit_gate_time,
    )


def extract_distributed_circuit(
    partitioner: Partitioner,
    *,
    ebit_assignment: bool = True,
    group_gates: bool = True,
    max_group_size: int | None = None,
    group_size_profile: SchedulerHardwareProfile | None = None,
    verbosity: Literal["quiet", "info", "debug"] = "quiet",
) -> ast.Program:
    """Extract distributed circuit from partitioning assignment.

    Args:
        partitioner: Partitioner with partitioning results.
        ebit_assignment: Whether the compiler assigns concrete e-bit pairs
            into the scheduler DAG. If false, schedulers choose from viable
            e-bit pair candidates.
        group_gates: Whether compatible remote gate groups should share one
            cat-entanglement region in the emitted program.
        max_group_size: Optional maximum number of two-qubit gates per emitted
            gate group.
        group_size_profile: Scheduler hardware profile whose timing bounds the
            duration of each gate group so its scheduled block stays within
            the EPR lifetime. Defaults to ``neutral_atom.polarization``.
        verbosity: Logging verbosity for this workflow call.

    Returns:
        Distributed OpenQASM 3 program with remote gate names applied.
    """
    with workflow_logging(verbosity):
        overall_timer = StepTimer()
        logger.info("Starting distributed circuit extraction.")

        # TODO: MUST DEAL WITH CASE OF ORIGINAL REGISTERS NAMED C
        circuit, schedule, windows = _validated_partitioner_outputs(
            partitioner
        )
        logger.debug(
            "Validated partitioner outputs: schedule_steps=%d windows=%d.",
            len(schedule),
            len(windows),
        )

        remote_analysis_timer = StepTimer()
        remote_gates = identify_remote_gates(circuit, partitioner)
        swap_schedule = synthesize_state_teleportation_swaps(schedule)
        num_swaps = sum(
            len(timestep_swaps) for timestep_swaps in swap_schedule
        )
        logger.debug(
            "Identified %d remote gates and %d synthesized swaps in %.3fs.",
            len(remote_gates),
            num_swaps,
            remote_analysis_timer.elapsed_seconds(),
        )

        if max_group_size is not None and max_group_size < 1:
            raise ValueError("max_group_size must be positive when provided.")

        duration_limit = _resolve_group_duration_limit(group_size_profile)
        logger.debug(
            "Gate-group duration budget: %.3f time units.",
            duration_limit.gate_duration_budget,
        )
        reordered_ops, group_indices, _ = identify_gate_groups(
            circuit,
            partitioner,
            verbose=True,
            max_size=max_group_size,
            duration_limit=duration_limit,
        )
        gate_group_op_ids = (
            _gate_group_op_ids(reordered_ops, group_indices)
            if group_gates
            else ()
        )
        total_grouped_gates = sum(end - start for start, end in group_indices)
        average_group_size = (
            total_grouped_gates / len(group_indices) if group_indices else 0
        )
        remote_statement_ids = {op.statement_id for op, _ in remote_gates}
        comp_qubits_per_qpu = partitioner.network.comp_qubits_per_qpu()
        comm_qubits_per_qpu = partitioner.network.comm_qubits_per_qpu()
        num_comm_registers = (
            sum(1 for count in comm_qubits_per_qpu if count > 0)
            if ebit_assignment
            else 0
        )

        build_timer = StepTimer()
        distributed = circuit.build_distributed(
            remote_statement_ids=remote_statement_ids,
            swaps_schedule=swap_schedule,
            windows=windows,
            schedule=schedule,
            comp_qubits_per_qpu=comp_qubits_per_qpu,
            comm_qubits_per_qpu=comm_qubits_per_qpu,
            network=partitioner.network,
            ebit_assignment=ebit_assignment,
            gate_group_op_ids=gate_group_op_ids,
        )
        logger.debug(
            "Built distributed circuit in %.3fs.",
            build_timer.elapsed_seconds(),
        )

        num_qpus = len(schedule[0])
        # Every original qubit-register declaration is dropped and replaced
        # with per-QPU registers, so subtract the real count rather than a
        # hardcoded 1 to keep the expected lower bound valid for circuits
        # with more than one qubit register.
        num_qubit_registers = sum(
            1
            for statement in circuit.mono.statements
            if isinstance(statement, CleanedQubitDeclaration)
        )
        local_swaps_added = distributed.num_local_swaps_added
        include_dist_gates = len(remote_gates) > 0 or num_swaps > 0
        expected_statement_count = (
            len(circuit.mono.statements)
            + int(include_dist_gates)
            + num_swaps
            + num_qpus
            + num_comm_registers
            - num_qubit_registers
            + local_swaps_added
        )
        actual_statement_count = len(distributed.statements)
        logger.debug(
            "Distributed statement count: expected_min=%d actual=%d "
            "include_dist_gates=%s local_swaps_added=%d num_qpus=%d "
            "num_comm_registers=%d remote_statement_ids=%d.",
            expected_statement_count,
            actual_statement_count,
            include_dist_gates,
            local_swaps_added,
            num_qpus,
            num_comm_registers,
            len(remote_statement_ids),
        )

        # Routed remote gates may add extra ``rswap`` statements beyond the
        # schedule-synthesized swaps, so ``expected_statement_count`` is a
        # lower bound, not an exact count. Gate grouping rewrites the
        # statement stream (merging gates into shared cat-entanglement
        # blocks), so the bound is only checked when grouping is disabled.
        # A plain ``assert`` is avoided so the invariant still holds under
        # ``python -O``.
        if (
            not group_gates
            and actual_statement_count < expected_statement_count
        ):
            raise RuntimeError(
                "Distributed circuit extraction produced fewer statements "
                f"than expected (actual={actual_statement_count}, "
                f"expected>={expected_statement_count}). This indicates a "
                "statement-accounting error while assembling the "
                "distributed program."
            )
        exact_cost = _exact_entanglement_cost(distributed)
        partitioner._algorithm._set_exact_cost(exact_cost)
        logger.info(
            "Distributed circuit extraction completed in %.3fs: "
            "remote_gates=%d swaps=%d statements=%d exact_cost=%.3f "
            "avg_group_size=%.3f.",
            overall_timer.elapsed_seconds(),
            len(remote_gates),
            num_swaps,
            actual_statement_count,
            exact_cost,
            average_group_size,
        )
        return distributed.program


def _gate_group_op_ids(
    reordered_ops: Sequence[Op],
    group_indices: set[tuple[int, int]],
) -> tuple[tuple[int, ...], ...]:
    """Return grouped operation IDs from reordered gate-group ranges."""
    groups: list[tuple[int, ...]] = []
    for start, end in sorted(group_indices):
        op_ids = tuple(op.op_id for op in reordered_ops[start:end])
        if len(op_ids) > 1:
            groups.append(op_ids)
    return tuple(groups)


def _validated_partitioner_outputs(
    partitioner: Partitioner,
) -> tuple[Circuit, PartitionSchedule, PartitionWindows]:
    """Validate that partitioning outputs needed for extraction are present."""
    circuit = partitioner.circuit
    schedule = partitioner.schedule
    if schedule is None:
        raise ValueError("partitioner.run() must be called before extraction.")
    if not schedule:
        raise ValueError(
            "partitioner.schedule must contain at least one step."
        )

    windows = partitioner.windows
    if windows is None:
        raise ValueError(
            "partitioner.windows is missing; run partitioner first."
        )

    return circuit, schedule, windows


def _exact_entanglement_cost(distributed: DistributedCircuit) -> float:
    """Return exact e-bit cost from emitted cat-entanglement pairs.

    A matched ``catent``/``catdisent`` pair is the source of truth for e-bit
    usage. When concrete communication operands are present, the number of
    e-bits is the number of communication-qubit pairs in ``catent``. When
    e-bit assignment is deferred and communication operands have been stripped,
    the wrapped operation determines the required pair count.

    Raises:
        ValueError: If a cat-entanglement pair is malformed or unmatched.
    """
    exact_cost = 0.0
    pending_catent: tuple[int, CleanedQuantumGate, float] | None = None
    for index, statement in enumerate(distributed.statements):
        if not isinstance(statement, CleanedQuantumGate):
            continue
        if statement.name == "catent":
            if pending_catent is not None:
                pending_index, _, _ = pending_catent
                raise ValueError(
                    "Encountered nested catent before matching catdisent "
                    f"for catent at statement {pending_index}."
                )
            pending_catent = (
                index,
                statement,
                _catent_ebit_count(statement, distributed.statements, index),
            )
        elif statement.name == "catdisent":
            if pending_catent is None:
                raise ValueError(
                    "Encountered catdisent without preceding catent at "
                    f"statement {index}."
                )
            _, catent_statement, catent_cost = pending_catent
            if statement.qubits != catent_statement.qubits:
                raise ValueError(
                    "catdisent qubits do not match preceding catent qubits "
                    f"at statement {index}."
                )
            exact_cost += catent_cost
            pending_catent = None

    if pending_catent is not None:
        pending_index, _, _ = pending_catent
        raise ValueError(
            f"catent at statement {pending_index} has no matching catdisent."
        )
    return exact_cost


def _catent_ebit_count(
    catent: CleanedQuantumGate,
    statements: Sequence[object],
    catent_index: int,
) -> float:
    """Return e-bit count represented by one ``catent`` statement."""
    if len(catent.qubits) < 2:
        raise ValueError(
            "catent must contain at least two data operands. "
            f"Received {catent.qubits!r}."
        )

    comm_operand_count = len(catent.qubits) - 2
    if comm_operand_count > 0:
        if comm_operand_count % 2 != 0:
            raise ValueError(
                "catent communication operands must be paired. "
                f"Received {catent.qubits!r}."
            )
        if any(
            not qubit.register_name.startswith("c")
            for qubit in catent.qubits[2:]
        ):
            raise ValueError(
                "catent communication operands must use communication "
                f"registers. Received {catent.qubits!r}."
            )
        return float(comm_operand_count // 2)

    wrapped_statement = _next_quantum_gate_statement(
        statements,
        start_index=catent_index + 1,
    )
    return 2.0 if wrapped_statement.name == "rswap" else 1.0


def _next_quantum_gate_statement(
    statements: Sequence[object],
    *,
    start_index: int,
) -> CleanedQuantumGate:
    """Return the next quantum gate statement after ``start_index``."""
    for statement in statements[start_index:]:
        if isinstance(statement, CleanedQuantumGate):
            return statement
    raise ValueError("catent has no following quantum gate to wrap.")
