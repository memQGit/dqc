# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import pytest
from openqasm3 import ast

from memq_dqc.builder import extract_distributed_circuit, identify_remote_gates
from memq_dqc.graph import NetworkGraph
from memq_dqc.io.qasm import load_qasm_program
from memq_dqc.partition import QPU, Partitioner
from memq_dqc.partition.partitioner import BasePartitioner
from memq_dqc.utils import get_windows


class _CustomQpuIdPartitioner(BasePartitioner):
    """Partitioner used by tests to emit non-zero-based QPU IDs."""

    def run(self) -> None:
        """Populate schedule/windows with fixed assignments."""
        windows = get_windows(self.dag, window_length=2)
        self.windows = windows
        self.schedule = [
            {QPU(id=1): {0, 1, 2}, QPU(id=2): {3, 4, 5}} for _ in windows
        ]
        self.cost = 0.0


def _declaration_size(statement: ast.QubitDeclaration) -> int:
    """Return the declared qubit register size."""
    if statement.size is None:
        return 1
    if isinstance(statement.size, ast.IntegerLiteral):
        return statement.size.value
    raise TypeError("Qubit declaration size must be an integer literal.")


def test_extract_distributed_circuit_requires_run(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )

    with pytest.raises(ValueError, match=r"partitioner.run\(\)"):
        extract_distributed_circuit(partitioner)


def test_identify_remote_gates_requires_run(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )

    with pytest.raises(ValueError, match=r"partition.run\(\)"):
        identify_remote_gates(partitioner.dag, partitioner)


def test_extract_distributed_circuit_returns_program(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    distributed_program = extract_distributed_circuit(partitioner)

    assert isinstance(distributed_program, ast.Program)
    assert distributed_program.statements


def test_extract_distributed_circuit_adds_comm_registers(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    distributed_program = extract_distributed_circuit(partitioner)
    declarations = [
        statement
        for statement in distributed_program.statements
        if isinstance(statement, ast.QubitDeclaration)
    ]
    declaration_sizes = {
        statement.qubit.name: _declaration_size(statement)
        for statement in declarations
    }

    assert declaration_sizes["q0"] == 3
    assert declaration_sizes["q1"] == 3
    assert declaration_sizes["c0"] == 1
    assert declaration_sizes["c1"] == 1


def test_extract_distributed_circuit_uses_full_comp_register_capacity(
    simple1_circuit_path,
    simple1_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network_path = simple1_network_path.parent / "simple_8comp_4comm.json"
    network = NetworkGraph(str(network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    distributed_program = extract_distributed_circuit(partitioner)
    declarations = [
        statement
        for statement in distributed_program.statements
        if isinstance(statement, ast.QubitDeclaration)
    ]
    declaration_sizes = {
        statement.qubit.name: _declaration_size(statement)
        for statement in declarations
    }

    assert declaration_sizes["q0"] == 4
    assert declaration_sizes["q1"] == 4
    assert declaration_sizes["c0"] == 2
    assert declaration_sizes["c1"] == 2


def test_extract_distributed_circuit_nonzero_based_qpu_ids(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_CustomQpuIdPartitioner(network, program),
    )
    partitioner.run()

    distributed_program = extract_distributed_circuit(partitioner)
    declarations = [
        statement
        for statement in distributed_program.statements
        if isinstance(statement, ast.QubitDeclaration)
    ]
    declaration_sizes = {
        statement.qubit.name: _declaration_size(statement)
        for statement in declarations
    }

    assert declaration_sizes["q1"] == 3
    assert declaration_sizes["q2"] == 3
    assert declaration_sizes["c1"] == 1
    assert declaration_sizes["c2"] == 1


def test_extract_distributed_circuit_sets_exact_entanglement_cost(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    class _SingleRemoteGatePartitioner(BasePartitioner):
        def run(self) -> None:
            self.windows = [self.dag.ops]
            self.schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]
            self.cost = 0.0

    qasm_path = tmp_path / "single_remote.qasm"
    qasm_path.write_text(
        "OPENQASM 3.0;\nqubit[2] q;\ncx q[0], q[1];\n",
        encoding="utf-8",
    )
    program = load_qasm_program(str(qasm_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_SingleRemoteGatePartitioner(network, program),
    )
    partitioner.run()

    extract_distributed_circuit(partitioner)

    assert partitioner.cost == 1.0
