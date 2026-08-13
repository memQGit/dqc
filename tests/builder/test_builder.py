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

import io
import logging
from types import SimpleNamespace
from typing import Any, cast

import openqasm3
import pytest
from openqasm3 import ast

from xdqc.builder import extract_distributed_circuit, identify_remote_gates
from xdqc.builder.circuit_extractor import _exact_entanglement_cost
from xdqc.network import NetworkGraph
from xdqc.partition import Partitioner
from xdqc.partition.partitioner import QPU, BasePartitioner
from xdqc.preprocessing.qasm.io import load_qasm_program
from xdqc.preprocessing.qasm.types import CircuitQubit, CleanedQuantumGate
from xdqc.scheduler import SchedulerHardwareProfile
from xdqc.utils.circuit_utils import get_windows


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


class _TwoQubitRemotePartitioner(BasePartitioner):
    def run(self) -> None:
        self.windows = [self.circuit.mono.ops]
        self.schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]
        self.cost = 0.0


class _ThreeQubitSharedControlPartitioner(BasePartitioner):
    def run(self) -> None:
        self.windows = [self.circuit.mono.ops]
        self.schedule = [{QPU(id=0): {1, 2}, QPU(id=1): {0}}]
        self.cost = 0.0


def _declaration_size(statement: ast.QubitDeclaration) -> int:
    """Return the declared qubit register size."""
    if statement.size is None:
        return 1
    if isinstance(statement.size, ast.IntegerLiteral):
        return statement.size.value
    raise TypeError("Qubit declaration size must be an integer literal.")


def _cleaned_gate(name: str, qubits: list[CircuitQubit]) -> CleanedQuantumGate:
    return CleanedQuantumGate(
        statement_type=ast.QuantumGate,
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier(name),
            arguments=[],
            qubits=[],
        ),
        is_op=True,
        name=name,
        qubits=qubits,
    )


def _groupable_remote_program(tmp_path) -> ast.Program:
    qasm_path = tmp_path / "groupable_remote.qasm"
    qasm_path.write_text(
        "\n".join(
            [
                "OPENQASM 3.0;",
                'include "stdgates.inc";',
                "qubit[2] q;",
                "cx q[0], q[1];",
                "rz(0.125) q[1];",
                "cx q[0], q[1];",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return load_qasm_program(str(qasm_path))


def _shared_control_remote_program(tmp_path) -> ast.Program:
    qasm_path = tmp_path / "shared_control_remote.qasm"
    qasm_path.write_text(
        "\n".join(
            [
                "OPENQASM 3.0;",
                'include "stdgates.inc";',
                "qubit[3] q;",
                "cx q[0], q[1];",
                "rz(0.125) q[1];",
                "cx q[0], q[2];",
                "rz(0.25) q[0];",
                "cx q[0], q[1];",
            ]
        )
        + "\n",
        encoding="utf-8",
    )
    return load_qasm_program(str(qasm_path))


def _quantum_gate_names(partitioner: Partitioner) -> list[str]:
    return [
        statement.name
        for statement in partitioner.distributed_circuit.statements
        if isinstance(statement, CleanedQuantumGate)
    ]


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


def test_partitioner_emits_grouped_remote_gates_by_default(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = _groupable_remote_program(tmp_path)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_TwoQubitRemotePartitioner(network, program),
    )
    partitioner.run()

    assert _quantum_gate_names(partitioner) == [
        "catent",
        "rcx",
        "rz",
        "rcx",
        "catdisent",
    ]
    assert partitioner.cost == 1.0


def test_partitioner_run_group_gates_false_disables_emitted_grouping(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = _groupable_remote_program(tmp_path)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_TwoQubitRemotePartitioner(network, program),
    )
    partitioner.run(group_gates=False)

    assert _quantum_gate_names(partitioner) == [
        "catent",
        "rcx",
        "catdisent",
        "rz",
        "catent",
        "rcx",
        "catdisent",
    ]
    assert partitioner.cost == 2.0


def test_partitioner_groups_shared_control_remote_gates_with_distinct_targets(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = _shared_control_remote_program(tmp_path)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_ThreeQubitSharedControlPartitioner(network, program),
    )
    partitioner.run()

    assert _quantum_gate_names(partitioner) == [
        "catent",
        "rcx",
        "rz",
        "rcx",
        "rz",
        "rcx",
        "catdisent",
    ]
    assert partitioner.cost == 1.0


def test_partitioner_max_group_size_limits_emitted_grouping(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = _shared_control_remote_program(tmp_path)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_ThreeQubitSharedControlPartitioner(network, program),
    )
    partitioner.run(max_group_size=2)

    assert _quantum_gate_names(partitioner) == [
        "catent",
        "rcx",
        "rz",
        "rcx",
        "catdisent",
        "rz",
        "catent",
        "rcx",
        "catdisent",
    ]
    assert partitioner.cost == 2.0


def test_partitioner_group_size_profile_caps_grouping_by_epr_lifetime(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = _shared_control_remote_program(tmp_path)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_ThreeQubitSharedControlPartitioner(network, program),
    )
    # A realistic 50us EPR lifetime is far shorter than this profile's
    # entanglement generation time, leaving a negative budget so no gate can
    # join the seed and grouping collapses to one remote gate per
    # cat-entanglement region. Passed explicitly because the packaged default
    # lifetime is temporarily effectively-infinite (see the epr_lifetime note
    # in settings.toml).
    partitioner.run(
        group_size_profile=SchedulerHardwareProfile(epr_lifetime=50.0)
    )

    assert _quantum_gate_names(partitioner) == [
        "catent",
        "rcx",
        "catdisent",
        "rz",
        "catent",
        "rcx",
        "catdisent",
        "rz",
        "catent",
        "rcx",
        "catdisent",
    ]
    assert partitioner.cost == 3.0


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


def _swap_partitioner_case(tmp_path, network_path):
    class _SplitSwapPartitioner(BasePartitioner):
        def run(self) -> None:
            self.windows = [self.circuit.mono.ops]
            self.schedule = [{QPU(id=0): {0}, QPU(id=1): {1}}]
            self.cost = 0.0

    qasm_path = tmp_path / "cross_qpu_swap.qasm"
    qasm_path.write_text(
        'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
        "qubit[2] q;\nswap q[0], q[1];\n",
        encoding="utf-8",
    )
    program = load_qasm_program(str(qasm_path))
    network = NetworkGraph(str(network_path))
    return Partitioner(
        network,
        program,
        algo=_SplitSwapPartitioner(network, program),
    )


def test_cross_qpu_swap_rejected_without_two_disjoint_links(
    tmp_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    # One link between the QPUs cannot carry the two teleports a remote
    # swap needs, and no alternate route exists, so this placement must be
    # rejected rather than costed as a cheap single-link remote gate.
    partitioner = _swap_partitioner_case(
        tmp_path, three_comp_one_comm_x2_network_path
    )

    with pytest.raises(
        ValueError,
        match="requires two disjoint communication links",
    ):
        partitioner.run()


def test_cross_qpu_swap_routed_between_non_adjacent_qpus(
    tmp_path,
    chain_3qpu_2pairs_network_path,
) -> None:
    # Regression: a source swap landing on QPUs with no direct link used to
    # be rejected outright, even though the builder routes it as a chain of
    # adjacent remote swaps. Price the routed cost instead.
    class _SplitSwapPartitioner(BasePartitioner):
        def run(self) -> None:
            self.windows = [self.circuit.mono.ops]
            # QPU 1 is the empty intermediary the routed swap hops through.
            self.schedule = [
                {QPU(id=0): {0}, QPU(id=1): set(), QPU(id=2): {1}}
            ]
            self.cost = 0.0

    qasm_path = tmp_path / "cross_qpu_swap.qasm"
    qasm_path.write_text(
        'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
        "qubit[2] q;\nswap q[0], q[1];\n",
        encoding="utf-8",
    )
    program = load_qasm_program(str(qasm_path))
    network = NetworkGraph(str(chain_3qpu_2pairs_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_SplitSwapPartitioner(network, program),
    )

    partitioner.run()

    # No direct link, so a single remote swap is impossible, but the routed
    # chain through QPU 1 is, and that is what the cost must reflect.
    assert network.supports_remote_swap(0, 2) is False
    assert partitioner.cost == float(network.remote_swap_ebit_cost(0, 2))

    # And the routed swap is actually buildable, not just priceable: the
    # single source swap lowers to more than one adjacent remote swap.
    distributed_program = extract_distributed_circuit(partitioner)
    output = io.StringIO()
    openqasm3.dump(distributed_program, output)

    assert output.getvalue().count("rswap") > 1


def test_cross_qpu_swap_costed_as_remote_swap_with_two_links(
    tmp_path,
    simple1_network_path,
) -> None:
    # QPUs 1 and 2 have two disjoint links, but this partitioner places the
    # operands on QPU ids 0 and 1, so remap the schedule onto real QPU ids.
    class _SplitSwapPartitioner(BasePartitioner):
        def run(self) -> None:
            self.windows = [self.circuit.mono.ops]
            self.schedule = [{QPU(id=1): {0}, QPU(id=2): {1}}]
            self.cost = 0.0

    qasm_path = tmp_path / "cross_qpu_swap.qasm"
    qasm_path.write_text(
        'OPENQASM 3.0;\ninclude "stdgates.inc";\n'
        "qubit[2] q;\nswap q[0], q[1];\n",
        encoding="utf-8",
    )
    program = load_qasm_program(str(qasm_path))
    network = NetworkGraph(str(simple1_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo=_SplitSwapPartitioner(network, program),
    )

    partitioner.run()

    # Accepted, and priced as a remote swap rather than a remote gate: the
    # two costs differ here, so this pins which path was taken.
    assert network.supports_remote_swap(1, 2) is True
    assert network.remote_gate_ebit_cost(1, 2) == 1
    assert partitioner.cost == float(network.remote_swap_ebit_cost(1, 2))
    assert partitioner.cost != float(network.remote_gate_ebit_cost(1, 2))


def test_exact_entanglement_cost_counts_catent_pairs() -> None:
    q0 = CircuitQubit("q0", 0)
    q1 = CircuitQubit("q1", 0)
    c0 = CircuitQubit("c0", 0)
    c1 = CircuitQubit("c1", 0)
    c0_pair_2 = CircuitQubit("c0", 1)
    c1_pair_2 = CircuitQubit("c1", 1)
    # A cat-entangled remote gate costs one pair; a standalone remote swap
    # costs two.
    distributed = SimpleNamespace(
        statements=[
            _cleaned_gate("catent", [q0, q1, c0, c1]),
            _cleaned_gate("rcx", [q0, q1, c0, c1]),
            _cleaned_gate("catdisent", [q0, q1, c0, c1]),
            _cleaned_gate(
                "rswap",
                [q0, q1, c0, c1, c0_pair_2, c1_pair_2],
            ),
        ],
    )

    assert _exact_entanglement_cost(cast(Any, distributed)) == 3.0


def test_exact_entanglement_cost_counts_deferred_rswap() -> None:
    # With e-bit operands stripped for deferred assignment, a remote swap
    # still costs two pairs.
    q0 = CircuitQubit("q0", 0)
    q1 = CircuitQubit("q1", 0)
    distributed = SimpleNamespace(
        statements=[_cleaned_gate("rswap", [q0, q1])],
    )

    assert _exact_entanglement_cost(cast(Any, distributed)) == 2.0


def test_exact_entanglement_cost_counts_deferred_remote_gate() -> None:
    # A cat-entangled remote gate with stripped operands costs one pair.
    q0 = CircuitQubit("q0", 0)
    q1 = CircuitQubit("q1", 0)
    distributed = SimpleNamespace(
        statements=[
            _cleaned_gate("catent", [q0, q1]),
            _cleaned_gate("rcx", [q0, q1]),
            _cleaned_gate("catdisent", [q0, q1]),
        ],
    )

    assert _exact_entanglement_cost(cast(Any, distributed)) == 1.0


def test_exact_entanglement_cost_rejects_unmatched_catent() -> None:
    q0 = CircuitQubit("q0", 0)
    q1 = CircuitQubit("q1", 0)
    c0 = CircuitQubit("c0", 0)
    c1 = CircuitQubit("c1", 0)
    distributed = SimpleNamespace(
        statements=[
            _cleaned_gate("catent", [q0, q1, c0, c1]),
            _cleaned_gate("rcx", [q0, q1, c0, c1]),
        ],
    )

    with pytest.raises(ValueError, match="no matching catdisent"):
        _exact_entanglement_cost(cast(Any, distributed))


def test_exact_entanglement_cost_rejects_mismatched_catdisent() -> None:
    q0 = CircuitQubit("q0", 0)
    q1 = CircuitQubit("q1", 0)
    c0 = CircuitQubit("c0", 0)
    c1 = CircuitQubit("c1", 0)
    c2 = CircuitQubit("c1", 1)
    distributed = SimpleNamespace(
        statements=[
            _cleaned_gate("catent", [q0, q1, c0, c1]),
            _cleaned_gate("rcx", [q0, q1, c0, c1]),
            _cleaned_gate("catdisent", [q0, q1, c0, c2]),
        ],
    )

    with pytest.raises(ValueError, match="do not match"):
        _exact_entanglement_cost(cast(Any, distributed))


def test_extract_distributed_circuit_dumps_catent_statements(
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
    output = io.StringIO()
    openqasm3.dump(distributed_program, output)

    dumped_qasm = output.getvalue()
    assert "catent q0[2], q1[0], c0[0], c1[0];" in dumped_qasm
    assert "catdisent q0[2], q1[0], c0[0], c1[0];" in dumped_qasm


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

    caplog.set_level(logging.DEBUG, logger="xdqc")
    extract_distributed_circuit(partitioner)

    records = [
        record for record in caplog.records if record.name.startswith("xdqc")
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

    caplog.set_level(logging.DEBUG, logger="xdqc")
    extract_distributed_circuit(partitioner, verbosity="info")

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("xdqc")
    ]
    assert "Starting distributed circuit extraction." in messages
    assert any(
        "Distributed circuit extraction completed in" in msg
        and "avg_group_size=" in msg
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

    caplog.set_level(logging.DEBUG, logger="xdqc")
    extract_distributed_circuit(partitioner, verbosity="debug")

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name.startswith("xdqc")
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


def test_extract_distributed_circuit_raises_on_statement_undercount(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The statement-accounting invariant must raise a clear error (not a bare
    # ``assert``, which would be stripped under ``python -O``) when the
    # assembled program has fewer statements than the computed lower bound.
    import xdqc.circuit.circuit as circuit_module

    original = circuit_module.build_distributed_statements

    def _truncated(*args: Any, **kwargs: Any):
        statements, swaps_added = original(*args, **kwargs)
        return statements[:1], swaps_added

    program = load_qasm_program(str(simple1_circuit_path))
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network, program, algo_kwargs={"window_length": 2}
    )
    partitioner.run()
    monkeypatch.setattr(
        circuit_module, "build_distributed_statements", _truncated
    )

    with pytest.raises(RuntimeError, match="statement-accounting"):
        extract_distributed_circuit(partitioner, group_gates=False)
