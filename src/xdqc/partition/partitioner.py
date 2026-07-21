# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Partitioner interfaces.

Goal of partitioner is to create standardized
entry point for different partitioning algorithms, providing them with all
of the necessary data to perform partitioning.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from os import PathLike
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, TypeVar, cast

from openqasm3 import ast

from xdqc._logging import StepTimer, workflow_logging
from xdqc.circuit import Circuit
from xdqc.circuit.op import Op
from xdqc.network import NetworkGraph
from xdqc.preprocessing.qasm.io import (
    dump_qasm_program,
    load_qasm_program,
    parse_qasm_source,
)

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    import networkx as nx

    from xdqc.circuit import DistributedCircuit
    from xdqc.scheduler.schedule import SchedulerHardwareProfile


@dataclass(frozen=True, slots=True)
class QPU:
    """Represents a QPU identifier for partition assignments."""

    id: int


PartitionSchedule = list[dict[QPU, set[int]]]
PartitionWindows = list[list[Op]]
NetworkInput: TypeAlias = NetworkGraph | str | PathLike[str]
ProgramInput: TypeAlias = ast.Program | str | PathLike[str]

_Algorithm = TypeVar("_Algorithm", bound="BasePartitioner")


class BasePartitioner(ABC):
    """Base class for partitioning algorithm implementations."""

    def __init__(
        self,
        network: NetworkGraph,
        program: ast.Program,
        *,
        seed: int | None = None,
    ) -> None:
        """Initialize the partitioner with circuit and network inputs.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
            seed: Optional seed for algorithms with random components.
                Deterministic algorithms record it but may ignore it.
        """
        self.network = network
        self.circuit = Circuit(program)
        self.seed = seed
        self._reported_cost: float | None = None
        self._exact_cost: float | None = None
        self.schedule: PartitionSchedule | None = None
        self.windows: PartitionWindows | None = None

    @abstractmethod
    def run(self) -> None:
        """Run the partitioning algorithm.

        Updates:
            cost, schedule, and windows with the latest partitioning results.
        """
        raise NotImplementedError

    @property
    def cost(self) -> float | None:
        """Return the latest entanglement cost, if available.

        When a schedule and windowing are available, cost is derived from the
        total routed e-bit usage implied by remote gates and inter-window
        qubit movement.
        """
        if self._exact_cost is not None:
            return self._exact_cost

        schedule = self.schedule
        windows = self.windows
        if (
            schedule is None
            or windows is None
            or len(schedule) != len(windows)
        ):
            return self._reported_cost

        return _total_schedule_ebit_cost(schedule, windows, self.network)

    @cost.setter
    def cost(self, value: float | None) -> None:
        """Store an algorithm-reported cost estimate."""
        self._reported_cost = value
        self._exact_cost = None

    def _set_exact_cost(self, value: float | None) -> None:
        """Store an exact entanglement cost override."""
        self._exact_cost = value


class Partitioner:
    """Orchestrate a partitioning algorithm implementation."""

    def __init__(
        self,
        network: NetworkInput | ProgramInput,
        program: ProgramInput | NetworkInput,
        *,
        algo: str | type[_Algorithm] | _Algorithm = "interaction",
        algo_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the partitioner and select the algorithm.

        Args:
            network: Network graph or parsed OpenQASM 3 program, or a path
                to either input type. When both positional inputs are file
                paths or in-memory objects, the constructor infers which one
                is the network and which one is the program.
            program: Parsed OpenQASM 3 program or network graph, or a path to
                either input type. When both positional inputs are file paths
                or in-memory objects, the constructor infers which one is the
                network and which one is the program.
            algo: Algorithm name, class, or preconfigured instance.
            algo_kwargs: Keyword arguments forwarded to the algorithm.
        """
        resolved_network, resolved_program = _resolve_partitioner_inputs(
            network, program
        )
        self._algorithm = self._resolve_algorithm(
            resolved_network, resolved_program, algo, algo_kwargs
        )
        self._distributed_ebit_assignment = True
        self._distributed_group_gates = True
        self._distributed_max_group_size: int | None = None
        self._distributed_group_size_profile: (
            SchedulerHardwareProfile | None
        ) = None

    def run(
        self,
        *,
        ebit_assignment: bool | None = None,
        group_gates: bool = True,
        max_group_size: int | None = None,
        group_size_profile: SchedulerHardwareProfile | None = None,
        verbosity: Literal["quiet", "info", "debug"] = "quiet",
    ) -> None:
        """Run the configured partitioning algorithm.

        Args:
            ebit_assignment: Whether to also extract the distributed circuit
                during this call, and if so whether the compiler assigns
                concrete e-bit pairs into the scheduler DAG. When omitted,
                this method only runs partitioning and lazy extraction
                defaults to explicit e-bit assignment.
            group_gates: Whether distributed extraction should keep compatible
                remote gate groups inside a shared cat-entanglement region.
            max_group_size: Optional maximum number of two-qubit gates per
                emitted gate group.
            group_size_profile: Scheduler hardware profile whose timing bounds
                each gate group's duration to the EPR lifetime. When omitted
                the EPR-lifetime cap is disabled.
            verbosity: Logging verbosity for this workflow call.

        Updates:
            cost, schedule, and windows with the latest partitioning results.
        """
        if max_group_size is not None and max_group_size < 1:
            raise ValueError("max_group_size must be positive when provided.")
        self.circuit.distributed = None
        self._distributed_ebit_assignment = (
            True if ebit_assignment is None else ebit_assignment
        )
        self._distributed_group_gates = group_gates
        self._distributed_max_group_size = max_group_size
        self._distributed_group_size_profile = group_size_profile
        with workflow_logging(verbosity):
            timer = StepTimer()
            logger.info(
                "Starting partitioning with %s.",
                type(self._algorithm).__name__,
            )
            self._algorithm.run()
            schedule = self._algorithm.schedule
            if not schedule:
                logger.warning(
                    "Partitioning finished without a partition schedule "
                    "after %.3fs.",
                    timer.elapsed_seconds(),
                )
                return

            initial_mapping = _circuit_qubit_physical_map(schedule[0])
            final_mapping = _circuit_qubit_physical_map(schedule[-1])
            final_window_idx = len(schedule) - 1
            logger.info(
                "Partitioning completed in %.3fs: windows=%d cost=%s.",
                timer.elapsed_seconds(),
                len(schedule),
                self._algorithm.cost,
            )
            logger.debug(
                "Initial logical->physical mapping (window 0): %s",
                initial_mapping,
            )
            logger.debug(
                "Final logical->physical mapping (window %d): %s",
                final_window_idx,
                final_mapping,
            )
            if ebit_assignment is not None:
                self._ensure_distributed_circuit(verbosity=verbosity)

    @property
    def cost(self) -> float | None:
        """Return the latest entanglement cost, if available."""
        return self._algorithm.cost

    @property
    def schedule(self) -> PartitionSchedule | None:
        """Return the latest partition schedule, if available."""
        return self._algorithm.schedule

    @property
    def windows(self) -> PartitionWindows | None:
        """Return the latest operation windows, if available."""
        return self._algorithm.windows

    @property
    def circuit(self) -> Circuit:
        """Return the circuit for the configured program."""
        return self._algorithm.circuit

    @property
    def network(self) -> NetworkGraph:
        """Return the network graph used by the configured algorithm."""
        return self._algorithm.network

    @property
    def distributed_circuit(self) -> DistributedCircuit:
        """Return the distributed circuit, extracting it on first access.

        Raises:
            ValueError: If partitioning has not been run yet.
            RuntimeError: If extraction does not populate the circuit.
        """
        distributed = self.circuit.distributed
        if distributed is None:
            self._ensure_distributed_circuit()
            distributed = self.circuit.distributed
        if distributed is None:
            raise RuntimeError("Distributed circuit extraction failed.")
        return distributed

    @property
    def distributed_program(self) -> ast.Program:
        """Return the distributed OpenQASM program for this partitioner."""
        return self.distributed_circuit.program

    @property
    def distributed_qasm(self) -> str:
        """Return the distributed circuit as OpenQASM 3 source text.

        Extracts the distributed circuit on first access if needed.
        """
        return dump_qasm_program(self.distributed_program)

    def save_distributed_circuit(self, path: str | PathLike[str]) -> Path:
        """Write the distributed circuit to an OpenQASM 3 file.

        Args:
            path: Destination file path.

        Returns:
            The path the circuit was written to.
        """
        destination = Path(path)
        destination.write_text(self.distributed_qasm)
        return destination

    def annotated_dag(self) -> nx.DiGraph:
        """Build an annotated distributed-DAG graph for the circuit.

        Opt-in export; compilation never builds this automatically. A fresh
        graph is constructed on each call. Extracts the distributed circuit on
        first access if needed.

        Returns:
            An annotated :class:`networkx.DiGraph` of the distributed circuit.
        """
        from xdqc.circuit.dag import build_annotated_dag

        return build_annotated_dag(self.distributed_circuit)

    def to_dag_json(
        self,
        path: str | PathLike[str] | None = None,
        *,
        indent: int | None = 2,
    ) -> str:
        """Serialize the annotated distributed DAG to a JSON document.

        Opt-in export; compilation never serializes automatically. See
        :func:`xdqc.circuit.dag.annotated_dag_to_json` for the document
        layout. Extracts the distributed circuit on first access if needed.

        Args:
            path: Optional destination file. When given, the JSON document is
                written there in addition to being returned.
            indent: Indentation forwarded to the underlying serializer. Pass
                ``None`` for the most compact single-line output.

        Returns:
            The JSON document as a string.
        """
        from xdqc.circuit.dag import (
            annotated_dag_to_json,
            build_annotated_dag,
        )

        graph = build_annotated_dag(self.distributed_circuit)
        return annotated_dag_to_json(graph, path, indent=indent)

    def verify(
        self,
        *,
        shots: int = 50000000,
        fidelity_threshold: float = 0.90,
        verbosity: Literal["quiet", "info", "debug"] = "quiet",
    ) -> bool:
        """Verify that the distributed circuit matches the original circuit.

        Treats the distributed circuit as a single monolithic circuit in which
        remote operations act perfectly, then compares its measurement
        distribution against the original (pre-partition) circuit via Hellinger
        fidelity. The original circuit is taken from this partitioner, so it
        does not need to be supplied again. Extracts the distributed circuit on
        first access if needed.

        Args:
            shots: Number of shots to execute each circuit for.
            fidelity_threshold: Minimum Hellinger fidelity required for the
                distributed circuit to be considered correct.
            verbosity: Logging verbosity for this workflow call.

        Returns:
            True if the distributed circuit reproduces the original circuit's
            output distribution within the fidelity threshold, False otherwise.
        """
        from xdqc.verify import verify_distributed_circuit

        return verify_distributed_circuit(
            self.circuit.mono.program,
            self.distributed_program,
            shots=shots,
            fidelity_threshold=fidelity_threshold,
            verbosity=verbosity,
        )

    def _resolve_algorithm(
        self,
        network: NetworkGraph,
        program: ast.Program,
        # TODO: clean this up... unnecessary
        # Allow developers to pass custom algorithm implementations
        algo: str | type[_Algorithm] | _Algorithm,
        algo_kwargs: dict[str, Any] | None,
    ) -> BasePartitioner:
        if isinstance(algo, BasePartitioner):
            if algo_kwargs:
                raise ValueError(
                    "algo_kwargs cannot be provided with an algorithm instance."
                )
            return algo

        algo_kwargs = algo_kwargs or {}
        if isinstance(algo, str):
            algo_class = _get_algorithm_class(algo)
        else:
            algo_class = algo

        return algo_class(network, program, **algo_kwargs)

    def _ensure_distributed_circuit(
        self,
        *,
        verbosity: Literal["quiet", "info", "debug"] = "quiet",
    ) -> None:
        """Populate the cached distributed circuit when it is missing."""
        from xdqc.builder import extract_distributed_circuit

        extract_distributed_circuit(
            self,
            ebit_assignment=self._distributed_ebit_assignment,
            group_gates=self._distributed_group_gates,
            max_group_size=self._distributed_max_group_size,
            group_size_profile=self._distributed_group_size_profile,
            verbosity=verbosity,
        )


def _resolve_network_input(network: NetworkInput) -> NetworkGraph:
    """Return a loaded network graph for a supported partitioner input."""
    if isinstance(network, NetworkGraph):
        return network
    return NetworkGraph(str(network))


def _resolve_program_input(program: ProgramInput) -> ast.Program:
    """Return a parsed OpenQASM program for a supported partitioner input.

    Accepts a parsed program, a path to a ``.qasm``/``.qasm3`` file, or inline
    OpenQASM 3 source text.
    """
    if isinstance(program, ast.Program):
        return program
    text = str(program)
    if _looks_like_qasm_source(text):
        return parse_qasm_source(text)
    return load_qasm_program(text)


def _looks_like_qasm_source(value: str) -> bool:
    """Return whether a string is inline OpenQASM source rather than a path."""
    return "openqasm" in value.lower()


def _resolve_partitioner_inputs(
    first: NetworkInput | ProgramInput,
    second: NetworkInput | ProgramInput,
) -> tuple[NetworkGraph, ast.Program]:
    """Return resolved network and program inputs from two constructor args."""
    first_kind = _classify_partitioner_input(first)
    second_kind = _classify_partitioner_input(second)

    if first_kind == "network" and second_kind == "program":
        return (
            _resolve_network_input(cast(NetworkInput, first)),
            _resolve_program_input(cast(ProgramInput, second)),
        )
    if first_kind == "program" and second_kind == "network":
        return (
            _resolve_network_input(cast(NetworkInput, second)),
            _resolve_program_input(cast(ProgramInput, first)),
        )

    raise ValueError(
        "Could not infer which partitioner input is the network and which "
        "is the program. Pass a NetworkGraph and an OpenQASM program, use "
        ".json and .qasm/.qasm3 paths, or pass inline OpenQASM source text."
    )


def _classify_partitioner_input(
    value: NetworkInput | ProgramInput,
) -> Literal["network", "program"] | None:
    """Return the inferred partitioner input kind when it is obvious."""
    if isinstance(value, NetworkGraph):
        return "network"
    if isinstance(value, ast.Program):
        return "program"
    if isinstance(value, (str, PathLike)):
        text = str(value)
        suffix = text.lower()
        if suffix.endswith(".json"):
            return "network"
        if suffix.endswith((".qasm", ".qasm3")):
            return "program"
        if _looks_like_qasm_source(text):
            return "program"
    return None


def _get_algorithm_class(name: str) -> type[BasePartitioner]:
    """Resolve an algorithm class from a registry name."""
    if name == "interaction":
        from xdqc.partition.interaction.interaction import (
            InteractionPartitioner,
        )

        return InteractionPartitioner
    if name in {"benchmark_static", "BenchmarkStatic"}:
        from xdqc.partition.benchmark_static import (
            BenchmarkStaticPartitioner,
        )

        return BenchmarkStaticPartitioner
    if name in {"benchmark_random", "BenchmarkRandom"}:
        from xdqc.partition.benchmark_random import (
            BenchmarkRandomPartitioner,
        )

        return BenchmarkRandomPartitioner
    if name == "hypergraph":
        from xdqc.partition.hypergraph import HypergraphPartitioner

        return HypergraphPartitioner
    if name == "genetic":
        raise NotImplementedError("Genetic algorithm not yet implemented.")
    raise ValueError(f"Unknown partitioning algorithm: {name}")


def _circuit_qubit_physical_map(
    assignment: dict[QPU, set[int]],
) -> dict[int, tuple[int, int]]:
    """Return a deterministic logical-to-physical map for one window.

    The physical position is represented as ``(qpu_id, slot_idx)`` where
    ``slot_idx`` is determined by sorted logical-qubit order within each QPU.
    """
    # TODO: check & simplify this
    mapping: dict[int, tuple[int, int]] = {}
    for qpu, logical_qubits in sorted(
        assignment.items(), key=lambda kv: kv[0].id
    ):
        for slot_idx, logical_qubit in enumerate(sorted(logical_qubits)):
            mapping[logical_qubit] = (qpu.id, slot_idx)
    return dict(sorted(mapping.items(), key=lambda item: item[0]))


def _total_schedule_ebit_cost(
    schedule: PartitionSchedule,
    windows: PartitionWindows,
    network: NetworkGraph,
) -> float:
    """Return total routed e-bit usage implied by a schedule."""
    total_cost = 0.0
    previous_assignment: dict[int, int] | None = None
    remote_gate_ebit_cost = network.remote_gate_ebit_cost
    remote_swap_ebit_cost = network.remote_swap_ebit_cost

    for assignment, ops in zip(schedule, windows, strict=True):
        current_assignment: dict[int, int] = {}
        for qpu, logical_qubits in assignment.items():
            qpu_id = qpu.id
            for logical_qubit in logical_qubits:
                current_assignment[logical_qubit] = qpu_id

        if previous_assignment is not None:
            for logical_qubit, current_qpu_id in current_assignment.items():
                previous_qpu_id = previous_assignment.get(logical_qubit)
                if (
                    previous_qpu_id is not None
                    and previous_qpu_id != current_qpu_id
                ):
                    total_cost += float(
                        remote_swap_ebit_cost(
                            previous_qpu_id,
                            current_qpu_id,
                        )
                    )

        for op in ops:
            if not op.is_two_qubit:
                continue
            left_qubit, right_qubit = op.qubit_indices
            left_qpu_id = current_assignment[left_qubit]
            right_qpu_id = current_assignment[right_qubit]
            if left_qpu_id != right_qpu_id:
                total_cost += float(
                    remote_gate_ebit_cost(left_qpu_id, right_qpu_id)
                )

        previous_assignment = current_assignment

    return total_cost
