# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pytest
from openqasm3 import ast

from memq_dqc.circuit.ops import Op
from memq_dqc.partition.types import QPU
from memq_dqc.qasm.types import LogicalQubit
from memq_dqc.visualization.partition_visualizer import (
    plot_migration_timeline,
    plot_partition_heatmap,
    plot_qubit_flow,
    plot_window_operation_profile,
)


def _sample_partition() -> list[dict[QPU, set[int]]]:
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    return [
        {qpu0: {0, 1}, qpu1: {2, 3}},
        {qpu0: {0, 2}, qpu1: {1, 3}},
        {qpu0: {0, 2}, qpu1: {1, 3}},
        {qpu0: {0, 1}, qpu1: {2, 3}},
    ]


def test_partition_heatmap_top_k() -> None:
    partition = _sample_partition()
    _, ax = plt.subplots()

    ax = plot_partition_heatmap(
        partition,
        top_k_most_moved=2,
        ax=ax,
        show=False,
    )

    assert ax.images
    array = ax.images[0].get_array()
    assert array.shape == (2, len(partition))


def test_migration_timeline_entanglement_length_mismatch() -> None:
    partition = _sample_partition()
    _, ax = plt.subplots()

    with pytest.raises(ValueError, match="window_entanglement_cost"):
        plot_migration_timeline(
            partition,
            window_entanglement_cost=[1.0],
            ax=ax,
            show=False,
        )


def test_qubit_flow_invalid_qubit_selection() -> None:
    partition = _sample_partition()
    _, ax = plt.subplots()

    with pytest.raises(ValueError, match="No valid qubits"):
        plot_qubit_flow(partition, qubits=[100, 101], ax=ax, show=False)


def _op(op_id: int, qubits: tuple[int, ...]) -> Op:
    logical_qubits = tuple(LogicalQubit("q", idx) for idx in qubits)
    return Op(
        op_id=op_id,
        statement_id=op_id,
        name="cx" if len(qubits) == 2 else "x",
        qubits=logical_qubits,
        node=ast.Identifier(name=f"n{op_id}"),
    )


def test_window_operation_profile_stack() -> None:
    partition = _sample_partition()
    windows = [
        [_op(0, (0,)), _op(1, (0, 1)), _op(2, (1, 2))],
        [_op(3, (2,)), _op(4, (0, 2))],
        [_op(5, (1, 3)), _op(6, (2, 3))],
        [_op(7, (3,))],
    ]

    _, ax = plt.subplots()
    ax = plot_window_operation_profile(
        partition,
        windows,
        ax=ax,
        show=False,
    )

    assert ax.patches
    assert len(ax.patches) == len(partition) * 3


def test_window_operation_profile_length_mismatch() -> None:
    partition = _sample_partition()
    windows = [[_op(0, (0,))]]
    _, ax = plt.subplots()

    with pytest.raises(ValueError, match="matching lengths"):
        plot_window_operation_profile(partition, windows, ax=ax, show=False)
