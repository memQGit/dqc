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
from typing import Any, Literal, TypeVar

from openqasm3 import ast

from memq_dqc._logging import StepTimer, workflow_logging
from memq_dqc.circuit import Circuit
from memq_dqc.circuit.op import Op
from memq_dqc.network import NetworkGraph

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class QPU:
    """Represents a QPU identifier for partition assignments."""

    id: int


PartitionSchedule = list[dict[QPU, set[int]]]
PartitionWindows = list[list[Op]]

_Algorithm = TypeVar("_Algorithm", bound="BasePartitioner")


# TODO: add seed for randomness (eg cisco has some random components)
class BasePartitioner(ABC):
    """Base class for partitioning algorithm implementations."""

    def __init__(self, network: NetworkGraph, program: ast.Program) -> None:
        """Initialize the partitioner with circuit and network inputs.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
        """
        self.network = network
        self.circuit = Circuit(program)
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
        network: NetworkGraph,
        program: ast.Program,
        *,
        algo: str | type[_Algorithm] | _Algorithm = "cisco",
        algo_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the partitioner and select the algorithm.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
            algo: Algorithm name, class, or preconfigured instance.
            algo_kwargs: Keyword arguments forwarded to the algorithm.
        """
        self._algorithm = self._resolve_algorithm(
            network, program, algo, algo_kwargs
        )

    def run(
        self,
        *,
        verbosity: Literal["quiet", "info", "debug"] = "quiet",
    ) -> None:
        """Run the configured partitioning algorithm.

        Args:
            verbosity: Logging verbosity for this workflow call.

        Updates:
            cost, schedule, and windows with the latest partitioning results.
        """
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


def _get_algorithm_class(name: str) -> type[BasePartitioner]:
    """Resolve an algorithm class from a registry name."""
    if name == "cisco":
        from memq_dqc.partition.cisco.cisco import CiscoPartitioner

        return CiscoPartitioner
    if name in {"benchmark_static", "BenchmarkStatic"}:
        from memq_dqc.partition.benchmark_static import (
            BenchmarkStaticPartitioner,
        )

        return BenchmarkStaticPartitioner
    if name in {"benchmark_random", "BenchmarkRandom"}:
        from memq_dqc.partition.benchmark_random import (
            BenchmarkRandomPartitioner,
        )

        return BenchmarkRandomPartitioner
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
