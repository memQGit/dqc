"""Run simple makespan benchmarks for the DES scheduler variants.

Most cases mirror the compiler pipeline used by
``scripts/samples/full_algo_sample.py``:

1. Load a QASM circuit and network topology.
2. Partition the circuit with the standard ``Interaction`` partitioner.
3. Extract the distributed circuit with scheduler-assigned e-bits.
4. Run each DES-based scheduler on the same distributed circuit.
5. Print makespan comparisons to the terminal.

The suite also includes one scheduler-only synthetic case that exposes
link-arbitration differences more directly than the current compiler DAGs.
"""

from __future__ import annotations

import argparse
import logging
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import cast

import networkx as nx
from openqasm3 import ast

from memq_dqc.circuit import DistributedCircuit
from memq_dqc.circuit.dag import DistributedCircuitDAG
from memq_dqc.circuit.op import Op
from memq_dqc.network import NetworkGraph, PhysicalQubit
from memq_dqc.partition import Partitioner
from memq_dqc.preprocessing.qasm.io import load_qasm_program
from memq_dqc.preprocessing.qasm.types import CircuitQubit
from memq_dqc.scheduler import (
    DESLinkCriticalPathScheduler,
    DESLinkFIFOScheduler,
    DESLinkShortestDurationScheduler,
    Scheduler,
    SchedulerHardwareProfile,
)
from memq_dqc.scheduler.des_link_scheduler import (
    BaseDESLinkScheduler,
    _LinkState,
    _QueueEvent,
)
from memq_dqc.settings import load_settings

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_COMPILER_ALGO = "interaction"
DEFAULT_DES_ALGORITHMS: tuple[str, ...] = (
    "des_link_fifo",
    "des_link_shortest_duration",
    "des_link_critical_path",
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class SchedulerArbitrationStats:
    """Link-arbitration diagnostics for one DES scheduler run.

    Attributes:
        pending_enqueues: Number of link requests that entered a pending queue.
        policy_pops: Number of pending requests selected by the link policy.
        multi_candidate_decisions: Number of selections with more than one
            pending request available.
        same_time_batches: Number of same-time same-link request batches.
        non_fifo_selections: Number of multi-candidate selections that did not
            pick the oldest pending request.
        max_pending_depth: Largest observed pending queue depth.
    """

    pending_enqueues: int = 0
    policy_pops: int = 0
    multi_candidate_decisions: int = 0
    same_time_batches: int = 0
    non_fifo_selections: int = 0
    max_pending_depth: int = 0


@dataclass(slots=True)
class _MutableSchedulerArbitrationStats:
    """Mutable accumulator for link-arbitration diagnostics."""

    pending_enqueues: int = 0
    policy_pops: int = 0
    multi_candidate_decisions: int = 0
    same_time_batches: int = 0
    non_fifo_selections: int = 0
    max_pending_depth: int = 0

    def frozen(self) -> SchedulerArbitrationStats:
        """Return an immutable copy for benchmark output."""
        return SchedulerArbitrationStats(
            pending_enqueues=self.pending_enqueues,
            policy_pops=self.policy_pops,
            multi_candidate_decisions=self.multi_candidate_decisions,
            same_time_batches=self.same_time_batches,
            non_fifo_selections=self.non_fifo_selections,
            max_pending_depth=self.max_pending_depth,
        )


class _BenchmarkArbitrationMixin:
    """Collect link-arbitration diagnostics while running a DES scheduler."""

    def _reset_run_state(self) -> None:
        cast(BaseDESLinkScheduler, super())._reset_run_state()
        self._benchmark_arbitration_stats = _MutableSchedulerArbitrationStats()

    def _collect_same_time_link_start_requests(
        self,
        event: _QueueEvent,
    ) -> tuple[int, ...]:
        op_ids = cast(
            BaseDESLinkScheduler,
            super(),
        )._collect_same_time_link_start_requests(event)
        if len(op_ids) > 1:
            self._benchmark_arbitration_stats.same_time_batches += 1
        return op_ids

    def _enqueue_pending_request(
        self,
        link_state: _LinkState,
        op_id: int,
    ) -> None:
        before_depth = len(link_state.pending_requests)
        cast(BaseDESLinkScheduler, super())._enqueue_pending_request(
            link_state,
            op_id,
        )
        after_depth = len(link_state.pending_requests)
        if after_depth <= before_depth:
            return

        self._benchmark_arbitration_stats.pending_enqueues += 1
        self._benchmark_arbitration_stats.max_pending_depth = max(
            self._benchmark_arbitration_stats.max_pending_depth,
            after_depth,
        )

    def _pop_next_pending_request(
        self,
        link_state: _LinkState,
        *,
        link_key: tuple[str, str],
        time: float,
    ) -> int | None:
        pending_before = tuple(
            pending_request.op_id
            for pending_request in link_state.pending_requests
        )
        selected_op_id = cast(
            BaseDESLinkScheduler,
            super(),
        )._pop_next_pending_request(
            link_state,
            link_key=link_key,
            time=time,
        )
        if selected_op_id is None:
            return None

        self._benchmark_arbitration_stats.policy_pops += 1
        if len(pending_before) > 1:
            self._benchmark_arbitration_stats.multi_candidate_decisions += 1
            if selected_op_id != pending_before[0]:
                self._benchmark_arbitration_stats.non_fifo_selections += 1
        return selected_op_id

    def arbitration_stats(self) -> SchedulerArbitrationStats:
        """Return diagnostics collected during the most recent run."""
        return self._benchmark_arbitration_stats.frozen()


_DES_LINK_SCHEDULER_CLASSES: dict[str, type[BaseDESLinkScheduler]] = {
    "des_link_fifo": DESLinkFIFOScheduler,
    "des_link_shortest_duration": DESLinkShortestDurationScheduler,
    "des_link_critical_path": DESLinkCriticalPathScheduler,
}
_INSTRUMENTED_SCHEDULER_CLASSES: dict[str, type[BaseDESLinkScheduler]] = {}


def _instrumented_scheduler_class(
    algorithm: str,
) -> type[BaseDESLinkScheduler]:
    """Return an instrumented scheduler class for a DES-link algorithm."""
    scheduler_class = _INSTRUMENTED_SCHEDULER_CLASSES.get(algorithm)
    if scheduler_class is not None:
        return scheduler_class

    base_class = _DES_LINK_SCHEDULER_CLASSES[algorithm]
    scheduler_class = cast(
        type[BaseDESLinkScheduler],
        type(
            f"Benchmark{base_class.__name__}",
            (_BenchmarkArbitrationMixin, base_class),
            {},
        ),
    )
    _INSTRUMENTED_SCHEDULER_CLASSES[algorithm] = scheduler_class
    return scheduler_class


@dataclass(frozen=True, slots=True)
class SchedulerBenchmarkResult:
    """Benchmark output for one scheduler run.

    Attributes:
        algorithm: Scheduler registry name.
        makespan: Final schedule makespan.
        operation_count: Number of scheduled visible events.
        arbitration: Optional link-arbitration diagnostics.
    """

    algorithm: str
    makespan: float
    operation_count: int
    arbitration: SchedulerArbitrationStats | None = None


@dataclass(frozen=True, slots=True)
class BenchmarkCase:
    """One named scheduler benchmark input.

    Attributes:
        name: Short terminal-friendly case identifier.
        circuit_path: OpenQASM benchmark input for compiler-driven cases.
        network_path: Network benchmark input for compiler-driven cases.
        compiler_algo: Partitioner algorithm used to compile the circuit.
        builder: Optional scheduler-only distributed-circuit builder.
        description: Plain-text summary of what the case is meant to stress.
    """

    name: str
    description: str
    circuit_path: Path | None = None
    network_path: Path | None = None
    compiler_algo: str | None = None
    builder: Callable[[], DistributedCircuit] | None = None


@dataclass(frozen=True, slots=True)
class _SyntheticDAG:
    """Minimal DAG container for scheduler-only benchmark cases."""

    graph: nx.DiGraph


def _remote_gate(
    *,
    op_id: int,
    name: str,
    data_register_a: str,
    data_register_b: str,
) -> Op:
    """Return one synthetic remote operation on a shared communication link."""
    qubits: tuple[CircuitQubit, ...] = (
        CircuitQubit(register_name=data_register_a, index=0),
        CircuitQubit(register_name=data_register_b, index=0),
        CircuitQubit(register_name="c0", index=0),
        CircuitQubit(register_name="c1", index=0),
    )
    if name == "rswap":
        qubits += (
            CircuitQubit(register_name="c0", index=1),
            CircuitQubit(register_name="c1", index=1),
        )

    return Op(
        op_id=op_id,
        statement_id=op_id,
        name=name,
        is_remote=True,
        qubits=qubits,
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier(name),
            arguments=[],
            qubits=[],
        ),
    )


def _deferred_remote_gate(
    *,
    op_id: int,
    name: str,
    data_register_a: str,
    data_register_b: str,
) -> Op:
    """Return one synthetic remote operation without assigned e-bit qubits."""
    return Op(
        op_id=op_id,
        statement_id=op_id,
        name=name,
        is_remote=True,
        qubits=(
            CircuitQubit(register_name=data_register_a, index=0),
            CircuitQubit(register_name=data_register_b, index=0),
        ),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier(name),
            arguments=[],
            qubits=[],
        ),
    )


def _local_gate(*, op_id: int, name: str, register_name: str) -> Op:
    """Return one synthetic local single-qubit operation."""
    return Op(
        op_id=op_id,
        statement_id=op_id,
        name=name,
        is_remote=False,
        qubits=(CircuitQubit(register_name=register_name, index=0),),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier(name),
            arguments=[],
            qubits=[],
        ),
    )


def _comm_pair(
    left_qpu_id: int,
    left_qubit_id: int,
    right_qpu_id: int,
    right_qubit_id: int,
) -> tuple[PhysicalQubit, PhysicalQubit]:
    """Return one synthetic physical communication-qubit pair."""
    return (
        PhysicalQubit(left_qpu_id, left_qubit_id, "communication"),
        PhysicalQubit(right_qpu_id, right_qubit_id, "communication"),
    )


def _distributed_circuit_from_ops(
    *,
    ops: list[Op],
    graph_edges: Sequence[tuple[int, int]] = (),
    ebit_candidates_by_op_id: (
        dict[
            int,
            tuple[
                tuple[tuple[PhysicalQubit, PhysicalQubit], ...],
                ...,
            ],
        ]
        | None
    ) = None,
) -> DistributedCircuit:
    """Return a scheduler-only distributed circuit from synthetic operations."""
    graph = nx.DiGraph()
    for op in ops:
        graph.add_node(op.op_id, op=op)
    for predecessor, successor in graph_edges:
        graph.add_edge(predecessor, successor)

    return DistributedCircuit(
        program=ast.Program(statements=[], version="3.0"),
        statements=[],
        ops=ops,
        num_two_qubit_gates=sum(1 for op in ops if op.is_remote),
        num_remote_gates=sum(1 for op in ops if op.is_remote),
        num_local_swaps_added=0,
        dag=cast(DistributedCircuitDAG, _SyntheticDAG(graph=graph)),
        ebit_candidates_by_op_id=ebit_candidates_by_op_id,
    )


def _build_link_arbitration_divergence_case() -> DistributedCircuit:
    """Return a synthetic case where the DES variants choose differently.

    The first remote operation grabs the only shared link immediately.
    Three more remote requests queue behind it on that same link:

    - one long ``rswap`` request with no downstream work,
    - one short ``rcx`` request with no downstream work,
    - one short ``rcx`` request followed by a long local tail.

    This setup creates a clear separation between:

    - FIFO order,
    - shortest-duration-first order, and
    - critical-path-first order.
    """
    ops = [
        _remote_gate(
            op_id=0,
            name="rcx",
            data_register_a="q10",
            data_register_b="q11",
        ),
        _remote_gate(
            op_id=1,
            name="rswap",
            data_register_a="q0",
            data_register_b="q1",
        ),
        _remote_gate(
            op_id=2,
            name="rcx",
            data_register_a="q2",
            data_register_b="q3",
        ),
        _remote_gate(
            op_id=3,
            name="rcx",
            data_register_a="q4",
            data_register_b="q5",
        ),
        _local_gate(op_id=4, name="x", register_name="q4"),
        _local_gate(op_id=5, name="h", register_name="q4"),
        _local_gate(op_id=6, name="z", register_name="q4"),
        _local_gate(op_id=7, name="x", register_name="q4"),
        _local_gate(op_id=8, name="h", register_name="q4"),
    ]

    return _distributed_circuit_from_ops(
        ops=ops,
        graph_edges=((3, 4), (4, 5), (5, 6), (6, 7), (7, 8)),
    )


def _build_shortest_vs_tail_contention_case() -> DistributedCircuit:
    """Return a single-link case with duration and tail-priority conflict."""
    ops = [
        _remote_gate(
            op_id=0,
            name="rcx",
            data_register_a="q20",
            data_register_b="q21",
        ),
        _remote_gate(
            op_id=1,
            name="rswap",
            data_register_a="q0",
            data_register_b="q1",
        ),
        _remote_gate(
            op_id=2,
            name="rcx",
            data_register_a="q2",
            data_register_b="q3",
        ),
        _remote_gate(
            op_id=3,
            name="rcx",
            data_register_a="q4",
            data_register_b="q5",
        ),
        _remote_gate(
            op_id=4,
            name="rswap",
            data_register_a="q6",
            data_register_b="q7",
        ),
        _local_gate(op_id=5, name="x", register_name="q4"),
        _local_gate(op_id=6, name="h", register_name="q4"),
        _local_gate(op_id=7, name="z", register_name="q4"),
        _local_gate(op_id=8, name="x", register_name="q4"),
        _local_gate(op_id=9, name="h", register_name="q4"),
        _local_gate(op_id=10, name="z", register_name="q4"),
    ]
    return _distributed_circuit_from_ops(
        ops=ops,
        graph_edges=(
            (3, 5),
            (5, 6),
            (6, 7),
            (7, 8),
            (8, 9),
            (9, 10),
        ),
    )


def _build_initial_link_policy_contention_case() -> DistributedCircuit:
    """Return a case where the first idle-link request differs by policy."""
    ops = [
        _remote_gate(
            op_id=0,
            name="rswap",
            data_register_a="q0",
            data_register_b="q1",
        ),
        _remote_gate(
            op_id=1,
            name="rcx",
            data_register_a="q2",
            data_register_b="q3",
        ),
        _remote_gate(
            op_id=2,
            name="rcx",
            data_register_a="q4",
            data_register_b="q5",
        ),
        _local_gate(op_id=3, name="x", register_name="q4"),
        _local_gate(op_id=4, name="h", register_name="q4"),
        _local_gate(op_id=5, name="z", register_name="q4"),
        _local_gate(op_id=6, name="x", register_name="q4"),
        _local_gate(op_id=7, name="h", register_name="q4"),
        _local_gate(op_id=8, name="z", register_name="q4"),
        _local_gate(op_id=9, name="x", register_name="q4"),
        _local_gate(op_id=10, name="h", register_name="q4"),
    ]
    return _distributed_circuit_from_ops(
        ops=ops,
        graph_edges=(
            (2, 3),
            (3, 4),
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 8),
            (8, 9),
            (9, 10),
        ),
    )


def _build_critical_path_fanout_contention_case() -> DistributedCircuit:
    """Return a single-link fanout case with uneven downstream tails."""
    ops = [
        _remote_gate(
            op_id=0,
            name="rcx",
            data_register_a="q30",
            data_register_b="q31",
        ),
        _remote_gate(
            op_id=1,
            name="rcx",
            data_register_a="q0",
            data_register_b="q1",
        ),
        _remote_gate(
            op_id=2,
            name="rcx",
            data_register_a="q2",
            data_register_b="q3",
        ),
        _remote_gate(
            op_id=3,
            name="rcx",
            data_register_a="q4",
            data_register_b="q5",
        ),
        _remote_gate(
            op_id=4,
            name="rcx",
            data_register_a="q6",
            data_register_b="q7",
        ),
        _local_gate(op_id=5, name="x", register_name="q6"),
        _local_gate(op_id=6, name="h", register_name="q6"),
        _local_gate(op_id=7, name="z", register_name="q6"),
        _local_gate(op_id=8, name="x", register_name="q6"),
        _local_gate(op_id=9, name="h", register_name="q6"),
        _local_gate(op_id=10, name="z", register_name="q6"),
        _local_gate(op_id=11, name="x", register_name="q6"),
        _local_gate(op_id=12, name="h", register_name="q6"),
    ]
    return _distributed_circuit_from_ops(
        ops=ops,
        graph_edges=(
            (4, 5),
            (5, 6),
            (6, 7),
            (7, 8),
            (8, 9),
            (9, 10),
            (10, 11),
            (11, 12),
        ),
    )


def _build_deferred_two_lane_mixed_contention_case() -> DistributedCircuit:
    """Return a deferred e-bit case with two overloaded candidate lanes."""
    lane_a = _comm_pair(0, 0, 1, 0)
    lane_b = _comm_pair(0, 1, 1, 1)
    lane_c = _comm_pair(0, 2, 1, 2)
    lane_d = _comm_pair(0, 3, 1, 3)
    rcx_candidates = ((lane_a,), (lane_c,))
    rswap_candidates = ((lane_a, lane_b), (lane_c, lane_d))

    ops = [
        _deferred_remote_gate(
            op_id=0,
            name="rcx",
            data_register_a="q0",
            data_register_b="q1",
        ),
        _deferred_remote_gate(
            op_id=1,
            name="rcx",
            data_register_a="q2",
            data_register_b="q3",
        ),
        _deferred_remote_gate(
            op_id=2,
            name="rswap",
            data_register_a="q4",
            data_register_b="q5",
        ),
        _deferred_remote_gate(
            op_id=3,
            name="rcx",
            data_register_a="q6",
            data_register_b="q7",
        ),
        _deferred_remote_gate(
            op_id=4,
            name="rswap",
            data_register_a="q8",
            data_register_b="q9",
        ),
        _deferred_remote_gate(
            op_id=5,
            name="rcx",
            data_register_a="q10",
            data_register_b="q11",
        ),
        _local_gate(op_id=6, name="x", register_name="q10"),
        _local_gate(op_id=7, name="h", register_name="q10"),
        _local_gate(op_id=8, name="z", register_name="q10"),
        _local_gate(op_id=9, name="x", register_name="q10"),
        _local_gate(op_id=10, name="h", register_name="q10"),
    ]

    return _distributed_circuit_from_ops(
        ops=ops,
        graph_edges=((5, 6), (6, 7), (7, 8), (8, 9), (9, 10)),
        ebit_candidates_by_op_id={
            0: rcx_candidates,
            1: rcx_candidates,
            2: rswap_candidates,
            3: rcx_candidates,
            4: rswap_candidates,
            5: rcx_candidates,
        },
    )


BENCHMARK_CASES: tuple[BenchmarkCase, ...] = (
    BenchmarkCase(
        name="synthetic_link_arbitration_divergence",
        builder=_build_link_arbitration_divergence_case,
        description=(
            "Scheduler-only synthetic case that forces three queued remote "
            "requests to compete for the same link."
        ),
    ),
    BenchmarkCase(
        name="inter_swap_chain",
        circuit_path=(
            REPO_ROOT / "benchmarking" / "circuits" / "inter_swap_test.qasm"
        ),
        network_path=REPO_ROOT / "benchmarking" / "networks" / "4x6x4.json",
        compiler_algo=DEFAULT_COMPILER_ALGO,
        description=(
            "Larger three-QPU chain-like example taken from the existing full "
            "algorithm sample."
        ),
    ),
    BenchmarkCase(
        name="synthetic_shortest_vs_tail_contention",
        builder=_build_shortest_vs_tail_contention_case,
        description=(
            "Scheduler-only single-link case mixing long rswap requests, "
            "short rcx requests, and a dependent tail."
        ),
    ),
    BenchmarkCase(
        name="synthetic_initial_link_policy_contention",
        builder=_build_initial_link_policy_contention_case,
        description=(
            "Scheduler-only same-time idle-link contention case where FIFO, "
            "shortest-duration, and critical-path choose different first "
            "remote starts."
        ),
    ),
    BenchmarkCase(
        name="synthetic_critical_path_fanout_contention",
        builder=_build_critical_path_fanout_contention_case,
        description=(
            "Scheduler-only single-link case where several equal-duration "
            "remote branches have very different downstream tails."
        ),
    ),
    BenchmarkCase(
        name="synthetic_deferred_two_lane_mixed_contention",
        builder=_build_deferred_two_lane_mixed_contention_case,
        description=(
            "Scheduler-only deferred e-bit case where rcx and rswap requests "
            "choose between two overloaded communication-lane groups."
        ),
    ),
    BenchmarkCase(
        name="qv_12_line_topology",
        circuit_path=(
            REPO_ROOT / "benchmarking" / "circuits" / "qv_12_line_seed7.qasm"
        ),
        network_path=(
            REPO_ROOT
            / "benchmarking"
            / "networks"
            / "line_4qpu_3qubits_each.json"
        ),
        compiler_algo=DEFAULT_COMPILER_ALGO,
        description=(
            "Seeded 12-qubit quantum volume circuit on a four-QPU line "
            "topology where processors 1-2-3-4 form a chain."
        ),
    ),
    BenchmarkCase(
        name="critical_path_contention",
        circuit_path=(
            REPO_ROOT
            / "benchmarking"
            / "circuits"
            / "critical_path_contention.qasm"
        ),
        network_path=(
            REPO_ROOT / "benchmarking" / "networks" / "3comp_1comm_x2.json"
        ),
        compiler_algo=DEFAULT_COMPILER_ALGO,
        description=(
            "Two remote CX branches on a single-link topology, with extra "
            "dependent work on one branch."
        ),
    ),
    BenchmarkCase(
        name="single_link_remote_pressure",
        circuit_path=(
            REPO_ROOT
            / "benchmarking"
            / "circuits"
            / "single_link_remote_pressure.qasm"
        ),
        network_path=(
            REPO_ROOT / "benchmarking" / "networks" / "3comp_1comm_x2.json"
        ),
        compiler_algo=DEFAULT_COMPILER_ALGO,
        description=(
            "Several remote CX operations share the same single communication "
            "link."
        ),
    ),
)


def parse_args() -> argparse.Namespace:
    """Return parsed CLI arguments for the benchmark runner."""
    parser = argparse.ArgumentParser(
        description=(
            "Benchmark the DES scheduler variants across compiler-driven or "
            "synthetic distributed circuits."
        )
    )
    parser.add_argument(
        "--case",
        action="append",
        dest="cases",
        help=(
            "Benchmark case name to run. May be passed multiple times. "
            "Defaults to all built-in cases."
        ),
    )
    parser.add_argument(
        "--list-cases",
        action="store_true",
        help="List available benchmark cases and exit.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Random seed reused across all DES scheduler runs.",
    )
    return parser.parse_args()


def configure_logging() -> None:
    """Configure terminal logging for the benchmark run."""
    logging.basicConfig(level=logging.INFO, format="%(message)s")


def _display_path(path: Path) -> str:
    """Return a readable path, relative to the repo when possible."""
    try:
        return str(path.resolve().relative_to(REPO_ROOT))
    except ValueError:
        return str(path.resolve())


def resolve_cases(
    selected_case_names: Sequence[str] | None,
) -> list[BenchmarkCase]:
    """Return the requested benchmark cases by name.

    Args:
        selected_case_names: Optional user-selected case names.

    Returns:
        The resolved benchmark cases in definition order.

    Raises:
        ValueError: If any requested case name is unknown.
    """
    if not selected_case_names:
        return list(BENCHMARK_CASES)

    available_cases = {case.name: case for case in BENCHMARK_CASES}
    missing_cases = [
        case_name
        for case_name in selected_case_names
        if case_name not in available_cases
    ]
    if missing_cases:
        available_names = ", ".join(sorted(available_cases))
        raise ValueError(
            "Unknown benchmark case(s): "
            f"{', '.join(missing_cases)}. Available cases: {available_names}."
        )

    seen_case_names: set[str] = set()
    resolved_cases: list[BenchmarkCase] = []
    for case_name in selected_case_names:
        if case_name in seen_case_names:
            continue
        resolved_cases.append(available_cases[case_name])
        seen_case_names.add(case_name)
    return resolved_cases


def list_cases() -> None:
    """Print the available benchmark cases to the terminal."""
    for case in BENCHMARK_CASES:
        print(f"{case.name}: {case.description}")


def _log_distributed_circuit_summary(
    distributed_circuit: DistributedCircuit,
) -> None:
    """Print circuit size information for one benchmark case."""
    remote_name_counts = Counter(
        op.name for op in distributed_circuit.ops if op.is_remote
    )
    remote_operation_count = sum(remote_name_counts.values())
    logger.info(
        "Distributed ops: %d, remote/swap ops: %d, remote gates: %d",
        len(distributed_circuit.ops),
        remote_operation_count,
        distributed_circuit.num_remote_gates,
    )
    if remote_name_counts:
        logger.info(
            "Remote op mix: %s", dict(sorted(remote_name_counts.items()))
        )


def build_compiled_distributed_circuit(
    *,
    circuit_path: Path,
    network_path: Path,
    compiler_algo: str,
) -> DistributedCircuit:
    """Compile one monolithic circuit into a distributed circuit.

    Args:
        circuit_path: Benchmark QASM file.
        network_path: Benchmark network file.
        compiler_algo: Partitioner algorithm used during compilation.

    Returns:
        The distributed circuit produced by the compiler pipeline.

    Raises:
        RuntimeError: If the distributed circuit is not created.
    """
    qasm_program = load_qasm_program(str(circuit_path))
    network_graph = NetworkGraph(str(network_path))
    partitioner = Partitioner(
        network_graph,
        qasm_program,
        algo=compiler_algo,
    )
    partitioner.run(verbosity="quiet", ebit_assignment=False)

    distributed_circuit = partitioner.circuit.distributed
    if distributed_circuit is None:
        raise RuntimeError("Distributed circuit was not created.")

    logger.info("Partition windows: %d", len(partitioner.windows or []))
    return distributed_circuit


def build_case_distributed_circuit(case: BenchmarkCase) -> DistributedCircuit:
    """Return one distributed circuit for a benchmark case."""
    logger.info("Case: %s", case.name)
    if case.builder is not None:
        logger.info("Case type: synthetic scheduler stress case")
        distributed_circuit = case.builder()
        _log_distributed_circuit_summary(distributed_circuit)
        return distributed_circuit

    if (
        case.circuit_path is None
        or case.network_path is None
        or case.compiler_algo is None
    ):
        raise RuntimeError(
            f"Benchmark case {case.name!r} is missing compiler inputs."
        )

    logger.info("Compiler algorithm: %s", case.compiler_algo)
    logger.info("Circuit: %s", _display_path(case.circuit_path))
    logger.info("Network: %s", _display_path(case.network_path))
    distributed_circuit = build_compiled_distributed_circuit(
        circuit_path=case.circuit_path,
        network_path=case.network_path,
        compiler_algo=case.compiler_algo,
    )
    _log_distributed_circuit_summary(distributed_circuit)
    return distributed_circuit


def benchmark_des_algorithms(
    *,
    distributed_circuit: DistributedCircuit,
    algorithms: Sequence[str],
    seed: int,
) -> list[SchedulerBenchmarkResult]:
    """Run one distributed circuit through the requested DES schedulers.

    Args:
        distributed_circuit: Distributed circuit shared by all runs.
        algorithms: DES scheduler registry names to benchmark.
        seed: Random seed reused for each scheduler run.

    Returns:
        One benchmark result per scheduler.

    Raises:
        RuntimeError: If a scheduler does not produce a schedule.
    """
    hardware_profile = SchedulerHardwareProfile.neutral_atom(
        entanglement_profile="neutral_atom.polarization"
    )
    results: list[SchedulerBenchmarkResult] = []
    for algorithm in algorithms:
        arbitration_stats: SchedulerArbitrationStats | None = None
        if algorithm in _DES_LINK_SCHEDULER_CLASSES:
            scheduler_class = _instrumented_scheduler_class(algorithm)
            des_scheduler = scheduler_class(
                distributed_circuit,
                profile=hardware_profile,
                seed=seed,
            )
            des_scheduler.run()
            schedule = des_scheduler.schedule
            arbitration_stats = cast(
                _BenchmarkArbitrationMixin,
                des_scheduler,
            ).arbitration_stats()
        else:
            scheduler = Scheduler(
                distributed_circuit,
                algo=algorithm,
                profile=hardware_profile,
                algo_kwargs={"seed": seed},
            )
            scheduler.run(verbosity="quiet")
            schedule = scheduler.schedule
        if schedule is None:
            raise RuntimeError(
                f"Scheduler {algorithm!r} did not produce a schedule."
            )

        results.append(
            SchedulerBenchmarkResult(
                algorithm=algorithm,
                makespan=schedule.makespan,
                operation_count=len(schedule.operations),
                arbitration=arbitration_stats,
            )
        )
    return results


def log_benchmark_results(results: Sequence[SchedulerBenchmarkResult]) -> None:
    """Print benchmark results and a simple ranking to the terminal."""
    if not results:
        logger.info("No scheduler results were produced.")
        return

    time_unit = load_settings().global_settings.time_unit or "time units"
    logger.info("")
    logger.info("DES Scheduler Makespan Comparison")
    logger.info("--------------------------------")
    for result in results:
        arbitration_suffix = ""
        if result.arbitration is not None:
            arbitration_suffix = (
                " link_choices="
                f"{result.arbitration.multi_candidate_decisions:4d}"
                " non_fifo="
                f"{result.arbitration.non_fifo_selections:4d}"
                " batches="
                f"{result.arbitration.same_time_batches:4d}"
                " maxq="
                f"{result.arbitration.max_pending_depth:3d}"
            )
        logger.info(
            "%-28s makespan=%10.3f %s operations=%4d%s",
            result.algorithm,
            result.makespan,
            time_unit,
            result.operation_count,
            arbitration_suffix,
        )

    best_result = min(results, key=lambda result: result.makespan)
    logger.info("")
    logger.info(
        "Best makespan: %s (%.3f %s)",
        best_result.algorithm,
        best_result.makespan,
        time_unit,
    )
    if len({result.makespan for result in results}) == 1:
        logger.info(
            "Note: all DES variants tied on this case. The compiled "
            "distributed DAG may already serialize same-link reuse."
        )
        arbitration_stats = [
            result.arbitration
            for result in results
            if result.arbitration is not None
        ]
        if arbitration_stats and all(
            stats.multi_candidate_decisions == 0 for stats in arbitration_stats
        ):
            logger.info(
                "Arbitration diagnostic: no link policy ever chose among "
                "multiple pending requests."
            )
        elif arbitration_stats and all(
            stats.non_fifo_selections == 0 for stats in arbitration_stats
        ):
            logger.info(
                "Arbitration diagnostic: multi-candidate choices occurred, "
                "but every policy selected the FIFO candidate."
            )
        elif arbitration_stats:
            logger.info(
                "Arbitration diagnostic: policies made different link choices, "
                "but those choices did not change this case's makespan."
            )


def main() -> None:
    """Run the DES scheduler benchmark from the command line."""
    args = parse_args()
    if args.list_cases:
        list_cases()
        return

    configure_logging()
    cases = resolve_cases(args.cases)
    for index, case in enumerate(cases):
        if index > 0:
            logger.info("")
            logger.info("=" * 72)
            logger.info("")
        logger.info("%s", case.description)
        try:
            distributed_circuit = build_case_distributed_circuit(case)
            results = benchmark_des_algorithms(
                distributed_circuit=distributed_circuit,
                algorithms=DEFAULT_DES_ALGORITHMS,
                seed=args.seed,
            )
        except (RuntimeError, ValueError) as exc:
            logger.info("Benchmark case failed: %s", exc)
            continue
        log_benchmark_results(results)


if __name__ == "__main__":
    main()
