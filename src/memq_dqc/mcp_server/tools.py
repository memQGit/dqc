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

"""Transport-agnostic implementations of the MCP tools.

Every function here takes plain strings, numbers, and dictionaries and
returns a JSON-serializable dictionary, so the same logic serves a local
stdio server today and a remote HTTP server later. None of it imports
FastMCP.

Circuits and networks are given as a single string that may be:

- the name of a bundled asset (see ``list_bundled_assets``), such as
  ``"qft_n10"`` or ``"10_qubits/n2_pair_nn"``;
- inline source: OpenQASM 3 text for a circuit, or network JSON text;
- a path to a ``.qasm``/``.qasm3`` or ``.json`` file on the server's machine.

Paths, including the optional ``output_path`` arguments, refer to the
filesystem of the machine running the server. That is the user's own
machine for a local server; a hosted server would need to restrict them.
"""

from __future__ import annotations

import json
import math
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any, Literal, TypeAlias, cast, get_args

from memq_dqc.assets import (
    circuit_path,
    list_circuits,
    list_networks,
    network_path,
)
from memq_dqc.compiler import Compiler
from memq_dqc.network import (
    NetworkGraph,
    generate_network,
    validate_network,
)
from memq_dqc.network.generation import IntraQpuConnectivity, QpuArrangement
from memq_dqc.preprocessing.qasm.analysis import count_total_qubits
from memq_dqc.scheduler import Scheduler
from memq_dqc.scheduler.schedule import (
    SchedulerEntanglementProfile,
    SchedulerModality,
)
from memq_dqc.verify import verify_distributed_circuit

if TYPE_CHECKING:
    from memq_dqc.scheduler import OperationSchedule

# Option names are Literal types so MCP clients see them as enums in each
# tool's input schema and invalid names are rejected before any work runs.

#: Partitioner registry names accepted by ``Compiler(algo=...)``.
PartitionerName: TypeAlias = Literal[
    "interaction",
    "interaction_static",
    "hypergraph",
    "benchmark_static",
    "benchmark_random",
]

#: Scheduler registry names accepted by ``Scheduler(algo=...)``.
SchedulerName: TypeAlias = Literal[
    "fifo",
    "des_link_fifo",
    "des_link_shortest_duration",
    "des_link_critical_path",
]

VerificationMethod: TypeAlias = Literal["statevector", "sampling"]


def list_algorithms() -> dict[str, list[str]]:
    """List the partitioners, schedulers, and hardware options available.

    Returns:
        A mapping from option kind to the accepted names.
    """
    return {
        "partitioners": list(get_args(PartitionerName)),
        "schedulers": list(get_args(SchedulerName)),
        "modalities": list(get_args(SchedulerModality)),
        "entanglement_profiles": list(get_args(SchedulerEntanglementProfile)),
    }


def list_bundled_assets() -> dict[str, list[str]]:
    """List the reference circuits and networks bundled with the package.

    Returns:
        A mapping with ``"circuits"`` and ``"networks"`` name lists. Network
        names are size-qualified: a network under ``N_qubits/`` hosts any
        circuit of at most N qubits.
    """
    return {"circuits": list_circuits(), "networks": list_networks()}


def describe_network(network: str) -> dict[str, Any]:
    """Validate a network topology and summarize it.

    Use this to check a hand-written network before compiling on it.

    Args:
        network: Bundled network name, inline network JSON, or a path to a
            network ``.json`` file.

    Returns:
        QPU ids and per-QPU computation and communication qubit counts.

    Raises:
        ValueError: If the network is malformed. The message lists every
            problem found.
    """
    data = _read_network(network)
    validate_network(data)
    return _summarize_network(_network_graph(data))


def build_network(
    num_qpus: int,
    computation_qubits_per_qpu: int | None = None,
    circuit_qubits: int | None = None,
    arrangement: QpuArrangement = "chain",
    qpu_links: list[tuple[int, int]] | None = None,
    intra_qpu: IntraQpuConnectivity = "nearest_neighbor",
    links_per_pair: int = 2,
    output_path: str | None = None,
) -> dict[str, Any]:
    """Generate a network topology with identically sized QPUs.

    Give exactly one of ``computation_qubits_per_qpu`` and
    ``circuit_qubits``.

    Args:
        num_qpus: Number of QPUs.
        computation_qubits_per_qpu: Computation (data) qubits on each QPU.
        circuit_qubits: Size of the largest circuit the network must run.
            Each QPU then gets that many qubits divided across the QPUs,
            rounded up.
        arrangement: How the QPUs are linked: ``chain``, ``ring`` (3+ QPUs),
            ``hub`` (QPU 0 is the centre), or ``all_to_all``.
        qpu_links: Explicit ``[qpu_a, qpu_b]`` links between QPU ids
            ``0..num_qpus-1``. Overrides ``arrangement`` when given.
        intra_qpu: Coupling inside each QPU: ``nearest_neighbor`` (a 2D
            grid) or ``all_to_all``.
        links_per_pair: Remote links between each pair of linked QPUs. With
            fewer than 2, QPUs that are not directly linked cannot interact.
        output_path: Optional file to write the network JSON to.

    Returns:
        The network summary, plus the path it was written to, or the
        network JSON itself when no ``output_path`` is given. The JSON can
        be passed directly as the ``network`` argument of other tools.

    Raises:
        ValueError: If both or neither qubit counts are given.
    """
    if (computation_qubits_per_qpu is None) == (circuit_qubits is None):
        raise ValueError(
            "Give exactly one of computation_qubits_per_qpu and "
            "circuit_qubits."
        )
    if circuit_qubits is not None:
        computation_qubits_per_qpu = math.ceil(circuit_qubits / num_qpus)
    network = generate_network(
        num_qpus,
        cast(int, computation_qubits_per_qpu),
        arrangement if qpu_links is None else qpu_links,
        intra_qpu=intra_qpu,
        links_per_pair=links_per_pair,
    )
    result = _summarize_network(_network_graph(network))
    if output_path is not None:
        destination = _output(output_path)
        destination.write_text(json.dumps(network, indent=2) + "\n")
        result["output_path"] = str(destination)
    else:
        result["network_json"] = json.dumps(network, separators=(",", ":"))
    return result


def _summarize_network(graph: NetworkGraph) -> dict[str, Any]:
    """Return the summary ``describe_network`` and ``build_network`` report.

    Args:
        graph: A loaded network.

    Returns:
        QPU ids and per-QPU computation and communication qubit counts.
    """
    return {
        "num_qpus": graph.num_qpus,
        "qpu_ids": graph.qpu_ids(),
        "num_computation_qubits": graph.num_comp_qubits,
        "num_communication_qubits": graph.num_comm_qubits,
        "computation_qubits_per_qpu": graph.comp_qubits_per_qpu(),
        "communication_qubits_per_qpu": graph.comm_qubits_per_qpu(),
        "is_homogeneous": graph.is_homogeneous,
    }


def compile_circuit(
    circuit: str,
    network: str,
    partitioner: PartitionerName = "interaction",
    partitioner_kwargs: dict[str, Any] | None = None,
    output_path: str | None = None,
    include_qasm: bool = True,
) -> dict[str, Any]:
    """Partition a circuit across a network and build the distributed circuit.

    Args:
        circuit: Bundled circuit name, inline OpenQASM 3 source, or a path to
            a ``.qasm`` file.
        network: Bundled network name, inline network JSON, or a path to a
            network ``.json`` file.
        partitioner: Partitioner registry name.
        partitioner_kwargs: Keyword arguments forwarded to the partitioner,
            such as ``{"seed": 7}``.
        output_path: Optional file to write the distributed OpenQASM to.
        include_qasm: Whether to return the distributed OpenQASM inline.
            Disable for large circuits and use ``output_path`` instead.

    Returns:
        The e-bit cost, circuit and network sizes, and the distributed
        OpenQASM and/or the path it was written to.
    """
    compiler = _compile(circuit, network, partitioner, partitioner_kwargs)
    result = _compile_summary(compiler, partitioner)
    if output_path is not None:
        written = compiler.save_distributed_circuit(_output(output_path))
        result["output_path"] = str(written)
    if include_qasm:
        result["distributed_qasm"] = compiler.distributed_qasm
    return result


def verify_compilation(
    circuit: str,
    network: str,
    partitioner: PartitionerName = "interaction",
    partitioner_kwargs: dict[str, Any] | None = None,
    method: VerificationMethod = "statevector",
    shots: int = 100_000,
    max_qubits: int = 20,
) -> dict[str, Any]:
    """Compile a circuit, then check the result against the original.

    Remote operations are simulated as ideal, so this checks the
    compiler's logic, not hardware noise.

    Args:
        circuit: Bundled circuit name, inline OpenQASM 3 source, or a path to
            a ``.qasm`` file.
        network: Bundled network name, inline network JSON, or a path to a
            network ``.json`` file.
        partitioner: Partitioner registry name.
        partitioner_kwargs: Keyword arguments forwarded to the partitioner.
        method: ``"statevector"`` for an exact check, or ``"sampling"`` for a
            shot-based Hellinger-fidelity check.
        shots: Shots per circuit for the ``"sampling"`` method.
        max_qubits: Widest circuit the ``"statevector"`` method will
            simulate; its memory grows as ``2**n``.

    Returns:
        Whether the circuits are equivalent, plus the compile summary.
    """
    compiler = _compile(circuit, network, partitioner, partitioner_kwargs)
    artifacts = compiler.get_verification_artifacts()
    equivalent = verify_distributed_circuit(
        artifacts.original_program,
        artifacts.distributed_program,
        method=method,
        shots=shots,
        max_qubits=max_qubits,
    )
    return {
        **_compile_summary(compiler, partitioner),
        "method": method,
        "equivalent": equivalent,
    }


def schedule_circuit(
    circuit: str,
    network: str,
    partitioner: PartitionerName = "interaction",
    partitioner_kwargs: dict[str, Any] | None = None,
    scheduler: SchedulerName = "fifo",
    modality: SchedulerModality = "trapped_ion.ba",
    entanglement_profile: SchedulerEntanglementProfile = "ion.time_bin",
    output_path: str | None = None,
) -> dict[str, Any]:
    """Compile a circuit and build its time-execution schedule.

    Args:
        circuit: Bundled circuit name, inline OpenQASM 3 source, or a path to
            a ``.qasm`` file.
        network: Bundled network name, inline network JSON, or a path to a
            network ``.json`` file.
        partitioner: Partitioner registry name.
        partitioner_kwargs: Keyword arguments forwarded to the partitioner.
        scheduler: Scheduler registry name.
        modality: Hardware modality setting local gate timings.
        entanglement_profile: Profile setting entanglement-generation timing.
        output_path: Optional file to write the full schedule JSON to.

    Returns:
        The makespan and operation counts, plus the compile summary and the
        schedule path when ``output_path`` is given.
    """
    compiler = _compile(circuit, network, partitioner, partitioner_kwargs)
    runner = Scheduler(
        compiler,
        algo=scheduler,
        modality=modality,
        entanglement_profile=entanglement_profile,
    )
    runner.run()
    schedule = _require_schedule(runner)
    result: dict[str, Any] = {
        **_compile_summary(compiler, partitioner),
        "scheduler": scheduler,
        "modality": modality,
        "entanglement_profile": entanglement_profile,
        **_schedule_summary(schedule),
    }
    if output_path is not None:
        destination = _output(output_path)
        runner.to_json(destination)
        result["output_path"] = str(destination)
    return result


def compare_partitioners(
    circuit: str,
    network: str,
    partitioners: list[PartitionerName] | None = None,
    scheduler: SchedulerName | None = None,
) -> dict[str, Any]:
    """Compile one circuit with several partitioners and compare them.

    A partitioner that fails (for example, ``hypergraph`` without KaHyPar
    installed) is reported with its error rather than aborting the run.

    Args:
        circuit: Bundled circuit name, inline OpenQASM 3 source, or a path to
            a ``.qasm`` file.
        network: Bundled network name, inline network JSON, or a path to a
            network ``.json`` file.
        partitioners: Partitioner names to compare. Defaults to all of them.
        scheduler: Optional scheduler name. When given, each result also
            reports the schedule makespan.

    Returns:
        One row per partitioner with its e-bit cost (and makespan), sorted
        best first; failed partitioners are listed last with their error.
    """
    names: list[PartitionerName] = (
        list(get_args(PartitionerName))
        if partitioners is None
        else partitioners
    )
    rows: list[dict[str, Any]] = []
    for name in names:
        try:
            compiler = _compile(circuit, network, name, None)
            row: dict[str, Any] = {
                "partitioner": name,
                "ebit_cost": compiler.cost,
            }
            if scheduler is not None:
                runner = Scheduler(compiler, algo=scheduler)
                runner.run()
                row["makespan"] = _require_schedule(runner).makespan
        except Exception as exc:  # Reported per row, not raised.
            row = {
                "partitioner": name,
                "error": f"{type(exc).__name__}: {exc}",
            }
        rows.append(row)
    sort_key = "makespan" if scheduler is not None else "ebit_cost"
    rows.sort(key=lambda r: ("error" in r, r.get(sort_key) or 0.0))
    return {"sorted_by": sort_key, "results": rows}


def _compile(
    circuit: str,
    network: str,
    partitioner: PartitionerName,
    partitioner_kwargs: dict[str, Any] | None,
) -> Compiler:
    """Build and run a compiler from tool-level string inputs.

    Args:
        circuit: Circuit given as a tool argument.
        network: Network given as a tool argument.
        partitioner: Partitioner registry name.
        partitioner_kwargs: Keyword arguments forwarded to the partitioner.

    Returns:
        A compiled ``Compiler``.
    """
    compiler = Compiler(
        _resolve_circuit(circuit),
        _load_network(network),
        algo=partitioner,
        algo_kwargs=partitioner_kwargs,
    )
    compiler.compile()
    return compiler


def _compile_summary(compiler: Compiler, partitioner: str) -> dict[str, Any]:
    """Return the fields every compiling tool reports.

    Args:
        compiler: A compiled ``Compiler``.
        partitioner: Partitioner registry name used to compile.

    Returns:
        The partitioner, e-bit cost, logical qubit count, and QPU count.
    """
    return {
        "partitioner": partitioner,
        "ebit_cost": compiler.cost,
        "num_logical_qubits": count_total_qubits(
            compiler.circuit.mono.program
        ),
        "num_qpus": compiler.network.num_qpus,
    }


def _schedule_summary(schedule: OperationSchedule) -> dict[str, Any]:
    """Return headline numbers for an operation schedule.

    Args:
        schedule: Schedule produced by a scheduler run.

    Returns:
        The makespan and total and remote operation counts.
    """
    return {
        "makespan": schedule.makespan,
        "num_operations": len(schedule.operations),
        "num_remote_operations": sum(
            1 for op in schedule.operations if op.is_remote
        ),
    }


def _require_schedule(runner: Scheduler) -> OperationSchedule:
    """Return a scheduler's result, failing loudly when it produced none.

    Args:
        runner: A scheduler that has been run.

    Returns:
        The operation schedule.

    Raises:
        RuntimeError: If the scheduler finished without a schedule.
    """
    if runner.schedule is None:
        raise RuntimeError("Scheduling finished without a schedule.")
    return runner.schedule


def _resolve_circuit(circuit: str) -> str | Path:
    """Map a bundled circuit name to its path; pass anything else through.

    Args:
        circuit: Bundled name, inline OpenQASM source, or file path.

    Returns:
        A value ``Compiler`` accepts as its circuit.
    """
    if circuit in list_circuits():
        return circuit_path(circuit)
    return circuit


def _load_network(network: str) -> NetworkGraph:
    """Load a network from a bundled name, inline JSON, or file path.

    Args:
        network: Bundled name, inline network JSON, or file path.

    Returns:
        The loaded network graph.
    """
    return _network_graph(_read_network(network))


def _read_network(network: str) -> dict[str, Any]:
    """Parse a network given as a bundled name, inline JSON, or file path.

    Args:
        network: Bundled name, inline network JSON, or file path.

    Returns:
        The parsed network JSON.
    """
    if network in list_networks():
        text = network_path(network).read_text()
    elif network.lstrip().startswith("{"):
        text = network
    else:
        text = Path(network).expanduser().read_text()
    return json.loads(text)


def _network_graph(data: dict[str, Any]) -> NetworkGraph:
    """Build a ``NetworkGraph`` from parsed network JSON.

    Args:
        data: The parsed network JSON.

    Returns:
        The loaded network graph.
    """
    # NetworkGraph only reads from a file, so stage the JSON in one.
    with tempfile.TemporaryDirectory() as tmp:
        staged = Path(tmp) / "network.json"
        staged.write_text(json.dumps(data))
        return NetworkGraph(str(staged))


def _output(output_path: str) -> Path:
    """Resolve an output path, creating its parent directory.

    Args:
        output_path: Destination file path.

    Returns:
        The resolved destination path.
    """
    destination = Path(output_path).expanduser().resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    return destination
