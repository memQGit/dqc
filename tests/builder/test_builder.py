# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import logging
from typing import Any, cast

import pytest
from openqasm3 import ast

from memq_dqc.builder import extract_distributed_circuit, identify_remote_gates
from memq_dqc.network import NetworkGraph
from memq_dqc.partition import Partitioner
from memq_dqc.partition.partitioner import QPU, BasePartitioner
from memq_dqc.preprocessing.qasm.io import load_qasm_program
from memq_dqc.utils import get_windows


class _CustomQpuIdPartitioner(BasePartitioner):
    """Partitioner used by tests to emit non-zero-based QPU IDs."""

    def run(self) -> None:
        """Populate schedule/windows with fixed assignments."""
        windows = get_windows(self.circuit, window_length=2)
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
        identify_remote_gates(partitioner.circuit, partitioner)


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


def test_partitioner_distributed_program_extracts_lazily(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    distributed_program = partitioner.distributed_program

    assert isinstance(distributed_program, ast.Program)
    assert partitioner.circuit.distributed is not None
    assert distributed_program is partitioner.circuit.distributed.program


def test_partitioner_distributed_circuit_extracts_once_and_caches(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    first = partitioner.distributed_circuit
    second = partitioner.distributed_circuit

    assert first is second
    assert partitioner.distributed_program is first.program


def test_partitioner_run_with_ebit_assignment_extracts_distributed_circuit(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )

    partitioner.run(ebit_assignment=False)

    distributed = partitioner.circuit.distributed
    assert distributed is not None
    assert partitioner.distributed_circuit is distributed
    assert distributed.ebit_candidates_by_op_id is not None


def test_partitioner_lazy_extraction_honors_run_ebit_assignment(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )

    partitioner.run(ebit_assignment=False)
    first = partitioner.distributed_circuit

    partitioner.run()
    second = partitioner.distributed_circuit

    assert first is not second
    assert first.ebit_candidates_by_op_id is not None
    assert second.ebit_candidates_by_op_id is None


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


def test_extract_distributed_circuit_deferred_ebits_omits_comm_registers(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    distributed_program = extract_distributed_circuit(
        partitioner,
        ebit_assignment=False,
    )
    declarations = [
        statement
        for statement in distributed_program.statements
        if isinstance(statement, ast.QubitDeclaration)
    ]
    declaration_names = {statement.qubit.name for statement in declarations}

    assert "c0" not in declaration_names
    assert "c1" not in declaration_names


def test_extract_distributed_circuit_deferred_ebits_omits_comm_operands(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run(ebit_assignment=False)

    remote_ops = [
        op for op in partitioner.distributed_circuit.ops if op.is_remote
    ]

    assert remote_ops
    assert all(len(op.qubits) == 2 for op in remote_ops)
    assert all(
        qubit.register_name.startswith("q")
        for op in remote_ops
        for qubit in op.qubits
    )
    assert partitioner.distributed_circuit.ebit_candidates_by_op_id is not None


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

    assert declaration_sizes["q1"] == 4
    assert declaration_sizes["q2"] == 4
    assert declaration_sizes["c1"] == 2
    assert declaration_sizes["c2"] == 2


def test_extract_distributed_circuit_nonzero_based_qpu_ids(
    simple1_circuit_path,
    simple1_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network_path = simple1_network_path.parent / "simple_8comp_4comm.json"
    network = NetworkGraph(str(network_path))
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

    assert declaration_sizes["q1"] == 4
    assert declaration_sizes["q2"] == 4
    assert declaration_sizes["c1"] == 2
    assert declaration_sizes["c2"] == 2


def test_extract_distributed_circuit_rejects_non_network_schedule_qpu_ids(
    simple1_circuit_path,
    simple1_network_path,
) -> None:
    class _MismatchedQpuIdPartitioner(BasePartitioner):
        def run(self) -> None:
            windows = get_windows(self.circuit, window_length=2)
            self.windows = windows
            self.schedule = [
                {QPU(id=0): {0, 1, 2}, QPU(id=1): {3, 4, 5}} for _ in windows
            ]
            self.cost = 0.0

    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(simple1_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_MismatchedQpuIdPartitioner(network, program),
    )
    # TODO: should update test or check this
    with pytest.raises(
        ValueError,
    ):
        partitioner.run()


def test_extract_distributed_circuit_sets_exact_entanglement_cost(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    class _SingleRemoteGatePartitioner(BasePartitioner):
        def run(self) -> None:
            self.windows = [self.circuit.mono.ops]
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


def test_extract_distributed_circuit_quiet_emits_no_logs(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    caplog.set_level(logging.DEBUG, logger="memq_dqc")
    extract_distributed_circuit(partitioner)

    records = [
        record
        for record in caplog.records
        if record.name.startswith("memq_dqc")
    ]
    assert records == []


def test_extract_distributed_circuit_info_logs_summary(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    caplog.set_level(logging.DEBUG, logger="memq_dqc")
    extract_distributed_circuit(partitioner, verbosity="info")

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("memq_dqc")
    ]
    assert "Starting distributed circuit extraction." in messages
    assert any(
        "Distributed circuit extraction completed in" in msg
        for msg in messages
    )


def test_extract_distributed_circuit_debug_logs_diagnostics(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    caplog.set_level(logging.DEBUG, logger="memq_dqc")
    extract_distributed_circuit(partitioner, verbosity="debug")

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("memq_dqc")
    ]
    assert any("Validated partitioner outputs:" in msg for msg in messages)
    assert any("Distributed statement count:" in msg for msg in messages)


def test_extract_distributed_circuit_rejects_invalid_verbosity(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()

    invalid_verbosity = cast(Any, "loud")
    with pytest.raises(ValueError, match="Unsupported verbosity"):
        extract_distributed_circuit(
            partitioner,
            verbosity=invalid_verbosity,
        )
