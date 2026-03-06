# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Verification of distributed circuit."""

import qiskit.qasm3
from openqasm3 import ast
from qiskit import QuantumCircuit, transpile
from qiskit.quantum_info import hellinger_fidelity
from qiskit_aer import AerSimulator

from memq_dqc.preprocessing.qasm import (
    dump_qasm_program,
    is_comm_qubit_declaration,
    is_comm_qubit_reference,
    non_comm_qubits,
    parse_qasm_file,
    parse_qasm_source,
    rename_quantum_gate,
)

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
    original_circuit_path: str,
    dist_circuit_path: str,
    shots: int = 50000000,
    fidelity_threshold: float = 0.90,
) -> bool:
    """Verify the correctness of a distributed circuit.

    Evaluates distributed circuit as a single, monolithic circuit where remote
    operations are assumed to operate perfectly.

    Args:
        original_circuit_path: Path to the original circuit file.
        dist_circuit_path: Path to the distributed circuit file.
        shots: Number of shots to execute the circuits for.
        fidelity_threshold: The minimum fidelity required for the distributed
            circuit to be considered correct (Hellinger fidelity).

    Returns:
        True if the distributed circuit gives nearly identical results to the
        original circuit, False otherwise - as determined by Hellinger fidelity
        between the two output distributions.
    """
    qc_orig = qiskit.qasm3.load(original_circuit_path)
    orig_counts = get_counts(qc_orig, shots=shots)
    # print("Original circuit counts:", orig_counts)
    mono_circuit = dist_to_mono_circuit(dist_circuit_path)
    qc_dist_mono = qiskit.qasm3.loads(str(mono_circuit))
    # print strng representation of monolithic circuit

    mono_counts = get_counts(qc_dist_mono, shots=shots)
    fidelity = hellinger_fidelity(orig_counts, mono_counts)
    # TODO: replace print with proper logging (and update commented-out prints throughout)
    if fidelity < fidelity_threshold:
        print(
            f"Verification failed: fidelity {fidelity} is below threshold {fidelity_threshold}"
        )
        return False
    print(
        f"Verification succeeded: fidelity {fidelity} is above threshold {fidelity_threshold}"
    )
    return True
    # print("Original circuit counts:", orig_counts)
    # print("Monolithic version of distributed circuit counts:", mono_counts)


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
    """Convert a distributed circuit to a monolithic QuantumCircuit.

    Rudimentary tool that takes distributed circuit and replaces remote
    gates with local equivalent gates. Specifically RSWAP gates (TODO:
    must get rid of RSWAPS and fix this function) are replaced with SWAP gates,
    and R2Q gates (TODO: right now this is just (R)CX) are replaced with
    local equivalent.

    Args:
        dist_circuit_path: Path to the distributed circuit file.

    Returns:
        A qasm string representing the monolithic version of the distributed
        circuit.
    """
    # TODO: must be tested!
    dist_prog = parse_qasm_file(dist_circuit_path)
    new_statements = []
    # iterate through program statements and remove remote gates
    for stmt in dist_prog.statements:
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
            elif any(is_comm_qubit_reference(qubit) for qubit in stmt.qubits):
                continue
        new_statements.append(stmt)
    mono_prog = ast.Program(
        version=dist_prog.version, statements=new_statements
    )
    return dump_qasm_program(mono_prog)


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
