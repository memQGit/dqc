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

"""OpenQASM 3 preprocessing utilities."""

from xdqc.preprocessing.qasm.analysis import (
    count_total_qubits,
    extract_qubit_index,
    extract_qubit_register_sizes,
    extract_two_qubit_gates,
)
from xdqc.preprocessing.qasm.ast_utils import (
    clone_statement_node,
    indexed_qubit_reference,
    is_comm_qubit_declaration,
    is_comm_qubit_reference,
    non_comm_qubits,
    rename_quantum_gate,
)
from xdqc.preprocessing.qasm.cleaning import (
    clean_statement,
    extract_cleaned_statements,
)
from xdqc.preprocessing.qasm.io import (
    dump_qasm_program,
    load_qasm_program,
    parse_qasm_file,
    parse_qasm_source,
)
from xdqc.preprocessing.qasm.types import (
    Cbit,
    CircuitQubit,
    CleanedClassicalDeclaration,
    CleanedIncludeStatement,
    CleanedQuantumGate,
    CleanedQuantumGateDefinition,
    CleanedQuantumMeasurementStatement,
    CleanedQubitDeclaration,
    CleanedStatement,
)

__all__ = [
    "Cbit",
    "CircuitQubit",
    "CleanedClassicalDeclaration",
    "CleanedIncludeStatement",
    "CleanedQuantumGate",
    "CleanedQuantumGateDefinition",
    "CleanedQuantumMeasurementStatement",
    "CleanedQubitDeclaration",
    "CleanedStatement",
    "clean_statement",
    "clone_statement_node",
    "count_total_qubits",
    "dump_qasm_program",
    "extract_cleaned_statements",
    "extract_qubit_register_sizes",
    "extract_qubit_index",
    "extract_two_qubit_gates",
    "indexed_qubit_reference",
    "is_comm_qubit_declaration",
    "is_comm_qubit_reference",
    "load_qasm_program",
    "non_comm_qubits",
    "parse_qasm_file",
    "parse_qasm_source",
    "rename_quantum_gate",
]
