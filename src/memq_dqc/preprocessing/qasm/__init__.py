# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""OpenQASM 3 preprocessing utilities."""

from memq_dqc.preprocessing.qasm.analysis import (
    count_total_qubits,
    extract_qubit_index,
    extract_two_qubit_gates,
)
from memq_dqc.preprocessing.qasm.ast_utils import (
    clone_statement_node,
    rename_quantum_gate,
)
from memq_dqc.preprocessing.qasm.cleaned_types import (
    Cbit,
    CleanedClassicalDeclaration,
    CleanedIncludeStatement,
    CleanedQuantumGate,
    CleanedQuantumGateDefinition,
    CleanedQuantumMeasurementStatement,
    CleanedQubitDeclaration,
    CleanedStatement,
)
from memq_dqc.preprocessing.qasm.cleaning import (
    clean_statement,
    extract_cleaned_statements,
)
from memq_dqc.qasm.types import Qubit

__all__ = [
    "Cbit",
    "CleanedClassicalDeclaration",
    "CleanedIncludeStatement",
    "CleanedQuantumGate",
    "CleanedQuantumGateDefinition",
    "CleanedQuantumMeasurementStatement",
    "CleanedQubitDeclaration",
    "CleanedStatement",
    "Qubit",
    "clean_statement",
    "clone_statement_node",
    "count_total_qubits",
    "extract_cleaned_statements",
    "extract_qubit_index",
    "extract_two_qubit_gates",
    "rename_quantum_gate",
]
