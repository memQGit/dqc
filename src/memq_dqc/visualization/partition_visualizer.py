# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Partition and schedule visualization helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import numpy as np

if TYPE_CHECKING:
    from collections.abc import Sequence

    from memq_dqc.circuit.ops import Op
    from memq_dqc.partition.types import QPU

PartitionTimeline = list[dict["QPU", set[int]]]
PartitionWindows = list[list["Op"]]

__all__ = [
    "plot_partition_heatmap",
    "plot_migration_timeline",
    "plot_qubit_flow",
    "plot_window_operation_profile",
]

COLOR_SCHEME = ["#a558b5", "#222636", "#3b4171", "#3f5f81"]


def plot_partition_heatmap(  # pragma: no cover
    partition: PartitionTimeline,
    *,
    top_k_most_moved: int | None = None,
    sample_stride: int | None = None,
    sort_by_final_qpu: bool = False,
    x_tick_stride: int | None = 5,
    x_tick_rotation: float = 30.0,
    y_tick_fontsize: int = 8,
    ax: plt.Axes | None = None,
    cmap: str = "tab20",
    show: bool = True,
) -> plt.Axes:
    """Plot a qubit-vs-window heatmap of QPU assignments.

    Rows correspond to qubits, columns correspond to windows, and the color
    represents the QPU index for each qubit in each window.

    Args:
        partition: Timeline of partitions (window -> QPU -> qubit set).
        top_k_most_moved: If provided, keep only the qubits that moved most
            often across windows.
        sample_stride: If provided, keep every Nth qubit after filtering.
        sort_by_final_qpu: Whether to group rows by the final window QPU.
        x_tick_stride: Window tick spacing. If None, show every window.
        x_tick_rotation: Rotation angle for x-axis tick labels.
        y_tick_fontsize: Font size for y-axis tick labels.
        ax: Optional matplotlib axes to draw on.
        cmap: Matplotlib colormap to use.
        show: Whether to call matplotlib's show() at the end.

    Returns:
        The matplotlib axes containing the heatmap.
    """
    assignments, num_qpus = _assignments_and_qpu_count(partition)
    qubits = _collect_qubits(assignments)

    qubit_order = _order_qubits(
        qubits,
        assignments,
        top_k_most_moved=top_k_most_moved,
        sample_stride=sample_stride,
        sort_by_final_qpu=sort_by_final_qpu,
    )

    data = np.full((len(qubit_order), len(assignments)), np.nan)
    for col_idx, window_assignment in enumerate(assignments):
        for row_idx, qubit in enumerate(qubit_order):
            if qubit in window_assignment:
                data[row_idx, col_idx] = window_assignment[qubit]

    if ax is None:
        _, ax = plt.subplots(figsize=(10, 6))

    # Create custom colormap using COLOR_SCHEME first, then fallback
    if num_qpus <= len(COLOR_SCHEME):
        # Use only COLOR_SCHEME colors
        colors = COLOR_SCHEME[:num_qpus]
    else:
        # Use all COLOR_SCHEME colors, then fill with default colormap
        fallback_cmap = plt.get_cmap(cmap, num_qpus - len(COLOR_SCHEME))
        fallback_colors = [
            fallback_cmap(i) for i in range(num_qpus - len(COLOR_SCHEME))
        ]
        colors = COLOR_SCHEME + [mcolors.to_hex(c) for c in fallback_colors]

    cmap_obj = mcolors.ListedColormap(colors, N=num_qpus)
    cmap_obj.set_bad(color="#e0e0e0")
    img = ax.imshow(
        data,
        aspect="auto",
        interpolation="nearest",
        cmap=cmap_obj,
    )
    ax.set_xlabel("Window")
    ax.set_ylabel("Qubit")
    ax.set_title("Qubit Assignments Over Windows")

    tick_stride = max(1, len(qubit_order) // 50)
    ax.set_yticks(list(range(0, len(qubit_order), tick_stride)))
    ax.set_yticklabels(
        [str(qubit_order[i]) for i in range(0, len(qubit_order), tick_stride)],
        fontsize=y_tick_fontsize,
    )

    if x_tick_stride is None:
        x_tick_indices = list(range(len(assignments)))
    else:
        stride = max(1, x_tick_stride)
        x_tick_indices = list(range(0, len(assignments), stride))

    ax.set_xticks(x_tick_indices)
    ax.set_xticklabels(
        [str(i) for i in x_tick_indices],
        rotation=x_tick_rotation,
        ha="right",
    )

    cbar = plt.colorbar(img, ax=ax, shrink=0.85)
    cbar.set_label("QPU")

    if show:
        plt.show()

    return ax


def plot_migration_timeline(  # pragma: no cover
    partition: PartitionTimeline,
    *,
    window_entanglement_cost: list[float] | None = None,
    ax: plt.Axes | None = None,
    show: bool = True,
) -> plt.Axes:
    """Plot moved-qubits-per-window over time.

    Args:
        partition: Timeline of partitions (window -> QPU -> qubit set).
        window_entanglement_cost: Optional series to plot on a secondary axis.
        ax: Optional matplotlib axes to draw on.
        show: Whether to call matplotlib's show() at the end.

    Returns:
        The matplotlib axes containing the plot.
    """
    assignments, _ = _assignments_and_qpu_count(partition)
    movement = _movement_counts(assignments)
    window_indices = list(range(1, len(assignments)))

    if ax is None:
        _, ax = plt.subplots(figsize=(9, 4))

    ax.plot(window_indices, movement, marker="o", label="Moved qubits")
    ax.set_xlabel("Window")
    ax.set_ylabel("Moved qubits")
    ax.set_title("Qubit Migration Timeline")
    ax.grid(True, alpha=0.3)

    if window_entanglement_cost is not None:
        if len(window_entanglement_cost) != len(movement):
            raise ValueError(
                "window_entanglement_cost must match number of transitions."
            )
        ax2 = ax.twinx()
        ax2.plot(
            window_indices,
            window_entanglement_cost,
            color="#d95f02",
            marker="x",
            label="Entanglement cost",
        )
        ax2.set_ylabel("Entanglement cost")

    ax.legend(loc="upper right")

    if show:
        plt.show()

    return ax


def plot_qubit_flow(  # pragma: no cover
    partition: PartitionTimeline,
    *,
    qubits: Sequence[int] | None = None,
    max_qubits: int | None = 20,
    sort_by_movement: bool = True,
    linewidth: float = 1.8,
    alpha: float = 0.9,
    show_legend: bool = True,
    ax: plt.Axes | None = None,
    cmap: str = "tab20",
    show: bool = True,
) -> plt.Axes:
    """Plot a trajectory-style flow of qubit assignments over windows.

    This is useful for quickly spotting churn and steady-state behavior in a
    partition schedule. Every line corresponds to a logical qubit and its
    y-position indicates the assigned QPU index at each window.

    Args:
        partition: Timeline of partitions (window -> QPU -> qubit set).
        qubits: Optional explicit set/order of qubits to draw.
        max_qubits: Maximum number of qubits to show when ``qubits`` is None.
        sort_by_movement: Sort auto-selected qubits by movement count.
        linewidth: Width of trajectory lines.
        alpha: Line opacity.
        show_legend: Whether to draw a legend for qubit labels.
        ax: Optional matplotlib axes to draw on.
        cmap: Matplotlib colormap used for qubit lines.
        show: Whether to call matplotlib's show() at the end.

    Returns:
        The matplotlib axes containing the flow plot.
    """
    assignments, num_qpus = _assignments_and_qpu_count(partition)
    available_qubits = _collect_qubits(assignments)

    if qubits is None:
        ordered = list(available_qubits)
        if sort_by_movement:
            movement = _qubit_movement_counts(ordered, assignments)
            movement.sort(key=lambda item: (-item[1], item[0]))
            ordered = [qubit for qubit, _ in movement]
        selected_qubits = (
            ordered if max_qubits is None else ordered[:max_qubits]
        )
    else:
        selected_qubits = [
            qubit for qubit in qubits if qubit in available_qubits
        ]

    if not selected_qubits:
        raise ValueError("No valid qubits selected for plotting.")

    if ax is None:
        _, ax = plt.subplots(figsize=(10, 5))

    color_map = plt.get_cmap(cmap, len(selected_qubits))
    window_indices = np.arange(len(assignments))

    for idx, qubit in enumerate(selected_qubits):
        trajectory = [
            assignment.get(qubit, np.nan) for assignment in assignments
        ]
        ax.plot(
            window_indices,
            trajectory,
            marker="o",
            linewidth=linewidth,
            alpha=alpha,
            color=color_map(idx),
            label=f"q{qubit}",
        )

    ax.set_xlabel("Window")
    ax.set_ylabel("QPU")
    ax.set_title("Qubit Flow Across Partition Windows")
    ax.set_yticks(range(num_qpus))
    ax.grid(True, linestyle="--", alpha=0.25)

    if show_legend:
        ncol = max(1, min(4, len(selected_qubits) // 6 + 1))
        ax.legend(loc="upper center", bbox_to_anchor=(0.5, -0.14), ncol=ncol)

    if show:
        plt.show()

    return ax


def plot_window_operation_profile(  # pragma: no cover
    partition: PartitionTimeline,
    windows: PartitionWindows,
    *,
    ax: plt.Axes | None = None,
    show: bool = True,
) -> plt.Axes:
    """Plot per-window operation mix for a partition schedule.

    Categories:
        - Single-qubit ops.
        - Local two-qubit ops (both operands on same QPU).
        - Remote two-qubit ops (operands on different QPUs).

    Args:
        partition: Timeline of partitions (window -> QPU -> qubit set).
        windows: Operations grouped by compiler window.
        ax: Optional matplotlib axes to draw on.
        show: Whether to call matplotlib's show() at the end.

    Returns:
        The matplotlib axes containing the stacked bar chart.
    """
    assignments, _ = _assignments_and_qpu_count(partition)
    if len(assignments) != len(windows):
        raise ValueError("partition and windows must have matching lengths.")

    single_counts: list[int] = []
    local_two_counts: list[int] = []
    remote_two_counts: list[int] = []

    for window_idx, (window_ops, assignment) in enumerate(
        zip(windows, assignments, strict=True)
    ):
        single = 0
        local_two = 0
        remote_two = 0
        for op in window_ops:
            qubits = op.qubit_indices
            if len(qubits) <= 1:
                single += 1
                continue
            if len(qubits) != 2:
                continue

            q1, q2 = qubits
            qpu_1 = assignment.get(q1)
            qpu_2 = assignment.get(q2)
            if qpu_1 is None or qpu_2 is None:
                raise ValueError(
                    "Missing qubit assignment for op in window "
                    f"{window_idx}: qubits={qubits}."
                )
            if qpu_1 == qpu_2:
                local_two += 1
            else:
                remote_two += 1

        single_counts.append(single)
        local_two_counts.append(local_two)
        remote_two_counts.append(remote_two)

    x = np.arange(len(windows))
    if ax is None:
        _, ax = plt.subplots(figsize=(10, 5))

    ax.bar(x, single_counts, label="1Q", color="#6baed6")
    ax.bar(
        x,
        local_two_counts,
        bottom=single_counts,
        label="2Q local",
        color="#74c476",
    )
    ax.bar(
        x,
        remote_two_counts,
        bottom=np.array(single_counts) + np.array(local_two_counts),
        label="2Q remote",
        color="#fb6a4a",
    )

    ax.set_xlabel("Window")
    ax.set_ylabel("Operation count")
    ax.set_title("Per-Window Operation Profile")
    ax.legend()
    ax.grid(axis="y", alpha=0.25)

    if show:
        plt.show()

    return ax


def _assignments_and_qpu_count(
    partition: PartitionTimeline,
) -> tuple[list[dict[int, int]], int]:
    if not partition:
        raise ValueError("partition must contain at least one window")

    num_qpus = len(partition[0])
    if num_qpus == 0:
        raise ValueError("partition windows must include at least one QPU")

    assignments: list[dict[int, int]] = []
    qpu_ids = {qpu.id for qpu in partition[0].keys()}
    for window_idx, window in enumerate(partition):
        if len(window) != num_qpus:
            raise ValueError("All windows must have the same QPU count")

        mapping: dict[int, int] = {}
        if {qpu.id for qpu in window.keys()} != qpu_ids:
            raise ValueError("All windows must use the same QPU identifiers")
        for qpu, qubits in window.items():
            for qubit in qubits:
                if qubit in mapping:
                    raise ValueError(
                        "Qubit assigned to multiple QPUs in "
                        f"window {window_idx}."
                    )
                mapping[qubit] = qpu.id
        assignments.append(mapping)

    return assignments, num_qpus


def _collect_qubits(assignments: list[dict[int, int]]) -> list[int]:
    qubits: set[int] = set()
    for mapping in assignments:
        qubits.update(mapping.keys())
    return sorted(qubits)


def _movement_counts(assignments: list[dict[int, int]]) -> list[int]:
    movement: list[int] = []
    for idx in range(1, len(assignments)):
        prev = assignments[idx - 1]
        curr = assignments[idx]
        all_qubits = set(prev) | set(curr)
        moved = sum(1 for q in all_qubits if prev.get(q) != curr.get(q))
        movement.append(moved)
    return movement


def _order_qubits(
    qubits: list[int],
    assignments: list[dict[int, int]],
    *,
    top_k_most_moved: int | None,
    sample_stride: int | None,
    sort_by_final_qpu: bool,
) -> list[int]:
    order = list(qubits)

    if top_k_most_moved is not None:
        movement = _qubit_movement_counts(order, assignments)
        movement.sort(key=lambda item: (-item[1], item[0]))
        order = [qubit for qubit, _ in movement[:top_k_most_moved]]

    if sort_by_final_qpu:
        final_assignment = assignments[-1]
        order.sort(key=lambda q: (final_assignment.get(q, -1), q))

    if sample_stride is not None and sample_stride > 1:
        order = order[::sample_stride]

    return order


def _qubit_movement_counts(
    qubits: list[int], assignments: list[dict[int, int]]
) -> list[tuple[int, int]]:
    counts: list[tuple[int, int]] = []
    for qubit in qubits:
        prev = assignments[0].get(qubit)
        moved = 0
        for idx in range(1, len(assignments)):
            curr = assignments[idx].get(qubit)
            if curr != prev:
                moved += 1
            prev = curr
        counts.append((qubit, moved))
    return counts
