# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Partitioner interfaces and orchestration helpers."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, TypeVar

from openqasm3 import ast

from memq_dqc.graph import NetworkGraph

PartitionSchedule = list[list[set[int]]]
PartitionResult = tuple[float, PartitionSchedule]

_AlgorithmT = TypeVar("_AlgorithmT", bound="BasePartitioner")


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

    @abstractmethod
    def run(self) -> PartitionResult:
        """Run the partitioning algorithm.

        Returns:
            The entanglement cost and partition schedule.
        """
        raise NotImplementedError


class Partitioner:
    """Orchestrate a partitioning algorithm implementation."""

    def __init__(
        self,
        network: NetworkGraph,
        program: ast.Program,
        *,
        algo: str | type[_AlgorithmT] | _AlgorithmT = "cisco",
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

    def run(self) -> PartitionResult:
        """Run the configured partitioning algorithm.

        Returns:
            The entanglement cost and partition schedule.
        """
        return self._algorithm.run()

    def _resolve_algorithm(
        self,
        network: NetworkGraph,
        program: ast.Program,
        algo: str | type[_AlgorithmT] | _AlgorithmT,
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
            algo_cls = _get_algorithm_class(algo)
        else:
            algo_cls = algo

        return algo_cls(network, program, **algo_kwargs)


def _get_algorithm_class(name: str) -> type[BasePartitioner]:
    """Resolve an algorithm class from a registry name."""
    if name == "cisco":
        from memq_dqc.partition.cisco.cisco import CiscoPartitioner

        return CiscoPartitioner
    raise ValueError(f"Unknown partitioning algorithm: {name}")
