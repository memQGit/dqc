"""Experimental gate-grouping partitioning implementation."""

import openqasm3.ast as ast

from memq_dqc.network import NetworkGraph
from memq_dqc.partition.partitioner import BasePartitioner
from memq_dqc.preprocessing.qasm.cleaning import extract_cleaned_statements
from memq_dqc.preprocessing.qasm.types import (
    CleanedQuantumGate,
)


class GateGroupingPartitioner(BasePartitioner):
    """Gate-grouping-based partitioner."""

    def __init__(
        self,
        network: NetworkGraph,
        program: ast.Program,
    ) -> None:
        """Initialize the gate-grouping partitioner.

        Args:
            network: Network graph describing available resources.
            program: Parsed OpenQASM 3 program.
        """
        super().__init__(network, program)

    def run(self) -> None:
        """Print two-qubit gate statements identified in the circuit."""
        program = self.circuit.mono.program
        # get the cleaned program statements
        cleaned_statements = extract_cleaned_statements(program)
        for statement in cleaned_statements:
            if (
                isinstance(statement, CleanedQuantumGate)
                and len(statement.qubits) == 2
            ):
                # identify 2-qubit gates
                print(statement.qubits)
                print(statement.name)


"""
INTERCHANGEABLE
cp(λ)
cz
swap

# NOT INTERCHANGEABLE
cx
cy
crx
cry
crz
ch
cu"""
