# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Tests for the annotated distributed-DAG export."""

import json
from types import SimpleNamespace

import networkx as nx
import pytest
from openqasm3 import ast

from xdqc import Partitioner
from xdqc.circuit.dag import (
    DistributedCircuitDAG,
    annotated_dag_to_json,
    build_annotated_dag,
)
from xdqc.circuit.dag.annotated import (
    _assign_group_ids,
    _circuit_qubit_to_dict,
    _op_type,
    _physical_qubit_to_dict,
    _split_register,
)
from xdqc.circuit.op import Op
from xdqc.network import PhysicalQubit
from xdqc.preprocessing.qasm.types import CircuitQubit


def _q(register_name: str, index: int) -> CircuitQubit:
    return CircuitQubit(register_name=register_name, index=index)


def _op(op_id, name, qubits, *, is_remote=False, statement_id=0) -> Op:
    return Op(
        op_id=op_id,
        statement_id=statement_id,
        name=name,
        is_remote=is_remote,
        qubits=tuple(qubits),
        node=ast.QuantumGate(
            modifiers=[],
            name=ast.Identifier(name),
            arguments=[],
            qubits=[],
        ),
    )


def _distributed(ops, ebit_candidates=None) -> SimpleNamespace:
    return SimpleNamespace(
        ops=ops,
        dag=DistributedCircuitDAG(ops),
        ebit_candidates_by_op_id=ebit_candidates,
    )


def _assigned_ops() -> list[Op]:
    comm = (_q("c0", 0), _q("c1", 0))
    data = (_q("q0", 0), _q("q1", 0))
    return [
        _op(0, "catent", (*data, *comm), statement_id=0),
        _op(1, "rcx", (*data, *comm), is_remote=True, statement_id=1),
        _op(2, "catdisent", (*data, *comm), statement_id=2),
        _op(3, "h", (_q("q0", 0),), statement_id=3),
        _op(4, "x", (_q("q0", 0),), statement_id=4),
        _op(5, "measure", (_q("q1", 0),), statement_id=5),
    ]


# ---------------------------------------------------------------------------
# Tier A: pure helpers + serializer on hand-built inputs
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("name", "expected"),
    [
        ("rcx", "remote_gate"),
        ("rcp", "remote_gate"),
        ("rcry", "remote_gate"),
        ("rcz", "remote_gate"),
        ("rswap", "remote_swap"),
        ("catent", "epr_generation"),
        ("catdisent", "disentangle"),
        ("swap", "local_swap"),
        ("measure", "measurement"),
        ("h", "local_gate"),
        ("cx", "local_gate"),
    ],
)
def test_op_type_classification(name, expected) -> None:
    op = _op(0, name, (_q("q0", 0),), is_remote=name.startswith("r"))
    assert _op_type(op) == expected


def test_assign_group_ids() -> None:
    ops = [
        _op(0, "catent", (_q("q0", 0),)),
        _op(1, "rcx", (_q("q0", 0),), is_remote=True),
        _op(2, "rcx", (_q("q0", 0),), is_remote=True),
        _op(3, "catdisent", (_q("q0", 0),)),
        _op(4, "cx", (_q("q0", 0),)),
        _op(5, "rswap", (_q("q0", 0),), is_remote=True),
    ]
    assert _assign_group_ids(ops) == {0: 0, 1: 0, 2: 0, 3: 0, 4: None, 5: None}


def test_circuit_qubit_to_dict() -> None:
    assert _circuit_qubit_to_dict(_q("q0", 2)) == {
        "register": "q0",
        "index": 2,
        "label": "q0[2]",
    }


def test_physical_qubit_to_dict() -> None:
    qubit = PhysicalQubit(qpu_id=1, qubit_id=3, qubit_type="communication")
    assert _physical_qubit_to_dict(qubit) == {
        "qpu_id": 1,
        "qubit_id": 3,
        "qubit_type": "communication",
        "label": "c_1_3",
    }


@pytest.mark.parametrize(
    ("register", "expected"),
    [("q0", ("q", 0)), ("c2", ("c", 2)), ("q10", ("q", 10))],
)
def test_split_register(register, expected) -> None:
    assert _split_register(register) == expected


@pytest.mark.parametrize("register", ["", "x0", "q", "qa"])
def test_split_register_rejects_malformed(register) -> None:
    with pytest.raises(ValueError):
        _split_register(register)


def test_top_level_shape() -> None:
    graph = build_annotated_dag(_distributed(_assigned_ops()))
    document = json.loads(annotated_dag_to_json(graph))
    assert set(document) == {
        "type",
        "schema_version",
        "num_nodes",
        "num_edges",
        "nodes",
        "edges",
    }
    assert document["type"] == "distributed_dag"
    assert document["schema_version"] == 1
    assert document["num_nodes"] == 6
    assert document["num_edges"] == 5


def test_node_ordering_and_epr_node() -> None:
    graph = build_annotated_dag(_distributed(_assigned_ops()))
    document = json.loads(annotated_dag_to_json(graph))
    assert [node["op_id"] for node in document["nodes"]] == [0, 1, 2, 3, 4, 5]
    assert document["nodes"][0] == {
        "op_id": 0,
        "op_type": "epr_generation",
        "name": "catent",
        "statement_id": 0,
        "is_remote": False,
        "is_two_qubit": True,
        "group_id": 0,
        "logical_qubits": [
            {"register": "q0", "index": 0, "label": "q0[0]"},
            {"register": "q1", "index": 0, "label": "q1[0]"},
        ],
        "physical_qubits": [
            {
                "qpu_id": 0,
                "qubit_id": 0,
                "qubit_type": "computation",
                "label": "q_0_0",
            },
            {
                "qpu_id": 1,
                "qubit_id": 0,
                "qubit_type": "computation",
                "label": "q_1_0",
            },
        ],
        "comm_qubits": [
            {
                "qpu_id": 0,
                "qubit_id": 0,
                "qubit_type": "communication",
                "label": "c_0_0",
            },
            {
                "qpu_id": 1,
                "qubit_id": 0,
                "qubit_type": "communication",
                "label": "c_1_0",
            },
        ],
        "ebit_pairs": [
            [
                {
                    "qpu_id": 0,
                    "qubit_id": 0,
                    "qubit_type": "communication",
                    "label": "c_0_0",
                },
                {
                    "qpu_id": 1,
                    "qubit_id": 0,
                    "qubit_type": "communication",
                    "label": "c_1_0",
                },
            ]
        ],
        "ebit_candidates": None,
        "hardware": {},
    }


def test_remote_local_and_measurement_nodes() -> None:
    graph = build_annotated_dag(_distributed(_assigned_ops()))
    document = json.loads(annotated_dag_to_json(graph))
    nodes = {node["op_id"]: node for node in document["nodes"]}

    remote = nodes[1]
    assert remote["op_type"] == "remote_gate"
    assert remote["is_remote"] is True
    assert remote["is_two_qubit"] is True
    assert remote["group_id"] == 0
    assert remote["ebit_pairs"] is not None
    assert remote["ebit_candidates"] is None
    assert len(remote["comm_qubits"]) == 2

    local = nodes[3]
    assert local["op_type"] == "local_gate"
    assert local["comm_qubits"] == []
    assert local["ebit_pairs"] is None
    assert local["group_id"] is None
    assert local["is_two_qubit"] is False

    measurement = nodes[5]
    assert measurement["op_type"] == "measurement"
    assert measurement["logical_qubits"] == [
        {"register": "q1", "index": 0, "label": "q1[0]"}
    ]
    assert measurement["comm_qubits"] == []


def test_edge_ordering_and_cross_qpu() -> None:
    graph = build_annotated_dag(_distributed(_assigned_ops()))
    document = json.loads(annotated_dag_to_json(graph))
    edge_keys = [
        (edge["source"], edge["target"]) for edge in document["edges"]
    ]
    assert edge_keys == [(0, 1), (1, 2), (2, 3), (2, 5), (3, 4)]

    edges = {
        (edge["source"], edge["target"]): edge for edge in document["edges"]
    }
    # Both operands on QPU 0 -> not cross-QPU.
    assert edges[(3, 4)] == {
        "source": 3,
        "target": 4,
        "qubits": [{"register": "q0", "index": 0, "label": "q0[0]"}],
        "is_cross_qpu": False,
        "hardware": {},
    }
    # Endpoints span QPU 0 and 1 -> cross-QPU.
    assert edges[(2, 5)]["is_cross_qpu"] is True


def test_deferred_ebit_node() -> None:
    ops = [
        _op(0, "catent", (_q("q0", 0), _q("q1", 0))),
        _op(1, "rcx", (_q("q0", 0), _q("q1", 0)), is_remote=True),
        _op(2, "catdisent", (_q("q0", 0), _q("q1", 0))),
    ]
    pair = (
        PhysicalQubit(qpu_id=0, qubit_id=0, qubit_type="communication"),
        PhysicalQubit(qpu_id=1, qubit_id=0, qubit_type="communication"),
    )
    candidates = {1: ((pair,),)}
    graph = build_annotated_dag(_distributed(ops, ebit_candidates=candidates))
    document = json.loads(annotated_dag_to_json(graph))
    remote = next(n for n in document["nodes"] if n["op_id"] == 1)
    assert remote["ebit_pairs"] is None
    assert remote["comm_qubits"] == []
    assert remote["ebit_candidates"] == [
        [
            [
                {
                    "qpu_id": 0,
                    "qubit_id": 0,
                    "qubit_type": "communication",
                    "label": "c_0_0",
                },
                {
                    "qpu_id": 1,
                    "qubit_id": 0,
                    "qubit_type": "communication",
                    "label": "c_1_0",
                },
            ]
        ]
    ]


def test_file_round_trip(tmp_path) -> None:
    graph = build_annotated_dag(_distributed(_assigned_ops()))
    out_path = tmp_path / "dag.json"
    document = annotated_dag_to_json(graph, out_path)
    assert out_path.is_file()
    assert json.loads(out_path.read_text(encoding="utf-8")) == json.loads(
        document
    )


def test_compact_output() -> None:
    graph = build_annotated_dag(_distributed(_assigned_ops()))
    document = annotated_dag_to_json(graph, indent=None)
    assert "\n" not in document
    assert json.loads(document)["num_nodes"] == 6


# ---------------------------------------------------------------------------
# Tier B: end-to-end from a compiled distributed circuit
# ---------------------------------------------------------------------------


def _ran(circuit_path, network_path, *, ebit_assignment=None) -> Partitioner:
    partitioner = Partitioner(
        network_path, circuit_path, algo_kwargs={"window_length": 2}
    )
    partitioner.run(ebit_assignment=ebit_assignment)
    return partitioner


def test_end_to_end_structure_fidelity(
    simple1_circuit_path, three_comp_one_comm_x2_network_path
) -> None:
    partitioner = _ran(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    graph = partitioner.annotated_dag()
    distributed = partitioner.distributed_circuit

    assert set(graph.nodes) == {op.op_id for op in distributed.ops}
    assert set(graph.edges) == set(distributed.dag.graph.edges())


def test_end_to_end_remote_node_has_ebits(
    simple1_circuit_path, three_comp_one_comm_x2_network_path
) -> None:
    partitioner = _ran(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    document = json.loads(partitioner.to_dag_json())
    remote_nodes = [
        node for node in document["nodes"] if node["op_type"] == "remote_gate"
    ]
    assert remote_nodes
    assert any(node["comm_qubits"] for node in remote_nodes)
    assert any(node["ebit_pairs"] for node in remote_nodes)
    assert document["num_nodes"] == len(partitioner.distributed_circuit.ops)


def test_end_to_end_determinism(
    simple1_circuit_path, three_comp_one_comm_x2_network_path
) -> None:
    partitioner = _ran(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    assert partitioner.to_dag_json() == partitioner.to_dag_json()


def test_end_to_end_file_write(
    tmp_path, simple1_circuit_path, three_comp_one_comm_x2_network_path
) -> None:
    partitioner = _ran(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    out_path = tmp_path / "dag.json"
    document = partitioner.to_dag_json(out_path)
    assert out_path.read_text(encoding="utf-8") == document


def test_end_to_end_deferred_mode(
    simple1_circuit_path, three_comp_one_comm_x2_network_path
) -> None:
    partitioner = _ran(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        ebit_assignment=False,
    )
    document = json.loads(partitioner.to_dag_json())
    remote_nodes = [
        node for node in document["nodes"] if node["op_type"] == "remote_gate"
    ]
    assert remote_nodes
    assert all(node["ebit_pairs"] is None for node in remote_nodes)
    assert all(node["comm_qubits"] == [] for node in remote_nodes)
    assert any(node["ebit_candidates"] for node in remote_nodes)


def test_end_to_end_local_only(
    bell_circuit_path, three_comp_one_comm_x2_network_path
) -> None:
    partitioner = _ran(bell_circuit_path, three_comp_one_comm_x2_network_path)
    document = json.loads(partitioner.to_dag_json())
    assert all(
        node["op_type"] in {"local_gate", "measurement"}
        for node in document["nodes"]
    )
    assert all(node["group_id"] is None for node in document["nodes"])
    assert all(not edge["is_cross_qpu"] for edge in document["edges"])


def test_compiler_forwarding_matches_partitioner(
    simple1_circuit_path, three_comp_one_comm_x2_network_path
) -> None:
    from xdqc import Compiler

    compiler = Compiler(
        simple1_circuit_path,
        three_comp_one_comm_x2_network_path,
        algo_kwargs={"window_length": 2},
    )
    compiler.compile()
    assert isinstance(compiler.annotated_dag(), nx.DiGraph)
    assert compiler.to_dag_json() == compiler.partitioner.to_dag_json()


def test_annotated_dag_does_not_change_qasm(
    simple1_circuit_path, three_comp_one_comm_x2_network_path
) -> None:
    partitioner = _ran(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    before = partitioner.distributed_qasm
    partitioner.annotated_dag()
    partitioner.to_dag_json()
    assert partitioner.distributed_qasm == before
