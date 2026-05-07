###
#  GATE GROUPING ###
# simple conditions: https://arxiv.org/pdf/2503.19082
# 1) all two-qubit gates share a common control qubit
# 2) two-qubit gates are adjacent on the control
# 3) Single-qubit gates on the common control are diagonal or anti-diagonal.
from typing import List

from memq_dqc.partition.partitioner import BasePartitioner
from memq_dqc.preprocessing.qasm.cleaning import extract_cleaned_statements
from memq_dqc.preprocessing.qasm.types import (
    CleanedQuantumGate,
)
from memq_dqc.network import NetworkGraph


import openqasm3.ast as ast


class GateGroupingPartitioner(BasePartitioner):
    """
    Gate-grouping-based partitioner (eventaully may be merged with other designs)
    """

    def __init__(
        self,
        network: NetworkGraph,
        program: ast.Program,
    ):
        super().__init__(network, program)

    def run(self) -> None:
        """
        Insert doctring here
        """
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
