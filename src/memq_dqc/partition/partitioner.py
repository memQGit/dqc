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

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from openqasm3 import ast

from memq_dqc.circuit.dag import CircuitDAG
from memq_dqc.circuit.ops import Op
from memq_dqc.graph import NetworkGraph
from memq_dqc.partition.types import QPU

PartitionSchedule = list[dict[QPU, set[int]]]
PartitionWindows = list[list[Op]]

_Algorithm = TypeVar("_Algorithm", bound="BasePartitioner")


class BasePartitioner(ABC):
    """Base class for partitioning algorithm implementations."""

    def __init__(self, network: NetworkGraph, program: ast.Program) -> None:
        """Initialize the partitioner with circuit and network inputs.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
        """
        self.network = network
        self.program = program
        self.dag = CircuitDAG(program)
        self.cost: float | None = None
        self.schedule: PartitionSchedule | None = None
        self.windows: PartitionWindows | None = None

    @abstractmethod
    def run(self) -> None:
        """Run the partitioning algorithm.

        Updates:
            cost, schedule, and windows with the latest partitioning results.
        """
        raise NotImplementedError


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

    def run(self) -> None:
        """Run the configured partitioning algorithm.

        Updates:
            cost, schedule, and windows with the latest partitioning results.
        """
        self._algorithm.run()

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
    def dag(self) -> CircuitDAG:
        """Return the circuit DAG for the configured program."""
        return self._algorithm.dag

    def _resolve_algorithm(
        self,
        network: NetworkGraph,
        program: ast.Program,
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
    if name == "genetic":
        raise NotImplementedError("Genetic algorithm not yet implemented.")
    raise ValueError(f"Unknown partitioning algorithm: {name}")
