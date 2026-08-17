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

"""Verification of distributed circuit."""

from __future__ import annotations

import logging
from typing import Literal

import qiskit.qasm3
from openqasm3 import ast
from qiskit import QuantumCircuit, transpile
from qiskit.circuit import Measure
from qiskit.quantum_info import Statevector, hellinger_fidelity
from qiskit_aer import AerSimulator

from memq_dqc._logging import StepTimer, workflow_logging
from memq_dqc.network.network_graph import (
    REMOTE_GATE_EBIT_COST,
    REMOTE_SWAP_EBIT_COST,
)
from memq_dqc.preprocessing.qasm import (
    dump_qasm_program,
    parse_qasm_file,
    parse_qasm_source,
)
from memq_dqc.preprocessing.qasm.ast_utils import (
    is_comm_qubit_declaration,
    is_comm_qubit_reference,
    non_comm_qubits,
    rename_quantum_gate,
)

logger = logging.getLogger(__name__)

_REMOTE_OPERATION_COSTS: dict[str, int] = {
    "rswap": REMOTE_SWAP_EBIT_COST,
    "rcp": REMOTE_GATE_EBIT_COST,
    "rcry": REMOTE_GATE_EBIT_COST,
    "rcx": REMOTE_GATE_EBIT_COST,
    "rcz": REMOTE_GATE_EBIT_COST,
}


# TODO: verifier should also perform some hardware verification, eg. ensuring
# that local / remote gates reflect actual connectivity
def verify_distributed_circuit(
    original: ast.Program | str,
    distributed: ast.Program | str,
    *,
    method: Literal["sampling", "statevector"] = "sampling",
    shots: int = 50000000,
    fidelity_threshold: float = 0.90,
    max_qubits: int = 28,
    atol: float = 1e-9,
    verbosity: Literal["quiet", "info", "debug"] = "quiet",
) -> bool:
    """Verify the correctness of a distributed circuit.

    Evaluates the distributed circuit as a single, monolithic circuit where
    remote operations are assumed to operate perfectly, then compares it to
    the original circuit using the chosen ``method``:

    - ``"sampling"`` simulates both circuits for ``shots`` shots and compares
      their measured output distributions via Hellinger fidelity. This is an
      approximate, stochastic check whose accuracy depends on the shot count.
    - ``"statevector"`` computes each circuit's exact output distribution from
      its statevector (no shots) and checks that they match within ``atol``.
      The comparison is mapped through each circuit's own
      measurement-to-classical-bit mapping, so it is invariant to how data
      qubits are laid out or relabeled across QPUs. This is deterministic and
      exact, but memory grows as ``2**n`` in the qubit count ``n``.

    Args:
        original: The original circuit, either as a parsed OpenQASM 3
            program or a path to its ``.qasm`` file.
        distributed: The distributed circuit, either as a parsed
            OpenQASM 3 program or a path to its ``.qasm`` file.
        method: Verification method, either ``"sampling"`` (default) or
            ``"statevector"``.
        shots: Number of shots to execute the circuits for. Used only by the
            ``"sampling"`` method.
        fidelity_threshold: The minimum Hellinger fidelity required for the
            distributed circuit to be considered correct. Used only by the
            ``"sampling"`` method.
        max_qubits: Maximum circuit width the ``"statevector"`` method will
            attempt before raising, to avoid exhausting memory. Used only by
            the ``"statevector"`` method.
        atol: Maximum total-variation distance between the exact output
            distributions for the circuits to be considered equivalent. Used
            only by the ``"statevector"`` method.
        verbosity: Logging verbosity for this workflow call.

    Returns:
        True if the distributed circuit reproduces the original circuit's
        output distribution under the chosen method, False otherwise.

    Raises:
        ValueError: If ``method`` is not ``"sampling"`` or ``"statevector"``,
            or if the ``"statevector"`` method is used on a circuit wider than
            ``max_qubits`` or without measurements.
    """
    with workflow_logging(verbosity):
        if method not in ("sampling", "statevector"):
            raise ValueError(
                f"Unsupported method {method!r}; expected 'sampling' or "
                "'statevector'."
            )

        overall_timer = StepTimer()
        if method == "sampling":
            logger.info(
                "Starting distributed circuit verification: method=sampling "
                "shots=%d fidelity_threshold=%.3f.",
                shots,
                fidelity_threshold,
            )
        else:
            logger.info(
                "Starting distributed circuit verification: "
                "method=statevector max_qubits=%d atol=%.1e.",
                max_qubits,
                atol,
            )

        original_load_timer = StepTimer()
        if isinstance(original, ast.Program):
            qc_orig = qiskit.qasm3.loads(dump_qasm_program(original))
        else:
            qc_orig = qiskit.qasm3.load(original)
        logger.debug(
            "Loaded original circuit in %.3fs.",
            original_load_timer.elapsed_seconds(),
        )

        mono_timer = StepTimer()
        if isinstance(distributed, ast.Program):
            mono_qasm = dump_qasm_program(dist_to_mono_program(distributed))
        else:
            mono_qasm = dist_to_mono_circuit(distributed)
        qc_dist_mono = qiskit.qasm3.loads(str(mono_qasm))
        logger.debug(
            "Converted distributed circuit to monolithic form in %.3fs.",
            mono_timer.elapsed_seconds(),
        )

        if method == "sampling":
            return _verify_by_sampling(
                qc_orig,
                qc_dist_mono,
                shots=shots,
                fidelity_threshold=fidelity_threshold,
                overall_timer=overall_timer,
            )
        return _verify_by_statevector(
            qc_orig,
            qc_dist_mono,
            max_qubits=max_qubits,
            atol=atol,
            overall_timer=overall_timer,
        )


def _verify_by_sampling(
    qc_orig: QuantumCircuit,
    qc_dist_mono: QuantumCircuit,
    *,
    shots: int,
    fidelity_threshold: float,
    overall_timer: StepTimer,
) -> bool:
    """Compare two circuits by sampling and Hellinger fidelity.

    Args:
        qc_orig: The original circuit.
        qc_dist_mono: The monolithic form of the distributed circuit.
        shots: Number of shots to execute each circuit for.
        fidelity_threshold: Minimum Hellinger fidelity required to pass.
        overall_timer: Timer started when verification began, used for logging
            total elapsed time.

    Returns:
        True if the Hellinger fidelity meets ``fidelity_threshold``.
    """
    original_sim_timer = StepTimer()
    orig_counts = get_counts(qc_orig, shots=shots)
    logger.debug(
        "Simulated original circuit in %.3fs with %d distinct outcomes.",
        original_sim_timer.elapsed_seconds(),
        len(orig_counts),
    )

    distributed_sim_timer = StepTimer()
    mono_counts = get_counts(qc_dist_mono, shots=shots)
    logger.debug(
        "Simulated monolithic distributed circuit in %.3fs with %d "
        "distinct outcomes.",
        distributed_sim_timer.elapsed_seconds(),
        len(mono_counts),
    )

    fidelity_timer = StepTimer()
    fidelity = hellinger_fidelity(orig_counts, mono_counts)
    logger.debug(
        "Computed fidelity in %.3fs: fidelity=%.6f threshold=%.6f.",
        fidelity_timer.elapsed_seconds(),
        fidelity,
        fidelity_threshold,
    )

    elapsed = overall_timer.elapsed_seconds()
    if fidelity < fidelity_threshold:
        logger.warning(
            "Verification failed in %.3fs: fidelity=%.6f threshold=%.6f.",
            elapsed,
            fidelity,
            fidelity_threshold,
        )
        return False

    logger.info(
        "Verification succeeded in %.3fs: fidelity=%.6f threshold=%.6f.",
        elapsed,
        fidelity,
        fidelity_threshold,
    )
    return True


def _verify_by_statevector(
    qc_orig: QuantumCircuit,
    qc_dist_mono: QuantumCircuit,
    *,
    max_qubits: int,
    atol: float,
    overall_timer: StepTimer,
) -> bool:
    """Compare two circuits by exact statevector output distributions.

    Args:
        qc_orig: The original circuit.
        qc_dist_mono: The monolithic form of the distributed circuit.
        max_qubits: Maximum circuit width to attempt before raising.
        atol: Maximum total-variation distance to consider the circuits
            equivalent.
        overall_timer: Timer started when verification began, used for logging
            total elapsed time.

    Returns:
        True if the exact output distributions match within ``atol``.

    Raises:
        ValueError: If either circuit is wider than ``max_qubits``.
    """
    num_qubits = max(qc_orig.num_qubits, qc_dist_mono.num_qubits)
    if num_qubits > max_qubits:
        raise ValueError(
            f"Circuit uses {num_qubits} qubits, exceeding max_qubits="
            f"{max_qubits}. Statevector verification holds ~2**n amplitudes "
            "in memory; raise max_qubits to override."
        )

    distance_timer = StepTimer()
    orig_distribution = _exact_classical_distribution(qc_orig)
    mono_distribution = _exact_classical_distribution(qc_dist_mono)
    distance = _total_variation_distance(orig_distribution, mono_distribution)
    logger.debug(
        "Computed statevector distance in %.3fs: distance=%.3e atol=%.1e.",
        distance_timer.elapsed_seconds(),
        distance,
        atol,
    )

    elapsed = overall_timer.elapsed_seconds()
    if distance > atol:
        logger.warning(
            "Verification failed in %.3fs: distance=%.3e atol=%.1e.",
            elapsed,
            distance,
            atol,
        )
        return False

    logger.info(
        "Verification succeeded in %.3fs: distance=%.3e atol=%.1e.",
        elapsed,
        distance,
        atol,
    )
    return True


def _measured_qubits_in_clbit_order(circuit: QuantumCircuit) -> list[int]:
    """Return data-qubit indices ordered by the clbit they measure into.

    Args:
        circuit: A circuit whose final measurements define the mapping from
            qubits to classical bits.

    Returns:
        Qubit indices ordered by ascending classical-bit index, suitable as
        the ``qargs`` for :meth:`Statevector.probabilities_dict` so the
        resulting bitstrings are keyed in classical-register order.
    """
    clbit_to_qubit: dict[int, int] = {}
    for instruction in circuit.data:
        if isinstance(instruction.operation, Measure):
            qubit = circuit.find_bit(instruction.qubits[0]).index
            clbit = circuit.find_bit(instruction.clbits[0]).index
            clbit_to_qubit[clbit] = qubit
    return [clbit_to_qubit[clbit] for clbit in sorted(clbit_to_qubit)]


def _exact_classical_distribution(
    circuit: QuantumCircuit,
) -> dict[str, float]:
    """Compute the exact output distribution over classical outcomes.

    Simulates the circuit's pre-measurement statevector exactly (no shots) and
    maps it through the circuit's own measurement-to-classical-bit mapping.
    Mapping through measurements makes the distribution invariant to how data
    qubits are laid out or relabeled across QPUs.

    Args:
        circuit: A measured circuit to evaluate.

    Returns:
        A mapping from classical-outcome bitstrings to their exact
        probabilities.

    Raises:
        ValueError: If the circuit contains no measurements.
    """
    qargs = _measured_qubits_in_clbit_order(circuit)
    if not qargs:
        raise ValueError(
            "Statevector verification requires the circuit to contain "
            "measurements; none were found."
        )
    unmeasured = circuit.remove_final_measurements(inplace=False)
    statevector = Statevector(unmeasured)
    return statevector.probabilities_dict(qargs=qargs)


def _total_variation_distance(
    first: dict[str, float],
    second: dict[str, float],
) -> float:
    """Return the L1 distance between two probability distributions.

    Args:
        first: First distribution mapping outcomes to probabilities.
        second: Second distribution mapping outcomes to probabilities.

    Returns:
        The sum of absolute per-outcome probability differences.
    """
    outcomes = set(first) | set(second)
    return sum(
        abs(first.get(outcome, 0.0) - second.get(outcome, 0.0))
        for outcome in outcomes
    )


def get_counts(circuit: QuantumCircuit, shots: int) -> dict[str, int]:
    """Get the measurement outcomes for a given circuit using.

    Currently uses Qiskit Aer (must transitition to CUDAQ)
    # TODO: transition this to Nvidia CUDAQ
    # TODO: remove qiskit & qiskit_aer from UV and replace with CUDAQ

    Args:
        circuit: The QuantumCircuit object to execute.
        shots: Number of shots to execute the circuit for.

    Returns:
        A dictionary mapping measurement outcomes to their probabilities.
    """
    # qc = qiskit.qasm3.load(circuit_path)

    sim = AerSimulator()
    transpiled_qc = transpile(circuit, sim)
    result = sim.run(transpiled_qc, shots=shots).result()
    counts = result.get_counts()
    return counts


def dist_to_mono_circuit(dist_circuit_path: str) -> str:
    """Convert a distributed circuit to an executable monolithic circuit.

    Takes a distributed circuit and rewrites it into an equivalent,
    locally-executable form by:

    - replacing remote operations with their local equivalents (``rcx`` ->
      ``cx``, ``rcp`` -> ``cp``, ``rcry`` -> ``cry``, ``rcz`` -> ``cz``,
      ``rswap`` -> ``swap``), keeping only the two data-qubit operands;
    - dropping the cat-entanglement scaffolding (``catent`` / ``catdisent``)
      that wraps remote operations, since the local equivalents need no
      shared entanglement;
    - removing communication-qubit (``c*``) declarations and any remaining
      gates that act on communication qubits;
    - dropping the custom ``distgates.inc`` include, which is no longer
      referenced once remote operations are removed.

    Args:
        dist_circuit_path: Path to the distributed circuit file.

    Returns:
        A qasm string representing the monolithic version of the distributed
        circuit.
    """
    dist_prog = parse_qasm_file(dist_circuit_path)
    return dump_qasm_program(dist_to_mono_program(dist_prog))


def dist_to_mono_program(dist_program: ast.Program) -> ast.Program:
    """Rewrite a distributed program into a monolithic program.

    Performs the same rewrite as :func:`dist_to_mono_circuit` but operates
    on an in-memory program rather than a file, so no serialization
    round-trip is required. See :func:`dist_to_mono_circuit` for the full
    list of transformations applied.

    Args:
        dist_program: Parsed distributed OpenQASM 3 program.

    Returns:
        An equivalent monolithic OpenQASM 3 program with remote
        operations replaced by their local equivalents.
    """
    new_statements = []
    # iterate through program statements and remove remote gates
    for stmt in dist_program.statements:
        if not isinstance(stmt, ast.Statement):
            new_statements.append(stmt)
            continue
        # Remove custom library includes
        if isinstance(stmt, ast.Include):
            included_file = stmt.filename
            if "distgates.inc" in included_file:
                continue
        if is_comm_qubit_declaration(stmt):
            continue
        # Replace remote gates with local equivalents
        if isinstance(stmt, ast.QuantumGate):
            # replace RCX w/ CX
            name = stmt.name.name
            if name == "rcx":
                stmt = rename_quantum_gate(stmt, "cx")
                stmt.qubits = non_comm_qubits(stmt.qubits)[:2]
            elif name == "rcp":
                stmt = rename_quantum_gate(stmt, "cp")
                stmt.qubits = non_comm_qubits(stmt.qubits)[:2]
            elif name == "rcry":
                stmt = rename_quantum_gate(stmt, "cry")
                stmt.qubits = non_comm_qubits(stmt.qubits)[:2]
            elif name == "rcz":
                stmt = rename_quantum_gate(stmt, "cz")
                stmt.qubits = non_comm_qubits(stmt.qubits)[:2]
            # replace RSWAP w/ SWAP
            elif name == "rswap":
                stmt = rename_quantum_gate(stmt, "swap")
                stmt.qubits = non_comm_qubits(stmt.qubits)[:2]
            # drop cat-entanglement scaffolding around remote operations
            elif name in ("catent", "catdisent"):
                continue
            elif any(is_comm_qubit_reference(qubit) for qubit in stmt.qubits):
                continue
        new_statements.append(stmt)
    return ast.Program(version=dist_program.version, statements=new_statements)


def manual_cost_verification(qasm: str) -> int:
    """Return the total manual cost of remote operations in a QASM string.

    Costs are in e-bit pairs:
        ``rswap`` costs :data:`REMOTE_SWAP_EBIT_COST` (two teleportations).
        ``rcp``, ``rcry``, ``rcx``, and ``rcz`` each cost
        :data:`REMOTE_GATE_EBIT_COST`.

    Args:
        qasm: OpenQASM source code to analyze.

    Returns:
        Sum of remote operation costs.
    """
    program = parse_qasm_source(qasm)
    total_cost = 0

    for statement in program.statements:
        if not isinstance(statement, ast.QuantumGate):
            continue
        total_cost += _REMOTE_OPERATION_COSTS.get(statement.name.name, 0)

    return total_cost
