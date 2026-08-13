# Copyright 2026 memQ Inc.

# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at

#     http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""User-facing distributed-compilation entry point.

``Compiler`` is the high-level interface for the distributed compiler: give it
a circuit and a network topology, call :meth:`Compiler.compile`, and read back
the distributed circuit (and verify or schedule it). It wraps the lower-level
:class:`~xdqc.partition.Partitioner`, which remains available directly for
callers who need control over the partitioning step itself.
"""

from __future__ import annotations

import hashlib
import json
import logging
from dataclasses import dataclass
from importlib.metadata import PackageNotFoundError, version
from typing import TYPE_CHECKING, Any, Literal

from xdqc.partition import Partitioner
from xdqc.partition.partitioner import (
    NetworkInput,
    ProgramInput,
    _resolve_network_input,
    _resolve_program_input,
)
from xdqc.preprocessing.qasm.io import dump_qasm_program

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from pathlib import Path

    import networkx as nx
    from openqasm3 import ast

    from xdqc.circuit import Circuit, DistributedCircuit
    from xdqc.network import NetworkGraph
    from xdqc.partition.partitioner import (
        BasePartitioner,
        PartitionSchedule,
        PartitionWindows,
    )
    from xdqc.scheduler.instance import (
        SchedulingCompileOptions,
        SchedulingInstance,
    )
    from xdqc.scheduler.schedule import SchedulerHardwareProfile

# Reverse map from algorithm class name to its partitioner registry name, used
# to record a stable partitioner name in instances built from compiler state.
_PARTITIONER_REGISTRY_NAMES: dict[str, str] = {
    "InteractionPartitioner": "interaction",
    "InteractionStaticPartitioner": "interaction_static",
    "HypergraphPartitioner": "hypergraph",
    "BenchmarkStaticPartitioner": "benchmark_static",
    "BenchmarkRandomPartitioner": "benchmark_random",
}


@dataclass(frozen=True, slots=True)
class VerificationArtifacts:
    """Represent both circuits needed for equivalence verification.

    Attributes:
        original_program: Parsed original OpenQASM program.
        original_qasm: Original circuit serialized as OpenQASM source.
        original_dag: Original circuit dependency graph.
        distributed_program: Parsed distributed OpenQASM program.
        distributed_qasm: Distributed circuit serialized as OpenQASM source.
        distributed_dag: Annotated distributed circuit dependency graph.
    """

    original_program: ast.Program
    original_qasm: str
    original_dag: nx.DiGraph
    distributed_program: ast.Program
    distributed_qasm: str
    distributed_dag: nx.DiGraph


class Compiler:
    """Compile a circuit for a distributed quantum network.

    This is the recommended entry point for end users. Construct it with a
    circuit and a network topology, then call :meth:`compile`; the distributed
    circuit and its derived artifacts are then available as properties. Under
    the hood it drives a :class:`~xdqc.partition.Partitioner`, which can
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
        # Deterministic signature of a caller-injected placement, folded into
        # the scheduling-instance fingerprint. ``None`` on the normal compile
        # path so its fingerprint is unaffected.
        self._injected_placement_signature: dict[str, Any] | None = None

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
        :func:`xdqc.circuit.dag.build_annotated_dag` for the node and edge
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
        :func:`xdqc.circuit.dag.annotated_dag_to_json` for the document
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

    def get_verification_artifacts(self) -> VerificationArtifacts:
        """Return original and distributed circuit verification inputs.

        The returned OpenQASM programs can be passed directly to
        :func:`xdqc.verify.verify_distributed_circuit`. The DAGs are
        independent NetworkX graph objects suitable for structural checks.

        Returns:
            Original and distributed OpenQASM programs, source strings, and
            DAGs.

        Raises:
            ValueError: If the circuit has not been compiled yet.
        """
        original_program = self.circuit.mono.program
        distributed_program = self.distributed_program
        return VerificationArtifacts(
            original_program=original_program,
            original_qasm=dump_qasm_program(original_program),
            original_dag=self.circuit.mono.dag.graph.copy(),
            distributed_program=distributed_program,
            distributed_qasm=dump_qasm_program(distributed_program),
            distributed_dag=self.annotated_dag(),
        )

    def verify(
        self,
        *,
        shots: int = 50000000,
        fidelity_threshold: float = 0.90,
        verbosity: Literal["quiet", "info", "debug"] = "quiet",
    ) -> bool:
        """Verify the distributed circuit against the original circuit.

        See :meth:`xdqc.partition.Partitioner.verify` for details.

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

    def to_scheduling_instance(
        self,
        *,
        hardware_profile: SchedulerHardwareProfile | None = None,
    ) -> SchedulingInstance:
        """Build a scheduling instance from the existing distributed result.

        Opt-in export for external RL schedulers. Uses the already-compiled
        distributed circuit (extracting it on first access if compilation has
        occurred) and does not rerun partitioning. Compile the circuit first.

        Args:
            hardware_profile: Scheduler hardware profile whose timings set the
                deterministic operation durations. ``None`` selects the default
                profile.

        Returns:
            A validated :class:`~xdqc.scheduler.instance.SchedulingInstance`.
        """
        from xdqc.scheduler.instance import SchedulingCompileOptions
        from xdqc.scheduler.nominal import build_scheduling_instance

        algorithm = self._partitioner._algorithm
        options = SchedulingCompileOptions(
            partitioner=_PARTITIONER_REGISTRY_NAMES.get(
                type(algorithm).__name__, type(algorithm).__name__
            ),
            partitioner_kwargs=None,
            partition_seed=getattr(algorithm, "seed", None),
            ebit_assignment=self._partitioner._distributed_ebit_assignment,
            group_gates=self._partitioner._distributed_group_gates,
            max_group_size=self._partitioner._distributed_max_group_size,
            hardware_profile=hardware_profile,
        )
        fingerprint = _fingerprint_from_parts(
            self.circuit.mono.program,
            self.network,
            options,
            placement=self._injected_placement_signature,
        )
        return build_scheduling_instance(
            self.distributed_circuit,
            self.network,
            options=options,
            compiler_version=_xdqc_version(),
            source_fingerprint=fingerprint,
        )

    def recompile_with_placement(
        self,
        schedule: PartitionSchedule,
        windows: PartitionWindows | None = None,
        *,
        hardware_profile: SchedulerHardwareProfile | None = None,
    ) -> SchedulingInstance:
        """Re-derive the distributed circuit and scheduling instance.

        Injects a caller-supplied placement and rebuilds the scheduling
        instance from it, reusing the parsed program, monolithic DAG, and
        (unless overridden) the windows from the prior compile; only the
        placement -> distributed derivation re-runs. Partitioning is *not*
        re-run, so the compiler must already have produced windows (call
        :meth:`compile` first) or ``windows`` must be supplied explicitly.

        The existing distributed flags held on the partitioner
        (``ebit_assignment``, ``group_gates``, ``max_group_size``) are
        preserved. The injected placement is folded into the resulting
        instance's ``source_fingerprint`` so distinct placements never collide.

        Args:
            schedule: Per-window placement mapping each QPU to the set of
                logical qubit indices assigned to it.
            windows: Optional replacement operation windows. When omitted, the
                windows from the prior compile are reused.
            hardware_profile: Scheduler hardware profile whose timings set the
                deterministic operation durations. ``None`` selects the default
                profile.

        Returns:
            A validated :class:`~xdqc.scheduler.instance.SchedulingInstance`
            derived from the injected placement.

        Raises:
            ValueError: If the placement is missing windows, its schedule and
                windows differ in length, a window is not a partition of the
                circuit's logical qubits, per-QPU counts differ across windows,
                or a QPU id or qubit index is out of range for the network.
        """
        algorithm = self._partitioner._algorithm
        effective_windows = algorithm.windows if windows is None else windows
        self._validate_injected_placement(schedule, effective_windows)

        algorithm.schedule = schedule
        if windows is not None:
            algorithm.windows = windows
        self._partitioner.circuit.distributed = None
        self._injected_placement_signature = _placement_signature(
            schedule, windows
        )
        return self.to_scheduling_instance(hardware_profile=hardware_profile)

    def _validate_injected_placement(
        self,
        schedule: PartitionSchedule,
        windows: PartitionWindows | None,
    ) -> None:
        """Validate an injected placement against the circuit and network.

        Args:
            schedule: Per-window placement to validate.
            windows: Operation windows the placement will be paired with.

        Raises:
            ValueError: If the placement is structurally invalid or references
                resources outside the network.
        """
        from xdqc.preprocessing.qasm.analysis import count_total_qubits

        if not schedule:
            raise ValueError(
                "Injected placement schedule must contain at least one window."
            )
        if windows is None:
            raise ValueError(
                "No operation windows are available for recompilation: compile "
                "the circuit first or pass windows explicitly."
            )
        if len(schedule) != len(windows):
            raise ValueError(
                "Injected placement schedule and windows differ in length: "
                f"{len(schedule)} placement windows vs {len(windows)} "
                "operation windows."
            )

        network = self.network
        valid_qpu_ids = set(network.qpu_ids())
        capacity_by_qpu = dict(
            zip(
                network.qpu_ids(),
                network.comp_qubits_per_qpu(),
                strict=True,
            )
        )
        num_logical_qubits = count_total_qubits(self.circuit.mono.program)
        logical_qubits = set(range(num_logical_qubits))

        reference_counts: dict[int, int] | None = None
        for window_idx, assignment in enumerate(schedule):
            assigned: list[int] = []
            counts: dict[int, int] = {}
            for qpu, qubits in assignment.items():
                if qpu.id not in valid_qpu_ids:
                    raise ValueError(
                        f"Injected placement window {window_idx} references "
                        f"unknown QPU id {qpu.id}; network QPU ids are "
                        f"{sorted(valid_qpu_ids)}."
                    )
                for qubit in qubits:
                    if qubit not in logical_qubits:
                        raise ValueError(
                            f"Injected placement window {window_idx} assigns "
                            f"logical qubit {qubit} on QPU {qpu.id}, which is "
                            f"out of range for a circuit with "
                            f"{num_logical_qubits} logical qubits."
                        )
                if len(qubits) > capacity_by_qpu[qpu.id]:
                    raise ValueError(
                        f"Injected placement window {window_idx} assigns "
                        f"{len(qubits)} logical qubits to QPU {qpu.id}, "
                        f"exceeding its {capacity_by_qpu[qpu.id]} computation "
                        "qubits."
                    )
                assigned.extend(qubits)
                counts[qpu.id] = len(qubits)

            assigned_set = set(assigned)
            if len(assigned) != len(assigned_set):
                raise ValueError(
                    f"Injected placement window {window_idx} assigns a logical "
                    "qubit to more than one QPU."
                )
            if assigned_set != logical_qubits:
                missing = sorted(logical_qubits - assigned_set)
                unexpected = sorted(assigned_set - logical_qubits)
                raise ValueError(
                    f"Injected placement window {window_idx} is not a "
                    f"partition of the circuit's {num_logical_qubits} logical "
                    f"qubits (missing={missing}, unexpected={unexpected})."
                )

            if reference_counts is None:
                reference_counts = counts
            elif counts != reference_counts:
                raise ValueError(
                    "Injected placement changes per-QPU qubit counts across "
                    f"windows (window {window_idx} has {counts}, expected "
                    f"{reference_counts}); state-teleportation swap synthesis "
                    "requires equal per-QPU counts in every window."
                )


def get_verification_artifacts(
    circuit: ProgramInput,
    topology: NetworkInput,
    *,
    options: SchedulingCompileOptions | None = None,
    verbosity: Literal["quiet", "info", "debug"] = "quiet",
) -> VerificationArtifacts:
    """Compile and return everything needed for circuit equivalence checks.

    Args:
        circuit: The input circuit, as a parsed OpenQASM 3 program, a path to a
            ``.qasm``/``.qasm3`` file, or inline OpenQASM source text.
        topology: The network topology, as a ``NetworkGraph`` or a path to its
            ``.json`` description.
        options: Compilation options. ``None`` uses the scheduling API
            defaults.
        verbosity: Logging verbosity for the compilation workflow.

    Returns:
        Original and distributed OpenQASM programs, source strings, and DAGs.
    """
    from xdqc.scheduler.instance import SchedulingCompileOptions

    resolved_options = options or SchedulingCompileOptions()
    algo_kwargs = dict(resolved_options.partitioner_kwargs or {})
    if resolved_options.partition_seed is not None:
        algo_kwargs["seed"] = resolved_options.partition_seed

    compiler = Compiler(
        circuit,
        topology,
        algo=resolved_options.partitioner,
        algo_kwargs=algo_kwargs or None,
    )
    compiler.compile(
        ebit_assignment=resolved_options.ebit_assignment,
        group_gates=resolved_options.group_gates,
        max_group_size=resolved_options.max_group_size,
        verbosity=verbosity,
    )
    return compiler.get_verification_artifacts()


def compile_scheduling_instance(
    circuit: ProgramInput,
    topology: NetworkInput,
    *,
    options: SchedulingCompileOptions | None = None,
    verbosity: Literal["quiet", "info", "debug"] = "quiet",
) -> SchedulingInstance:
    """Compile a circuit into a self-contained scheduling instance.

    High-level entry point for external RL schedulers: partitions, extracts the
    distributed circuit, and assembles a versioned, JSON-persistable
    :class:`~xdqc.scheduler.instance.SchedulingInstance` (distributed DAG,
    zero-EPR-wait nominal schedule, physical resources and links, and EPR
    demands).

    Args:
        circuit: The input circuit, as a parsed OpenQASM 3 program, a path to a
            ``.qasm``/``.qasm3`` file, or inline OpenQASM source text.
        topology: The network topology, as a ``NetworkGraph`` or a path to its
            ``.json`` description.
        options: Compilation options. ``None`` uses the defaults
            (``interaction`` partitioner, explicit e-bit assignment, no gate
            grouping, default hardware profile). Set
            ``options.hardware_profile`` to select a hardware modality or to
            override individual hardware parameters such as gate, measurement,
            and entanglement timings.
        verbosity: Logging verbosity for this workflow call.

    Returns:
        A validated :class:`~xdqc.scheduler.instance.SchedulingInstance`.
    """
    from xdqc.scheduler.instance import SchedulingCompileOptions
    from xdqc.scheduler.nominal import build_scheduling_instance

    resolved_options = options or SchedulingCompileOptions()
    algo_kwargs = dict(resolved_options.partitioner_kwargs or {})
    if resolved_options.partition_seed is not None:
        algo_kwargs["seed"] = resolved_options.partition_seed

    compiler = Compiler(
        circuit,
        topology,
        algo=resolved_options.partitioner,
        algo_kwargs=algo_kwargs or None,
    )
    compiler.compile(
        ebit_assignment=resolved_options.ebit_assignment,
        group_gates=resolved_options.group_gates,
        max_group_size=resolved_options.max_group_size,
        verbosity=verbosity,
    )
    fingerprint = _fingerprint_from_parts(
        compiler.circuit.mono.program, compiler.network, resolved_options
    )
    return build_scheduling_instance(
        compiler.distributed_circuit,
        compiler.network,
        options=resolved_options,
        compiler_version=_xdqc_version(),
        source_fingerprint=fingerprint,
    )


def recompile_scheduling_instance(
    circuit: ProgramInput,
    topology: NetworkInput,
    *,
    schedule: PartitionSchedule,
    windows: PartitionWindows | None = None,
    options: SchedulingCompileOptions | None = None,
    verbosity: Literal["quiet", "info", "debug"] = "quiet",
) -> SchedulingInstance:
    """Compile a circuit and re-derive its instance from an injected placement.

    Convenience wrapper mirroring :func:`compile_scheduling_instance`: it builds
    a :class:`Compiler`, runs a full compile to establish the reusable program,
    monolithic DAG, windows, and distributed flags, then re-derives the
    scheduling instance from ``schedule`` (and ``windows`` when provided) via
    :meth:`Compiler.recompile_with_placement`.

    Args:
        circuit: The input circuit, as a parsed OpenQASM 3 program, a path to a
            ``.qasm``/``.qasm3`` file, or inline OpenQASM source text.
        topology: The network topology, as a ``NetworkGraph`` or a path to its
            ``.json`` description.
        schedule: Per-window placement mapping each QPU to the set of logical
            qubit indices assigned to it.
        windows: Optional replacement operation windows. When omitted, the
            windows produced by the initial compile are reused.
        options: Compilation options. ``None`` uses the defaults.
        verbosity: Logging verbosity for this workflow call.

    Returns:
        A validated :class:`~xdqc.scheduler.instance.SchedulingInstance`
        derived from the injected placement.
    """
    from xdqc.scheduler.instance import SchedulingCompileOptions

    resolved_options = options or SchedulingCompileOptions()
    algo_kwargs = dict(resolved_options.partitioner_kwargs or {})
    if resolved_options.partition_seed is not None:
        algo_kwargs["seed"] = resolved_options.partition_seed

    compiler = Compiler(
        circuit,
        topology,
        algo=resolved_options.partitioner,
        algo_kwargs=algo_kwargs or None,
    )
    compiler.compile(
        ebit_assignment=resolved_options.ebit_assignment,
        group_gates=resolved_options.group_gates,
        max_group_size=resolved_options.max_group_size,
        verbosity=verbosity,
    )
    return compiler.recompile_with_placement(
        schedule,
        windows,
        hardware_profile=resolved_options.hardware_profile,
    )


def compute_scheduling_source_fingerprint(
    circuit: ProgramInput,
    topology: NetworkInput,
    options: SchedulingCompileOptions | None = None,
) -> str:
    """Return the source fingerprint for a compile request without compiling.

    Parses and normalizes the inputs and hashes them together with the
    compilation options, hardware profile, and schema version. This is the same
    value :func:`compile_scheduling_instance` records, enabling a cache lookup
    before the (much more expensive) compilation runs.

    Args:
        circuit: The input circuit (parsed program, path, or inline source).
        topology: The network topology (``NetworkGraph`` or path).
        options: Compilation options; ``None`` uses the defaults.

    Returns:
        A hex SHA-256 digest of the normalized inputs and options.
    """
    from xdqc.scheduler.instance import SchedulingCompileOptions

    resolved_options = options or SchedulingCompileOptions()
    program = _resolve_program_input(circuit)
    network = _resolve_network_input(topology)
    return _fingerprint_from_parts(program, network, resolved_options)


def _fingerprint_from_parts(
    program: ast.Program,
    network: NetworkGraph,
    options: SchedulingCompileOptions,
    placement: dict[str, Any] | None = None,
) -> str:
    """Return a deterministic fingerprint for normalized inputs and options.

    Args:
        program: Normalized monolithic OpenQASM program.
        network: The network graph.
        options: Compilation options.
        placement: Optional deterministic signature of a caller-injected
            placement (see :func:`_placement_signature`). When ``None`` the
            payload is identical to the normal compile path, keeping that
            path's fingerprint unchanged.

    Returns:
        A hex SHA-256 digest of the normalized inputs, options, and placement.
    """
    from xdqc.scheduler.instance import SCHEDULING_INSTANCE_SCHEMA_VERSION
    from xdqc.scheduler.schedule import (
        _resolve_scheduler_hardware_profile,
    )

    profile = _resolve_scheduler_hardware_profile(
        profile=options.hardware_profile,
        modality="trapped_ion.ba",
        entanglement_profile="ion.time_bin",
    )
    canonical_options: dict[str, Any] = {
        "partitioner": options.partitioner,
        "partitioner_kwargs": dict(options.partitioner_kwargs or {}),
        "partition_seed": options.partition_seed,
        "ebit_assignment": options.ebit_assignment,
        "group_gates": options.group_gates,
        "max_group_size": options.max_group_size,
        "modality": profile.modality,
        "entanglement_profile": profile.entanglement_profile,
    }
    if profile.overrides:
        canonical_options["hardware_overrides"] = profile.overrides
    canonical: dict[str, Any] = {
        "schema_version": SCHEDULING_INSTANCE_SCHEMA_VERSION,
        "qasm": dump_qasm_program(program),
        "network": _network_signature(network),
        "options": canonical_options,
    }
    if placement is not None:
        canonical["placement"] = placement
    payload = json.dumps(canonical, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _placement_signature(
    schedule: PartitionSchedule,
    windows: PartitionWindows | None,
) -> dict[str, Any]:
    """Return a deterministic, JSON-serializable signature of a placement.

    The schedule is always included; the windows are included only when a
    caller overrides them, so a placement that reuses the prior windows folds
    in only its schedule.

    Args:
        schedule: Per-window placement mapping each QPU to logical qubits.
        windows: Overriding operation windows, or ``None`` when the prior
            compile's windows are reused.

    Returns:
        A nested mapping suitable for stable JSON serialization.
    """
    signature: dict[str, Any] = {
        "schedule": [
            [
                [qpu.id, sorted(qubits)]
                for qpu, qubits in sorted(
                    assignment.items(), key=lambda item: item[0].id
                )
            ]
            for assignment in schedule
        ]
    }
    if windows is not None:
        signature["windows"] = [
            [op.op_id for op in window] for window in windows
        ]
    return signature


def _network_signature(network: NetworkGraph) -> dict[str, Any]:
    """Return a canonical, order-independent signature of a network graph."""
    from xdqc.scheduler.schedule import _physical_qubit_label

    nodes = sorted(
        [qubit.qpu_id, qubit.qubit_id, qubit.qubit_type]
        for qubit in network.graph.nodes
    )
    edges = sorted(
        [
            *sorted(
                (_physical_qubit_label(first), _physical_qubit_label(second))
            ),
            data.get("connection_type"),
        ]
        for first, second, data in network.graph.edges(data=True)
    )
    return {"qubits": nodes, "edges": edges}


def _xdqc_version() -> str:
    """Return the installed xdqc version, or a sentinel when unknown."""
    try:
        return version("xdqc")
    except PackageNotFoundError:
        return "0.0.0+unknown"
