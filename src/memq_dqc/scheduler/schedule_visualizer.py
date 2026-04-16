# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Matplotlib Gantt visualization for scheduler outputs."""

from __future__ import annotations

import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.patches import Patch, Rectangle

from memq_dqc.scheduler.schedule import (
    EntanglementGeneration,
    OperationSchedule,
    ScheduleEvent,
)

_LOCAL_FILL = "#dbeafe"
_REMOTE_FILL = "#f5d0fe"
_MEASURE_FILL = "#ccfbf1"
_SWAP_FILL = "#fde68a"
_ENTANGLEMENT_FILL = "#fecaca"
_ENTANGLEMENT_UNUSED_FILL = "#dc2626"
_EDGE_COLOR = "#475569"
_COMM_EDGE_COLOR = "#7c2d12"
_CONNECTOR_COLOR = "#7c3aed"
_TEXT_COLOR = "#0f172a"
_GRID_COLOR = "#cbd5e1"
_COMM_HATCH = "///"


def plot_schedule_gantt(
    schedule: OperationSchedule,
    *,
    ax: Axes | None = None,
    title: str | None = None,
    show: bool = False,
    explicit_ops: bool = False,
) -> Axes:
    """Render a scheduler-produced operation timeline as a Gantt chart.

    Args:
        schedule: Scheduler output to render.
        ax: Existing axes to draw into. A new figure and axes are created when
            omitted.
        title: Optional chart title.
        show: Whether to call ``matplotlib.pyplot.show`` after rendering.
        explicit_ops: Whether to render one row per scheduled event instead of
            one row per physical qubit.

    Returns:
        The Matplotlib axes containing the rendered schedule.

    Raises:
        ValueError: If the schedule does not contain any qubit timelines, or
            if ``explicit_ops`` is enabled and the schedule has no operations.
    """
    if not schedule.timelines:
        raise ValueError("schedule must contain at least one qubit timeline.")
    if explicit_ops and not schedule.operations:
        raise ValueError("schedule must contain at least one operation.")

    if ax is None:
        figure_width = max(10.0, schedule.makespan * 0.55 + 4.0)
        row_count = (
            len(schedule.operations)
            if explicit_ops
            else len(schedule.timelines)
        )
        figure_height = max(4.0, row_count * 0.7 + 1.8)
        _, ax = plt.subplots(figsize=(figure_width, figure_height))
    if explicit_ops:
        _plot_operation_rows(ax, schedule)
    else:
        _plot_qubit_rows(ax, schedule)
    ax.set_xlim(0.0, max(schedule.makespan, 1.0))
    ax.set_xlabel("Time")
    ax.set_ylabel("Operation" if explicit_ops else "Physical Qubit")
    ax.set_title("Schedule" if title is None else title)
    ax.set_axisbelow(True)
    ax.grid(axis="x", color=_GRID_COLOR, linestyle="--", linewidth=0.8)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    ax.legend(
        handles=[
            Patch(facecolor=_LOCAL_FILL, edgecolor=_EDGE_COLOR, label="Local"),
            Patch(
                facecolor=_REMOTE_FILL,
                edgecolor=_EDGE_COLOR,
                label="Remote",
            ),
            Patch(
                facecolor=_MEASURE_FILL,
                edgecolor=_EDGE_COLOR,
                label="Measure",
            ),
            Patch(facecolor=_SWAP_FILL, edgecolor=_EDGE_COLOR, label="Swap"),
            Patch(
                facecolor=_ENTANGLEMENT_FILL,
                edgecolor=_EDGE_COLOR,
                label="Entangle (used)",
            ),
            Patch(
                facecolor=_ENTANGLEMENT_UNUSED_FILL,
                edgecolor=_EDGE_COLOR,
                label="Entangle (unused)",
            ),
            Patch(
                facecolor="white",
                edgecolor=_COMM_EDGE_COLOR,
                hatch=_COMM_HATCH,
                label="Comm qubit",
            ),
        ],
        loc="upper right",
    )

    if show:
        plt.show()
    return ax


def _plot_qubit_rows(ax: Axes, schedule: OperationSchedule) -> None:
    """Render one row for each physical qubit in the schedule."""
    qubit_order = [timeline.qubit for timeline in schedule.timelines]
    y_by_qubit = {
        qubit: len(qubit_order) - 1 - index
        for index, qubit in enumerate(qubit_order)
    }
    bar_height = 0.62

    for op in schedule.operations:
        fill_color = _operation_fill(op)
        y_positions = [y_by_qubit[qubit] for qubit in op.qubits]
        center_x = op.start_time + (op.duration / 2)

        if len(y_positions) > 1:
            ax.vlines(
                center_x,
                min(y_positions),
                max(y_positions),
                colors=_CONNECTOR_COLOR if not op.is_remote else _EDGE_COLOR,
                linewidth=1.4,
                linestyles="--" if op.is_remote else "-",
                zorder=1,
            )

        for qubit, y in zip(op.qubits, y_positions, strict=True):
            rectangle = Rectangle(
                (op.start_time, y - bar_height / 2),
                op.duration,
                bar_height,
                facecolor=fill_color,
                edgecolor=_rectangle_edge_color(qubit),
                hatch=_rectangle_hatch(qubit),
                linewidth=1.4 if _is_comm_qubit_label(qubit) else 1.1,
                zorder=2,
            )
            ax.add_patch(rectangle)

        if op.duration >= 0.9:
            ax.text(
                center_x,
                min(y_positions),
                _event_label(op),
                ha="center",
                va="center",
                fontsize=9,
                color=_TEXT_COLOR,
                fontweight="bold",
                zorder=3,
            )

    ax.set_yticks([y_by_qubit[qubit] for qubit in qubit_order], qubit_order)
    ax.set_ylim(-0.8, len(qubit_order) - 0.2)


def _plot_operation_rows(ax: Axes, schedule: OperationSchedule) -> None:
    """Render one row for each scheduled event in dispatch order."""
    op_order = list(schedule.operations)
    bar_height = 0.62
    y_positions = [len(op_order) - 1 - index for index in range(len(op_order))]

    for op, y in zip(op_order, y_positions, strict=True):
        center_x = op.start_time + (op.duration / 2)
        rectangle = Rectangle(
            (op.start_time, y - bar_height / 2),
            op.duration,
            bar_height,
            facecolor=_operation_fill(op),
            edgecolor=_event_edge_color(op),
            hatch=_event_hatch(op),
            linewidth=1.4 if _event_has_comm_qubits(op) else 1.1,
            zorder=2,
        )
        ax.add_patch(rectangle)

        if op.duration >= 0.9:
            ax.text(
                center_x,
                y,
                _event_label(op),
                ha="center",
                va="center",
                fontsize=9,
                color=_TEXT_COLOR,
                fontweight="bold",
                zorder=3,
            )

    labels = [
        _explicit_op_row_label(index, op)
        for index, op in enumerate(op_order, start=1)
    ]
    ax.set_yticks(y_positions, labels)
    ax.set_ylim(-0.8, len(op_order) - 0.2)


def _operation_fill(op: ScheduleEvent) -> str:
    """Return the face color for a scheduled event."""
    if isinstance(op, EntanglementGeneration):
        if not op.was_used:
            return _ENTANGLEMENT_UNUSED_FILL
        return _ENTANGLEMENT_FILL
    if op.name == "rswap":
        return _SWAP_FILL
    if op.is_remote:
        return _REMOTE_FILL
    if op.name == "measure":
        return _MEASURE_FILL
    return _LOCAL_FILL


def _event_label(op: ScheduleEvent) -> str:
    """Return the chart label for one scheduled event."""
    if isinstance(op, EntanglementGeneration):
        if not op.was_used:
            return "unused epr"
        return "epr"
    return op.name


def _explicit_op_row_label(index: int, op: ScheduleEvent) -> str:
    """Return the y-axis row label for explicit operation rendering."""
    return f"{index}: {_event_label(op)}"


def _is_comm_qubit_label(qubit: str) -> bool:
    """Return whether a rendered schedule qubit label is a comm qubit."""
    return qubit.startswith("c")


def _rectangle_edge_color(qubit: str) -> str:
    """Return the rectangle border color for a schedule qubit row."""
    if _is_comm_qubit_label(qubit):
        return _COMM_EDGE_COLOR
    return _EDGE_COLOR


def _rectangle_hatch(qubit: str) -> str | None:
    """Return the hatch pattern for a schedule qubit row."""
    if _is_comm_qubit_label(qubit):
        return _COMM_HATCH
    return None


def _event_has_comm_qubits(op: ScheduleEvent) -> bool:
    """Return whether a scheduled event touches any communication qubits."""
    return any(_is_comm_qubit_label(qubit) for qubit in op.qubits)


def _event_edge_color(op: ScheduleEvent) -> str:
    """Return the rectangle border color for an operation-row event."""
    if _event_has_comm_qubits(op):
        return _COMM_EDGE_COLOR
    return _EDGE_COLOR


def _event_hatch(op: ScheduleEvent) -> str | None:
    """Return the hatch pattern for an operation-row event."""
    if _event_has_comm_qubits(op):
        return _COMM_HATCH
    return None
