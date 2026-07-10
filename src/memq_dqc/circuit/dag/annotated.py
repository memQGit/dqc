# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Annotated distributed-DAG export.

Opt-in helpers that produce a standalone, richly annotated
:class:`networkx.DiGraph` view of a compiled distributed circuit, plus a JSON
serializer for it. These never run automatically as part of compilation; call
:func:`build_annotated_dag` (or :meth:`Compiler.annotated_dag`) and
:func:`annotated_dag_to_json` (or :meth:`Compiler.to_dag_json`) explicitly when
an exportable graph representation is needed.

The annotated graph is derived *read-only* from the existing
:class:`~memq_dqc.circuit.dag.distributed.DistributedCircuitDAG`; it copies the
dependency structure into a new graph and bakes on the execution detail that is
otherwise hidden behind object layers: operation classification, logical
qubits, physical qubits (QPU + slot), communication qubits, EPR-pair
assignments, and cat-entanglement group membership. Every node and edge also
carries a reserved ``hardware`` mapping, the intended attachment point for
future hardware attributes (coherence times, link fidelities).

The JSON document has these top-level keys:

* ``type``: the ``"distributed_dag"`` discriminator.
* ``schema_version``: an integer for forward-compatibility.
* ``num_nodes`` / ``num_edges``: convenience counts.
* ``nodes``: operation nodes, sorted by ``op_id``.
* ``edges``: dependency edges, sorted by ``(source, target)``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import TYPE_CHECKING, Any

import networkx as nx

from memq_dqc.circuit.dag.distributed import _REMOTE_GATE_NAMES
from memq_dqc.network import PhysicalQubit

if TYPE_CHECKING:
    from os import PathLike

    from memq_dqc.circuit.circuit import DistributedCircuit
    from memq_dqc.circuit.op import Op
    from memq_dqc.preprocessing.qasm.types import CircuitQubit

_SCHEMA_VERSION = 1
_GRAPH_TYPE = "distributed_dag"
_REMOTE_DATA_GATE_NAMES = _REMOTE_GATE_NAMES - {"rswap"}


def build_annotated_dag(distributed: DistributedCircuit) -> nx.DiGraph:
    """Build an annotated distributed-DAG graph for a compiled circuit.

    Constructs a brand-new :class:`networkx.DiGraph` that mirrors the
    dependency structure of ``distributed.dag`` and annotates each node and
    edge with execution detail. The source circuit and its DAG are only read;
    nothing is mutated.

    Args:
        distributed: The compiled distributed circuit to derive the graph from.

    Returns:
        A directed acyclic graph whose nodes are keyed by ``op_id`` and whose
        node/edge attributes carry the annotated execution detail.
    """
    group_by_op_id = _assign_group_ids(distributed.ops)
    ebit_candidates_by_op_id = distributed.ebit_candidates_by_op_id or {}
    source_graph = distributed.dag.graph

    graph = nx.DiGraph()
    graph.graph["type"] = _GRAPH_TYPE
    graph.graph["schema_version"] = _SCHEMA_VERSION

    for node_id in source_graph.nodes:
        op = source_graph.nodes[node_id]["op"]
        data_qubits, comm_qubits = _op_split_qubits(op)
        graph.add_node(
            op.op_id,
            op=op,
            op_id=op.op_id,
            op_type=_op_type(op),
            name=op.name,
            statement_id=op.statement_id,
            is_remote=op.is_remote,
            is_two_qubit=len(data_qubits) == 2,
            group_id=group_by_op_id.get(op.op_id),
            logical_qubits=data_qubits,
            physical_qubits=tuple(_physical_qubit(q) for q in data_qubits),
            comm_qubits=tuple(_physical_qubit(q) for q in comm_qubits),
            ebit_pairs=_ebit_pairs(comm_qubits),
            ebit_candidates=ebit_candidates_by_op_id.get(op.op_id),
            hardware={},
        )

    for source_id, target_id, edge_data in source_graph.edges(data=True):
        source_op = source_graph.nodes[source_id]["op"]
        target_op = source_graph.nodes[target_id]["op"]
        shared_qubits = tuple(
            sorted(
                edge_data["qubits"],
                key=lambda qubit: (qubit.register_name, qubit.index),
            )
        )
        graph.add_edge(
            source_id,
            target_id,
            qubits=shared_qubits,
            is_cross_qpu=_is_cross_qpu(source_op, target_op),
            hardware={},
        )

    return graph


def annotated_dag_to_json(
    graph: nx.DiGraph,
    path: str | PathLike[str] | None = None,
    *,
    indent: int | None = 2,
) -> str:
    """Serialize an annotated distributed-DAG graph to a JSON document.

    This is an opt-in helper; building the graph never serializes
    automatically. The document mirrors the node and edge attributes baked on
    by :func:`build_annotated_dag`; the raw operation object and its AST node
    are intentionally omitted.

    Args:
        graph: An annotated graph produced by :func:`build_annotated_dag`.
        path: Optional destination file. When given, the JSON document is
            written there as UTF-8 text in addition to being returned.
        indent: Indentation forwarded to :func:`json.dumps`. Pass ``None`` for
            the most compact single-line output.

    Returns:
        The JSON document as a string.
    """
    document = json.dumps(_graph_to_dict(graph), indent=indent)
    if path is not None:
        Path(path).write_text(document, encoding="utf-8")
    return document


def _op_type(op: Op) -> str:
    """Return the node type discriminator for an operation.

    Args:
        op: The distributed operation to classify.

    Returns:
        One of ``"remote_gate"``, ``"remote_swap"``, ``"epr_generation"``,
        ``"disentangle"``, ``"local_swap"``, ``"measurement"``, or
        ``"local_gate"``.
    """
    name = op.name
    if name in _REMOTE_DATA_GATE_NAMES:
        return "remote_gate"
    if name == "rswap":
        return "remote_swap"
    if name == "catent":
        return "epr_generation"
    if name == "catdisent":
        return "disentangle"
    if name == "swap":
        return "local_swap"
    if name == "measure":
        return "measurement"
    return "local_gate"


def _assign_group_ids(ops: list[Op]) -> dict[int, int | None]:
    """Assign a cat-entanglement group id to each operation.

    Groups are recovered structurally from the emitted operation order: a
    ``catent`` opens a group that its remote data gates and the closing
    ``catdisent`` share, and each ``rswap`` forms its own singleton group.
    Operations outside any cat-entanglement region receive ``None``.

    Args:
        ops: Distributed operations in emitted order.

    Returns:
        A mapping from ``op_id`` to its group id, or ``None`` when the
        operation belongs to no group.
    """
    group_by_op_id: dict[int, int | None] = {}
    next_group_id = 0
    current_group: int | None = None
    for op in ops:
        if op.name == "catent":
            current_group = next_group_id
            next_group_id += 1
            group_by_op_id[op.op_id] = current_group
        elif op.name == "catdisent":
            group_by_op_id[op.op_id] = current_group
            current_group = None
        elif op.name == "rswap":
            group_by_op_id[op.op_id] = next_group_id
            next_group_id += 1
        elif op.is_remote:
            group_by_op_id[op.op_id] = current_group
        else:
            group_by_op_id[op.op_id] = None
    return group_by_op_id


def _op_split_qubits(
    op: Op,
) -> tuple[tuple[CircuitQubit, ...], tuple[CircuitQubit, ...]]:
    """Split an operation's operands into data and communication qubits.

    Computation operands use ``q<qpu>`` registers; communication operands use
    ``c<qpu>`` registers. The split is by register prefix, which is robust
    across gate kinds and both e-bit assignment modes.

    Args:
        op: The distributed operation whose operands to split.

    Returns:
        A ``(data_qubits, comm_qubits)`` pair, each preserving operand order.
    """
    data_qubits = tuple(
        qubit
        for qubit in op.qubits
        if _split_register(qubit.register_name)[0] == "q"
    )
    comm_qubits = tuple(
        qubit
        for qubit in op.qubits
        if _split_register(qubit.register_name)[0] == "c"
    )
    return data_qubits, comm_qubits


def _ebit_pairs(
    comm_qubits: tuple[CircuitQubit, ...],
) -> tuple[tuple[PhysicalQubit, PhysicalQubit], ...] | None:
    """Return concrete e-bit pairs from consecutive communication operands.

    Args:
        comm_qubits: The communication operands of an EPR-backed operation.

    Returns:
        A tuple of physical communication-qubit pairs, or ``None`` when there
        are no communication operands (e.g. deferred e-bit assignment) or an
        unexpected odd count.
    """
    if not comm_qubits or len(comm_qubits) % 2 != 0:
        return None
    physical = [_physical_qubit(qubit) for qubit in comm_qubits]
    return tuple(
        (physical[index], physical[index + 1])
        for index in range(0, len(physical), 2)
    )


def _is_cross_qpu(source_op: Op, target_op: Op) -> bool:
    """Return whether a dependency straddles more than one QPU.

    Args:
        source_op: The operation at the dependency's source.
        target_op: The operation at the dependency's target.

    Returns:
        True when the union of QPU ids over both operations' operands spans
        more than one QPU.
    """
    qpu_ids = _op_qpu_ids(source_op) | _op_qpu_ids(target_op)
    return len(qpu_ids) > 1


def _op_qpu_ids(op: Op) -> set[int]:
    """Return the set of QPU ids referenced by an operation's operands."""
    return {_split_register(qubit.register_name)[1] for qubit in op.qubits}


def _physical_qubit(qubit: CircuitQubit) -> PhysicalQubit:
    """Convert a distributed circuit qubit into a physical qubit.

    Args:
        qubit: A circuit qubit whose register encodes its QPU and kind.

    Returns:
        The corresponding physical qubit, typed as computation or
        communication by its register prefix.
    """
    prefix, qpu_id = _split_register(qubit.register_name)
    qubit_type = "communication" if prefix == "c" else "computation"
    return PhysicalQubit(
        qpu_id=qpu_id,
        qubit_id=qubit.index,
        qubit_type=qubit_type,
    )


def _split_register(register_name: str) -> tuple[str, int]:
    """Parse a distributed register name into its prefix and QPU id.

    Args:
        register_name: A register identifier such as ``q0`` or ``c2``.

    Returns:
        A ``(prefix, qpu_id)`` pair, where ``prefix`` is ``"q"`` (computation)
        or ``"c"`` (communication).

    Raises:
        ValueError: If the register name is empty or malformed.
    """
    if not register_name:
        raise ValueError("Register name must be non-empty.")
    prefix = register_name[0]
    if prefix not in ("q", "c"):
        raise ValueError(
            f"Register name must start with 'q' or 'c': {register_name!r}."
        )
    suffix = register_name[1:]
    if not suffix.isdigit():
        raise ValueError(
            f"Register name must be '<prefix><int>': {register_name!r}."
        )
    return prefix, int(suffix)


def _graph_to_dict(graph: nx.DiGraph) -> dict[str, Any]:
    """Return a JSON-serializable mapping for an annotated graph.

    Args:
        graph: An annotated graph produced by :func:`build_annotated_dag`.

    Returns:
        A mapping with ``type``, ``schema_version``, ``num_nodes``,
        ``num_edges``, ``nodes``, and ``edges`` keys.
    """
    nodes = [
        _node_to_dict(graph.nodes[node_id]) for node_id in sorted(graph.nodes)
    ]
    edges = [
        _edge_to_dict(source_id, target_id, graph.edges[source_id, target_id])
        for source_id, target_id in sorted(graph.edges)
    ]
    return {
        "type": graph.graph.get("type", _GRAPH_TYPE),
        "schema_version": graph.graph.get("schema_version", _SCHEMA_VERSION),
        "num_nodes": graph.number_of_nodes(),
        "num_edges": graph.number_of_edges(),
        "nodes": nodes,
        "edges": edges,
    }


def _node_to_dict(data: dict[str, Any]) -> dict[str, Any]:
    """Return a JSON-serializable mapping for one annotated node.

    Args:
        data: The node attribute mapping baked on by
            :func:`build_annotated_dag`.

    Returns:
        A mapping of the node's serializable fields. The raw operation object
        and its AST node are omitted.
    """
    ebit_pairs = data["ebit_pairs"]
    ebit_candidates = data["ebit_candidates"]
    return {
        "op_id": data["op_id"],
        "op_type": data["op_type"],
        "name": data["name"],
        "statement_id": data["statement_id"],
        "is_remote": data["is_remote"],
        "is_two_qubit": data["is_two_qubit"],
        "group_id": data["group_id"],
        "logical_qubits": [
            _circuit_qubit_to_dict(qubit) for qubit in data["logical_qubits"]
        ],
        "physical_qubits": [
            _physical_qubit_to_dict(qubit) for qubit in data["physical_qubits"]
        ],
        "comm_qubits": [
            _physical_qubit_to_dict(qubit) for qubit in data["comm_qubits"]
        ],
        "ebit_pairs": (
            None
            if ebit_pairs is None
            else [
                [
                    _physical_qubit_to_dict(first),
                    _physical_qubit_to_dict(second),
                ]
                for first, second in ebit_pairs
            ]
        ),
        "ebit_candidates": (
            None
            if ebit_candidates is None
            else [
                [
                    [
                        _physical_qubit_to_dict(first),
                        _physical_qubit_to_dict(second),
                    ]
                    for first, second in assignment
                ]
                for assignment in ebit_candidates
            ]
        ),
        "hardware": data["hardware"],
    }


def _edge_to_dict(
    source_id: int,
    target_id: int,
    data: dict[str, Any],
) -> dict[str, Any]:
    """Return a JSON-serializable mapping for one annotated edge.

    Args:
        source_id: The ``op_id`` at the edge's source.
        target_id: The ``op_id`` at the edge's target.
        data: The edge attribute mapping baked on by
            :func:`build_annotated_dag`.

    Returns:
        A mapping of the edge's serializable fields.
    """
    return {
        "source": source_id,
        "target": target_id,
        "qubits": [_circuit_qubit_to_dict(qubit) for qubit in data["qubits"]],
        "is_cross_qpu": data["is_cross_qpu"],
        "hardware": data["hardware"],
    }


def _circuit_qubit_to_dict(qubit: CircuitQubit) -> dict[str, Any]:
    """Return a JSON-serializable mapping for a logical circuit qubit."""
    return {
        "register": qubit.register_name,
        "index": qubit.index,
        "label": f"{qubit.register_name}[{qubit.index}]",
    }


def _physical_qubit_to_dict(qubit: PhysicalQubit) -> dict[str, Any]:
    """Return a JSON-serializable mapping for a physical qubit."""
    return {
        "qpu_id": qubit.qpu_id,
        "qubit_id": qubit.qubit_id,
        "qubit_type": qubit.qubit_type,
        "label": qubit.label,
    }
