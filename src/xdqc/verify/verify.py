# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Verification of distributed circuit."""

from __future__ import annotations

import logging
from typing import Literal

import qiskit.qasm3
from openqasm3 import ast
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import hellinger_fidelity
from qiskit_aer import AerSimulator

from xdqc._logging import StepTimer, workflow_logging
from xdqc.preprocessing.qasm import (
    dump_qasm_program,
    is_comm_qubit_declaration,
    is_comm_qubit_reference,
    non_comm_qubits,
    parse_qasm_file,
    parse_qasm_source,
    rename_quantum_gate,
)

logger = logging.getLogger(__name__)

_REMOTE_OPERATION_COSTS: dict[str, int] = {
    "rswap": 2,
    "rcp": 1,
    "rcry": 1,
    "rcx": 1,
    "rcz": 1,
}


# TODO: verifier should also perform some hardware verification, eg. ensuring
# that local / remote gates reflect actual connectivity
def verify_distributed_circuit(
    original: ast.Program | str,
    distributed: ast.Program | str,
    shots: int = 50000000,
    fidelity_threshold: float = 0.90,
    *,
    verbosity: Literal["quiet", "info", "debug"] = "quiet",
) -> bool:
    """Verify the correctness of a distributed circuit.

    Evaluates distributed circuit as a single, monolithic circuit where remote
    operations are assumed to operate perfectly.

    Args:
        original: The original circuit, either as a parsed OpenQASM 3 program
            or a path to its ``.qasm`` file.
        distributed: The distributed circuit, either as a parsed OpenQASM 3
            program or a path to its ``.qasm`` file.
        shots: Number of shots to execute the circuits for.
        fidelity_threshold: The minimum fidelity required for the distributed
            circuit to be considered correct (Hellinger fidelity).
        verbosity: Logging verbosity for this workflow call.

    Returns:
        True if the distributed circuit gives nearly identical results to the
        original circuit, False otherwise - as determined by Hellinger fidelity
        between the two output distributions.
    """
    with workflow_logging(verbosity):
        overall_timer = StepTimer()
        logger.info(
            "Starting distributed circuit verification: shots=%d "
            "fidelity_threshold=%.3f.",
            shots,
            fidelity_threshold,
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

        original_sim_timer = StepTimer()
        orig_counts = get_counts(qc_orig, shots=shots)
        logger.debug(
            "Simulated original circuit in %.3fs with %d distinct outcomes.",
            original_sim_timer.elapsed_seconds(),
            len(orig_counts),
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
    """Rewrite a distributed program into an executable monolithic program.

    Performs the same rewrite as :func:`dist_to_mono_circuit` but operates on
    an in-memory program rather than a file, so no serialization round-trip is
    required. See :func:`dist_to_mono_circuit` for the full list of
    transformations applied.

    Args:
        dist_program: Parsed distributed OpenQASM 3 program.

    Returns:
        An equivalent monolithic OpenQASM 3 program with remote operations
        replaced by their local equivalents.
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

    Costs:
        ``rswap`` costs 4.
        ``rcp``, ``rcry``, ``rcx``, and ``rcz`` each cost 2.

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
