# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Tests for the high-level Compiler entry point."""

from typing import Any

import networkx as nx
import pytest
from openqasm3 import ast

from xdqc import (
    Compiler,
    Scheduler,
    SchedulingCompileOptions,
    VerificationArtifacts,
    get_verification_artifacts,
)
from xdqc.circuit import DistributedCircuit
from xdqc.network import NetworkGraph
from xdqc.partition import Partitioner


def test_compiler_compiles_and_exposes_distributed_circuit(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    compiler = Compiler(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        algo_kwargs={"window_length": 2},
    )
    compiler.compile()

    assert isinstance(compiler.network, NetworkGraph)
    assert isinstance(compiler.partitioner, Partitioner)
    assert isinstance(compiler.distributed_circuit, DistributedCircuit)
    assert "OPENQASM" in compiler.distributed_qasm


def test_compiler_accepts_inline_qasm_source(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    qasm_source = simple1_circuit_path.read_text(encoding="utf-8")
    compiler = Compiler(
        qasm_source,
        three_comp_one_comm_x2_network_path,
        algo_kwargs={"window_length": 2},
    )
    compiler.compile()

    assert isinstance(compiler.distributed_circuit, DistributedCircuit)


def test_compiler_exposes_verification_artifacts(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    compiler = Compiler(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        algo_kwargs={"window_length": 2},
    )
    compiler.compile(ebit_assignment=True, group_gates=False)

    artifacts = compiler.get_verification_artifacts()

    assert isinstance(artifacts, VerificationArtifacts)
    assert isinstance(artifacts.original_program, ast.Program)
    assert isinstance(artifacts.distributed_program, ast.Program)
    assert "OPENQASM" in artifacts.original_qasm
    assert "OPENQASM" in artifacts.distributed_qasm
    assert nx.is_directed_acyclic_graph(artifacts.original_dag)
    assert nx.is_directed_acyclic_graph(artifacts.distributed_dag)
    assert artifacts.original_dag is not compiler.circuit.mono.dag.graph


def test_get_verification_artifacts_compiles_both_representations(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    artifacts = get_verification_artifacts(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        options=SchedulingCompileOptions(
            partitioner_kwargs={"window_length": 2},
        ),
    )

    assert isinstance(artifacts, VerificationArtifacts)
    assert set(artifacts.original_dag) == {
        data["op"].op_id for data in artifacts.original_dag.nodes.values()
    }
    assert set(artifacts.distributed_dag) == {
        data["op"].op_id for data in artifacts.distributed_dag.nodes.values()
    }


def test_compiler_save_distributed_circuit(
    tmp_path,
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    compiler = Compiler(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        algo_kwargs={"window_length": 2},
    )
    compiler.compile()

    out_path = tmp_path / "dist.qasm"
    returned = compiler.save_distributed_circuit(out_path)

    assert returned == out_path
    assert out_path.read_text() == compiler.distributed_qasm


def test_compiler_verify_forwards_to_partitioner(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import xdqc.verify as verify_pkg

    compiler = Compiler(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        algo_kwargs={"window_length": 2},
    )
    compiler.compile()

    captured: dict[str, Any] = {}

    def fake_verify(
        original: Any,
        distributed: Any,
        *,
        shots: int,
        fidelity_threshold: float,
        verbosity: str,
    ) -> bool:
        captured.update(shots=shots, verbosity=verbosity)
        return True

    monkeypatch.setattr(verify_pkg, "verify_distributed_circuit", fake_verify)

    assert compiler.verify(shots=77, verbosity="info") is True
    assert captured == {"shots": 77, "verbosity": "info"}


def test_scheduler_accepts_compiler(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    compiler = Compiler(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        algo_kwargs={"window_length": 2},
    )
    compiler.compile()

    scheduler = Scheduler(compiler, algo="fifo")
    scheduler.run()

    assert scheduler.schedule is not None


def test_scheduler_rejects_unsupported_source() -> None:
    with pytest.raises(
        TypeError, match="Compiler, Partitioner, or DistributedCircuit"
    ):
        Scheduler("not a circuit")
