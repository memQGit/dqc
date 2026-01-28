# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Visualization helpers for partition timelines."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable

import matplotlib.pyplot as plt
import numpy as np

PartitionTimeline = list[list[set[int]]]

__all__ = [
    "plot_partition_heatmap",
    "plot_migration_timeline",
    "summarize_qpu_flows",
    "run_length_encode_partitions",
]


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

    cmap_obj = plt.get_cmap(cmap, num_qpus)
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
    window_entanglement_cost: Iterable[float] | None = None,
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
        cost = list(window_entanglement_cost)
        if len(cost) != len(movement):
            raise ValueError(
                "window_entanglement_cost must match number of transitions."
            )
        ax2 = ax.twinx()
        ax2.plot(
            window_indices,
            cost,
            color="#d95f02",
            marker="x",
            label="Entanglement cost",
        )
        ax2.set_ylabel("Entanglement cost")

    ax.legend(loc="upper right")

    if show:
        plt.show()

    return ax


def summarize_qpu_flows(
    partition: PartitionTimeline, *, top_k: int | None = 5
) -> list[str]:
    """Summarize qubit flows between QPUs for each window transition.

    Args:
        partition: Timeline of partitions (window -> QPU -> qubit set).
        top_k: Maximum number of flows to report per window. If None, report
            all non-zero flows.

    Returns:
        A list of human-readable summaries, one per window transition.
    """
    assignments, _ = _assignments_and_qpu_count(partition)
    summaries: list[str] = []

    for window_idx in range(1, len(assignments)):
        flows = _flow_counts(
            assignments[window_idx - 1], assignments[window_idx]
        )
        flow_items = [
            ((src, dst), count)
            for (src, dst), count in flows.items()
            if src != dst and count > 0
        ]
        flow_items.sort(key=lambda item: (-item[1], item[0][0], item[0][1]))

        if top_k is not None:
            flow_items = flow_items[:top_k]

        if not flow_items:
            summaries.append(f"Window {window_idx}: no qubit movement")
            continue

        pieces = [
            f"{count} qubit(s) QPU{src}->QPU{dst}"
            for (src, dst), count in flow_items
        ]
        summary = f"Window {window_idx}: " + ", ".join(pieces)
        summaries.append(summary)

    return summaries


def run_length_encode_partitions(
    partition: PartitionTimeline, *, include_diffs: bool = True
) -> list[str]:
    """Compress consecutive identical partitions into runs.

    Args:
        partition: Timeline of partitions (window -> QPU -> qubit set).
        include_diffs: Whether to include per-change movement summaries.

    Returns:
        Lines describing run-length encoding of the partition timeline.
    """
    assignments, _ = _assignments_and_qpu_count(partition)
    if not assignments:
        return []

    windows = [tuple(frozenset(qpu) for qpu in window) for window in partition]
    lines: list[str] = []
    run_start = 0

    for idx in range(1, len(windows) + 1):
        is_end = idx == len(windows) or windows[idx] != windows[run_start]
        if not is_end:
            continue

        run_end = idx - 1
        window_repr = _format_window(partition[run_start])
        lines.append(f"windows {run_start}-{run_end}: {window_repr}")

        if include_diffs and idx < len(windows):
            diffs = _describe_window_diff(
                assignments[idx - 1], assignments[idx]
            )
            if diffs:
                lines.append(f"{idx}: " + ", ".join(diffs))
            else:
                lines.append(f"{idx}: no qubit movement")

        run_start = idx

    return lines


def _assignments_and_qpu_count(
    partition: PartitionTimeline,
) -> tuple[list[dict[int, int]], int]:
    if not partition:
        raise ValueError("partition must contain at least one window")

    num_qpus = len(partition[0])
    if num_qpus == 0:
        raise ValueError("partition windows must include at least one QPU")

    assignments: list[dict[int, int]] = []
    for window_idx, window in enumerate(partition):
        if len(window) != num_qpus:
            raise ValueError("All windows must have the same QPU count")

        mapping: dict[int, int] = {}
        for qpu_idx, qubits in enumerate(window):
            for qubit in qubits:
                if qubit in mapping:
                    raise ValueError(
                        "Qubit assigned to multiple QPUs in "
                        f"window {window_idx}."
                    )
                mapping[qubit] = qpu_idx
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


def _flow_counts(
    prev: dict[int, int], curr: dict[int, int]
) -> dict[tuple[int, int], int]:
    flows: dict[tuple[int, int], int] = defaultdict(int)
    all_qubits = set(prev) | set(curr)
    for qubit in all_qubits:
        src = prev.get(qubit)
        dst = curr.get(qubit)
        if src is None or dst is None:
            continue
        flows[(src, dst)] += 1
    return flows


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


def _format_window(window: list[set[int]]) -> str:
    parts = []
    for qubits in window:
        qubit_list = ", ".join(str(q) for q in sorted(qubits))
        parts.append("{" + qubit_list + "}")
    return "[" + ", ".join(parts) + "]"


def _describe_window_diff(
    prev: dict[int, int], curr: dict[int, int]
) -> list[str]:
    moves: dict[tuple[int, int], set[int]] = defaultdict(set)
    all_qubits = set(prev) | set(curr)
    for qubit in all_qubits:
        src = prev.get(qubit)
        dst = curr.get(qubit)
        if src == dst:
            continue
        if src is None or dst is None:
            continue
        moves[(src, dst)].add(qubit)

    summaries = []
    for (src, dst), qubits in sorted(moves.items()):
        qubit_list = ", ".join(str(q) for q in sorted(qubits))
        summaries.append(f"moved {{{qubit_list}}} from QPU{src}->QPU{dst}")
    return summaries
