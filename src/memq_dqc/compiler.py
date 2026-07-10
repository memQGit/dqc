# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""User-facing distributed-compilation entry point.

``Compiler`` is the high-level interface for the distributed compiler: give it
a circuit and a network topology, call :meth:`Compiler.compile`, and read back
the distributed circuit (and verify or schedule it). It wraps the lower-level
:class:`~memq_dqc.partition.Partitioner`, which remains available directly for
callers who need control over the partitioning step itself.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Literal

from memq_dqc.partition import Partitioner
from memq_dqc.partition.partitioner import NetworkInput, ProgramInput

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    import networkx as nx
    from openqasm3 import ast

    from memq_dqc.circuit import Circuit, DistributedCircuit
    from memq_dqc.network import NetworkGraph
    from memq_dqc.partition.partitioner import BasePartitioner
    from memq_dqc.scheduler.schedule import SchedulerHardwareProfile


class Compiler:
    """Compile a circuit for a distributed quantum network.

    This is the recommended entry point for end users. Construct it with a
    circuit and a network topology, then call :meth:`compile`; the distributed
    circuit and its derived artifacts are then available as properties. Under
    the hood it drives a :class:`~memq_dqc.partition.Partitioner`, which can
    also be used directly for finer control over partitioning.
    """

    def __init__(
        self,
        circuit: ProgramInput,
        topology: NetworkInput,
        algo: str | type[BasePartitioner] | BasePartitioner = "interaction",
        *,
        algo_kwargs: dict[str, Any] | None = None,
    ) -> None:
        """Initialize the compiler.

        Args:
            circuit: The input circuit, as a parsed OpenQASM 3 program, a path
                to a ``.qasm``/``.qasm3`` file, or inline OpenQASM source text.
            topology: The network topology, as a ``NetworkGraph`` or a path to
                its ``.json`` description.
            algo: Partitioning algorithm name, class, or preconfigured
                instance.
            algo_kwargs: Keyword arguments forwarded to the algorithm.
        """
        self._partitioner = Partitioner(
            topology, circuit, algo=algo, algo_kwargs=algo_kwargs
        )

    def compile(
        self,
        *,
        ebit_assignment: bool | None = None,
        group_gates: bool = True,
        max_group_size: int | None = None,
        group_size_profile: SchedulerHardwareProfile | None = None,
        verbosity: Literal["quiet", "info", "debug"] = "quiet",
    ) -> None:
        """Compile the circuit for the configured network.

        Runs partitioning and reconstructs the distributed circuit. After this
        call, :attr:`distributed_circuit`, :attr:`distributed_qasm`, and the
        other result properties are available.

        Args:
            ebit_assignment: Whether to also extract the distributed circuit
                during this call, and if so whether the compiler assigns
                concrete e-bit pairs into the scheduler DAG. When omitted,
                partitioning runs and extraction is deferred until the
                distributed circuit is first accessed.
            group_gates: Whether to keep compatible remote gate groups inside a
                shared cat-entanglement region.
            max_group_size: Optional maximum number of two-qubit gates per
                emitted gate group.
            group_size_profile: Scheduler hardware profile whose timing bounds
                each gate group's duration to the EPR lifetime. When omitted
                the EPR-lifetime cap is disabled.
            verbosity: Logging verbosity for this workflow call.
        """
        self._partitioner.run(
            ebit_assignment=ebit_assignment,
            group_gates=group_gates,
            max_group_size=max_group_size,
            group_size_profile=group_size_profile,
            verbosity=verbosity,
        )

    @property
    def partitioner(self) -> Partitioner:
        """Return the underlying partitioner driving this compiler."""
        return self._partitioner

    @property
    def network(self) -> NetworkGraph:
        """Return the network graph used by this compiler."""
        return self._partitioner.network

    @property
    def circuit(self) -> Circuit:
        """Return the circuit model for the input program."""
        return self._partitioner.circuit

    @property
    def cost(self) -> float | None:
        """Return the latest entanglement cost, if available."""
        return self._partitioner.cost

    @property
    def distributed_circuit(self) -> DistributedCircuit:
        """Return the distributed circuit, extracting it on first access.

        Raises:
            ValueError: If the circuit has not been compiled yet.
            RuntimeError: If extraction does not populate the circuit.
        """
        return self._partitioner.distributed_circuit

    @property
    def distributed_program(self) -> ast.Program:
        """Return the distributed OpenQASM program."""
        return self._partitioner.distributed_program

    @property
    def distributed_qasm(self) -> str:
        """Return the distributed circuit as OpenQASM 3 source text."""
        return self._partitioner.distributed_qasm

    def save_distributed_circuit(self, path: str | Path) -> Path:
        """Write the distributed circuit to an OpenQASM 3 file.

        Args:
            path: Destination file path.

        Returns:
            The path the circuit was written to.
        """
        return self._partitioner.save_distributed_circuit(path)

    def annotated_dag(self) -> nx.DiGraph:
        """Return the compiled program as an annotated distributed DAG.

        Opt-in export; compiling never builds this automatically. A fresh
        annotated :class:`networkx.DiGraph` is constructed on each call. See
        :func:`memq_dqc.circuit.dag.build_annotated_dag` for the node and edge
        attributes.

        Returns:
            An annotated :class:`networkx.DiGraph` of the distributed circuit.
        """
        return self._partitioner.annotated_dag()

    def to_dag_json(
        self,
        path: str | Path | None = None,
        *,
        indent: int | None = 2,
    ) -> str:
        """Serialize the annotated distributed DAG to a JSON document.

        Opt-in export; compiling never serializes automatically. See
        :func:`memq_dqc.circuit.dag.annotated_dag_to_json` for the document
        layout.

        Args:
            path: Optional destination file. When given, the JSON document is
                written there in addition to being returned.
            indent: Indentation forwarded to the underlying serializer. Pass
                ``None`` for the most compact single-line output.

        Returns:
            The JSON document as a string.
        """
        return self._partitioner.to_dag_json(path, indent=indent)

    def verify(
        self,
        *,
        shots: int = 50000000,
        fidelity_threshold: float = 0.90,
        verbosity: Literal["quiet", "info", "debug"] = "quiet",
    ) -> bool:
        """Verify the distributed circuit against the original circuit.

        See :meth:`memq_dqc.partition.Partitioner.verify` for details.

        Args:
            shots: Number of shots to execute each circuit for.
            fidelity_threshold: Minimum Hellinger fidelity required for the
                distributed circuit to be considered correct.
            verbosity: Logging verbosity for this workflow call.

        Returns:
            True if the distributed circuit reproduces the original circuit's
            output distribution within the fidelity threshold, False otherwise.
        """
        return self._partitioner.verify(
            shots=shots,
            fidelity_threshold=fidelity_threshold,
            verbosity=verbosity,
        )
