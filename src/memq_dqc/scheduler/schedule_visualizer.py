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
) -> Axes:
    """Render a scheduler-produced operation timeline as a Gantt chart.

    Args:
        schedule: Scheduler output to render.
        ax: Existing axes to draw into. A new figure and axes are created when
            omitted.
        title: Optional chart title.
        show: Whether to call ``matplotlib.pyplot.show`` after rendering.

    Returns:
        The Matplotlib axes containing the rendered schedule.

    Raises:
        ValueError: If the schedule does not contain any qubit timelines.
    """
    if not schedule.timelines:
        raise ValueError("schedule must contain at least one qubit timeline.")

    if ax is None:
        figure_width = max(10.0, schedule.makespan * 0.55 + 4.0)
        figure_height = max(4.0, len(schedule.timelines) * 0.7 + 1.8)
        _, ax = plt.subplots(figsize=(figure_width, figure_height))

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
    ax.set_xlim(0.0, max(schedule.makespan, 1.0))
    ax.set_xlabel("Time")
    ax.set_ylabel("Physical Qubit")
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
                label="Entangle",
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


def _operation_fill(op: ScheduleEvent) -> str:
    """Return the face color for a scheduled event."""
    if isinstance(op, EntanglementGeneration):
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
        return "epr"
    return op.name


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
