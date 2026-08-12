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

"""Cat-entanglement statement builders for distributed DAG construction."""

from __future__ import annotations

from collections.abc import Sequence

from openqasm3 import ast

from xdqc.circuit.dag.remap import (
    _physical_to_circuit_qubit,
    _to_ast_qubit_ref,
)
from xdqc.network import PhysicalQubit
from xdqc.preprocessing.qasm.ast_utils import clone_statement_node
from xdqc.preprocessing.qasm.types import CircuitQubit, CleanedQuantumGate


def _build_entanglement_statements(
    data_qubits: Sequence[CircuitQubit],
    comm_pairs: Sequence[tuple[PhysicalQubit, PhysicalQubit]],
) -> tuple[CleanedQuantumGate, CleanedQuantumGate]:
    """Build CatEntangle and CatDisentangle statements.

    Args:
        data_qubits: Routed data operands for the remote operation.
        comm_pairs: Physical communication-qubit pairs to entangle.

    Returns:
        The catent and catdisent statements for the communication pairs.
    """
    comm_qubits = [
        _physical_to_circuit_qubit(qubit)
        for comm_pair in comm_pairs
        for qubit in comm_pair
    ]
    gate_qubits = [*data_qubits, *comm_qubits]
    gate_qubit_refs: list[ast.IndexedIdentifier | ast.Identifier] = [
        _to_ast_qubit_ref(qubit) for qubit in gate_qubits
    ]
    cat_ent_node = clone_statement_node(
        ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("catent"),
            arguments=[],
            qubits=gate_qubit_refs,
        )
    )
    cat_disent_node = clone_statement_node(
        ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier("catdisent"),
            arguments=[],
            qubits=gate_qubit_refs,
        )
    )
    cat_ent_gate = CleanedQuantumGate(
        statement_type=ast.QuantumGate,
        node=cat_ent_node,
        is_op=True,
        name="catent",
        qubits=gate_qubits,
    )
    cat_disent_gate = CleanedQuantumGate(
        statement_type=ast.QuantumGate,
        node=cat_disent_node,
        is_op=True,
        name="catdisent",
        qubits=gate_qubits,
    )
    return cat_ent_gate, cat_disent_gate
