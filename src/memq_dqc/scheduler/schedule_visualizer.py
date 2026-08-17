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
"""Matplotlib Gantt visualization for scheduler outputs."""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Any, Literal

import matplotlib.patheffects as patheffects
import matplotlib.pyplot as plt
from matplotlib.axes import Axes
from matplotlib.lines import Line2D
from matplotlib.patches import Patch, Rectangle
from matplotlib.ticker import MultipleLocator
from matplotlib.transforms import ScaledTranslation, Transform

from memq_dqc.scheduler.schedule import (
    EntanglementGeneration,
    OperationSchedule,
    ScheduleEvent,
)
from memq_dqc.settings import load_settings

# Upper bound (inches) for an auto-created figure's width. Width otherwise
# scales with the makespan, which produces an unrenderable figure for very
# long schedules (e.g. realistic, slow entanglement generation).
_MAX_AUTO_FIGURE_WIDTH = 48.0

# Default ("screen") palette. Kept identical to the original styling so the
# standard, non-``pretty`` chart renders exactly as before.
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


@dataclass(frozen=True, slots=True)
class _GanttStyle:
    """Visual styling for a scheduler Gantt chart.

    Bundling every color, line weight, and font choice behind a single object
    keeps the drawing helpers palette-agnostic: the same rendering code powers
    both the default on-screen chart and the publication-ready ``pretty``
    variant simply by swapping the style passed in.

    Attributes:
        local_fill: Fill color for local operation bars.
        remote_fill: Fill color for remote operation bars.
        measure_fill: Fill color for measurement bars.
        swap_fill: Fill color for routing swap bars.
        entanglement_fill: Fill color for consumed entanglement bars.
        entanglement_unused_fill: Fill color for unused entanglement bars.
        edge_color: Border color for ordinary (non-communication) bars.
        comm_edge_color: Border color for communication-qubit bars.
        connector_color: Color of the connector joining local multi-qubit
            operations.
        remote_connector_color: Color of the connector joining remote
            multi-qubit operations.
        text_color: Color of in-bar operation labels.
        grid_color: Color of the time-axis grid lines.
        comm_hatch: Hatch pattern applied to communication-qubit bars.
        bar_height: Height of each operation bar in data units.
        bar_linewidth: Border width for ordinary bars.
        comm_bar_linewidth: Border width for communication-qubit bars.
        connector_linewidth: Width of multi-qubit connector lines.
        grid_linestyle: Line style for the time-axis grid.
        grid_linewidth: Line width for the time-axis grid.
        label_fontsize: Font size for in-bar operation labels.
        label_fontweight: Font weight for in-bar operation labels.
        label_halo: Whether to draw a white outline behind bar labels so they
            stay legible on any fill (and where labels overflow narrow bars).
        min_label_duration: Bars shorter than this are left unlabeled. Set to
            ``0`` to label every bar.
        uppercase_text: Whether to upper-case all chart text (bar labels,
            legend entries, axis labels, tick labels, and title).
        zebra_fill: Background shade for alternating rows, or ``None`` to
            disable zebra striping.
        legend_loc: Matplotlib legend location anchor.
        legend_bbox: ``bbox_to_anchor`` for the legend in axes coordinates, or
            ``None`` to use ``legend_loc`` alone.
        legend_ncol: Number of legend columns.
        legend_fontsize: Legend font size, or ``None`` for the default.
        legend_framed: Whether to draw an opaque, bordered legend box.
        extra_figure_width: Extra inches added to an auto-created figure.
        extra_figure_height: Extra inches added to an auto-created figure.
        use_constrained_layout: Whether an auto-created figure should use
            constrained layout (reserves room for an out-of-axes legend).
        rc: Matplotlib ``rcParams`` overrides applied while rendering.
    """

    local_fill: str
    remote_fill: str
    measure_fill: str
    swap_fill: str
    entanglement_fill: str
    entanglement_unused_fill: str
    edge_color: str
    comm_edge_color: str
    connector_color: str
    remote_connector_color: str
    text_color: str
    grid_color: str
    comm_hatch: str
    bar_height: float
    bar_linewidth: float
    comm_bar_linewidth: float
    connector_linewidth: float
    grid_linestyle: str
    grid_linewidth: float
    label_fontsize: float
    label_fontweight: str
    label_halo: bool
    min_label_duration: float
    uppercase_text: bool
    zebra_fill: str | None
    legend_loc: str
    legend_bbox: tuple[float, float] | None
    legend_ncol: int
    legend_fontsize: float | None
    legend_framed: bool
    extra_figure_width: float
    extra_figure_height: float
    use_constrained_layout: bool
    rc: dict[str, Any] = field(default_factory=dict)


def _default_style() -> _GanttStyle:
    """Return the standard on-screen Gantt styling."""
    return _GanttStyle(
        local_fill=_LOCAL_FILL,
        remote_fill=_REMOTE_FILL,
        measure_fill=_MEASURE_FILL,
        swap_fill=_SWAP_FILL,
        entanglement_fill=_ENTANGLEMENT_FILL,
        entanglement_unused_fill=_ENTANGLEMENT_UNUSED_FILL,
        edge_color=_EDGE_COLOR,
        comm_edge_color=_COMM_EDGE_COLOR,
        connector_color=_CONNECTOR_COLOR,
        remote_connector_color=_EDGE_COLOR,
        text_color=_TEXT_COLOR,
        grid_color=_GRID_COLOR,
        comm_hatch=_COMM_HATCH,
        bar_height=0.62,
        bar_linewidth=1.1,
        comm_bar_linewidth=1.4,
        connector_linewidth=1.4,
        grid_linestyle="--",
        grid_linewidth=0.8,
        label_fontsize=9.0,
        label_fontweight="bold",
        label_halo=False,
        min_label_duration=0.9,
        uppercase_text=False,
        zebra_fill=None,
        legend_loc="upper right",
        legend_bbox=None,
        legend_ncol=1,
        legend_fontsize=None,
        legend_framed=False,
        extra_figure_width=0.0,
        extra_figure_height=0.0,
        use_constrained_layout=False,
    )


# ===========================================================================
# Publication ("pretty") rendering.
#
# A bespoke, print-safe rendering tuned for journal figures. It is independent
# of the default screen rendering above so the standard chart is unaffected.
# Design goals: grayscale-safe luminance separation (pale-purple local vs
# solid-purple remote), a single teal accent for the entanglement family,
# monospace identifiers, module-grouped rows with labelled brackets, subtle
# gridlines, light connector links, and a compact legend.
# ===========================================================================

_PRETTY_RC: dict[str, Any] = {
    "font.family": "monospace",
    "font.size": 10.5,
    "axes.labelsize": 11.0,
    "axes.labelweight": "bold",
    "axes.labelcolor": "#3a3550",
    "axes.edgecolor": "#cdcad9",
    "axes.linewidth": 0.8,
    "xtick.color": "#6c6884",
    "ytick.color": "#3a3550",
    "xtick.labelsize": 9.5,
    "ytick.labelsize": 10.0,
    "figure.facecolor": "white",
    "axes.facecolor": "white",
    "hatch.linewidth": 0.6,
}

# memQ light / print palette: purple = computation, teal = entanglement.
_PRETTY_TEXT = "#2c2a3c"
_PRETTY_LOCAL_FILL = "#ece5f7"
_PRETTY_LOCAL_EDGE = "#b6a6dc"
_PRETTY_REMOTE_FILL = "#5a2d86"
_PRETTY_REMOTE_EDGE = "#3f1f63"
_PRETTY_REMOTE_TEXT = "#ffffff"
_PRETTY_MEASURE_FILL = "#eaeaef"
_PRETTY_MEASURE_EDGE = "#bcbcc8"
_PRETTY_SWAP_FILL = "#d9ccf2"
_PRETTY_SWAP_EDGE = "#9c84cf"
_PRETTY_TEAL = "#16a394"
_PRETTY_TEAL_DARK = "#0b5e54"
_PRETTY_RESERVED_FILL = "#e9f8f4"
_PRETTY_MODULE_BAND = "#f7f4fc"
_PRETTY_COMM_BAND = "#edf9f6"
_PRETTY_MODULE_ACCENT = "#6b3fa0"
_PRETTY_COMM_ACCENT = "#0f8c7e"
_PRETTY_GRID = "#e6e4ee"
_PRETTY_GRID_MINOR = "#f1f0f6"
_PRETTY_LINK_LOCAL = "#6b3fa0"
_PRETTY_LINK_REMOTE = "#0f8c7e"
_PRETTY_SPARSE_HATCH = "//"

_RESERVED_OP_NAMES = frozenset({"catent", "catdisent"})
_QUBIT_LABEL_RE = re.compile(r"^([qc])(\d+)\[(\d+)\]$")

# role -> (facecolor, edgecolor, hatch, text_color)
_PRETTY_ROLE_VISUAL: dict[str, tuple[str, str, str | None, str]] = {
    "local": (_PRETTY_LOCAL_FILL, _PRETTY_LOCAL_EDGE, None, _PRETTY_TEXT),
    "remote": (
        _PRETTY_REMOTE_FILL,
        _PRETTY_REMOTE_EDGE,
        None,
        _PRETTY_REMOTE_TEXT,
    ),
    "measure": (
        _PRETTY_MEASURE_FILL,
        _PRETTY_MEASURE_EDGE,
        None,
        _PRETTY_TEXT,
    ),
    "swap": (_PRETTY_SWAP_FILL, _PRETTY_SWAP_EDGE, None, _PRETTY_TEXT),
    "epr_consumed": (
        _PRETTY_TEAL,
        _PRETTY_TEAL_DARK,
        None,
        _PRETTY_TEAL_DARK,
    ),
    "epr_unused": (
        "#ffffff",
        _PRETTY_TEAL_DARK,
        _PRETTY_SPARSE_HATCH,
        _PRETTY_TEAL_DARK,
    ),
    "reserved": (
        _PRETTY_RESERVED_FILL,
        _PRETTY_TEAL,
        _PRETTY_SPARSE_HATCH,
        _PRETTY_TEAL_DARK,
    ),
}

# role -> sentence-case legend label (legend stays sentence case by design).
_PRETTY_ROLE_LEGEND: dict[str, str] = {
    "local": "Local gate",
    "remote": "Remote (non-local) gate",
    "measure": "Measurement",
    "swap": "Routed swap",
    "epr_consumed": "Entanglement generation",
    "epr_unused": "Entanglement — unused",
    "reserved": "Entanglement — reserved",
}

# Friendly display strings for the scheduler's configured time unit.
_TIME_UNIT_LABELS = {"us": "μs", "µs": "μs", "ns": "ns", "ms": "ms", "s": "s"}


def _pretty_time_unit_label() -> str:
    """Return a display label for the scheduler's configured time unit."""
    try:
        unit = load_settings().global_settings.time_unit
    except Exception:  # pragma: no cover - settings should always load
        unit = None
    if not unit:
        return "μs"
    return _TIME_UNIT_LABELS.get(unit.lower(), unit)


def _pretty_role(op: ScheduleEvent) -> str:
    """Classify a scheduled event into a print-palette role."""
    if isinstance(op, EntanglementGeneration):
        return "epr_consumed" if op.was_used else "epr_unused"
    name = op.name.lower()
    if name in _RESERVED_OP_NAMES:
        return "reserved"
    if name == "rswap":
        return "swap"
    if op.is_remote:
        return "remote"
    if name == "measure":
        return "measure"
    return "local"


def _parse_qubit_label(label: str) -> tuple[str, int | None, int | None]:
    """Parse ``q<qpu>[<id>]`` / ``c<qpu>[<id>]`` into (kind, qpu, id)."""
    match = _QUBIT_LABEL_RE.match(label)
    if match is not None:
        kind = "comm" if match.group(1) == "c" else "comp"
        return kind, int(match.group(2)), int(match.group(3))
    kind = "comm" if label.lower().startswith("c") else "comp"
    return kind, None, None


def plot_schedule_gantt(
    schedule: OperationSchedule,
    *,
    ax: Axes | None = None,
    title: str | None = None,
    show: bool = False,
    explicit_ops: bool = False,
    display: Literal["pretty", "legacy"] = "pretty",
) -> Axes:
    """Render a scheduler-produced operation timeline as a Gantt chart.

    Args:
        schedule: Scheduler output to render.
        ax: Existing axes to draw into. A new figure and axes are created when
            omitted.
        title: Optional chart title (ignored in ``"pretty"`` display, which is
            captioned externally for a paper).
        show: Whether to call ``matplotlib.pyplot.show`` after rendering.
        explicit_ops: Whether to render one row per scheduled event instead of
            one row per physical qubit.
        display: Which rendering to produce. ``"pretty"`` (the default) is the
            publication-ready variant: a print-safe, grayscale-friendly memQ
            palette (pale-purple local vs solid-purple remote gates,
            neutral-gray measurement, teal entanglement), monospace
            identifiers, module-grouped rows with labelled brackets, subtle
            gridlines, and a compact legend suitable for a journal figure.
            ``"legacy"`` is the original on-screen/diagnostic chart (pastel
            palette, communication-qubit hatching, inside legend).

    Returns:
        The Matplotlib axes containing the rendered schedule.

    Raises:
        ValueError: If ``display`` is not a recognized value, if the schedule
            does not contain any qubit timelines, or if ``explicit_ops`` is
            enabled and the schedule has no operations.
    """
    if display not in ("pretty", "legacy"):
        raise ValueError(
            f"display must be 'pretty' or 'legacy', got {display!r}."
        )
    if not schedule.timelines:
        raise ValueError("schedule must contain at least one qubit timeline.")
    if explicit_ops and not schedule.operations:
        raise ValueError("schedule must contain at least one operation.")

    if display == "pretty":
        with plt.rc_context(_PRETTY_RC):
            return _render_pretty_gantt(
                schedule,
                ax=ax,
                title=title,
                show=show,
                explicit_ops=explicit_ops,
            )

    style = _default_style()
    with plt.rc_context(style.rc):
        return _render_schedule_gantt(
            schedule,
            style=style,
            ax=ax,
            title=title,
            show=show,
            explicit_ops=explicit_ops,
        )


def _render_schedule_gantt(
    schedule: OperationSchedule,
    *,
    style: _GanttStyle,
    ax: Axes | None,
    title: str | None,
    show: bool,
    explicit_ops: bool,
) -> Axes:
    """Draw the schedule onto ``ax`` (or a freshly created figure)."""
    if ax is None:
        row_count = (
            len(schedule.operations)
            if explicit_ops
            else len(schedule.timelines)
        )
        figure_width = min(
            _MAX_AUTO_FIGURE_WIDTH, max(10.0, schedule.makespan * 0.55 + 4.0)
        )
        figure_height = max(4.0, row_count * 0.7 + 1.8)
        figure_width += style.extra_figure_width
        figure_height += style.extra_figure_height
        _, ax = plt.subplots(
            figsize=(figure_width, figure_height),
            layout="constrained" if style.use_constrained_layout else None,
        )

    if explicit_ops:
        _plot_operation_rows(ax, schedule, style)
    else:
        _plot_qubit_rows(ax, schedule, style)

    ax.set_xlim(0.0, max(schedule.makespan, 1.0))
    ax.set_xlabel(_format_text(f"Time ({_pretty_time_unit_label()})", style))
    ax.set_ylabel(
        _format_text("Operation" if explicit_ops else "Physical Qubit", style)
    )
    ax.set_title(_format_text("Schedule" if title is None else title, style))
    ax.set_axisbelow(True)
    ax.grid(
        axis="x",
        color=style.grid_color,
        linestyle=style.grid_linestyle,
        linewidth=style.grid_linewidth,
    )
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)

    _add_legend(ax, style)

    if show:
        plt.show()
    return ax


def _add_legend(ax: Axes, style: _GanttStyle) -> None:
    """Attach the operation-category legend to the axes."""
    handles = [
        Patch(
            facecolor=style.local_fill,
            edgecolor=style.edge_color,
            label=_format_text("Local", style),
        ),
        Patch(
            facecolor=style.remote_fill,
            edgecolor=style.edge_color,
            label=_format_text("Remote", style),
        ),
        Patch(
            facecolor=style.measure_fill,
            edgecolor=style.edge_color,
            label=_format_text("Measure", style),
        ),
        Patch(
            facecolor=style.swap_fill,
            edgecolor=style.edge_color,
            label=_format_text("Swap", style),
        ),
        Patch(
            facecolor=style.entanglement_fill,
            edgecolor=style.comm_edge_color,
            label=_format_text("Entangle (used)", style),
        ),
        Patch(
            facecolor=style.entanglement_unused_fill,
            edgecolor=style.comm_edge_color,
            hatch=style.comm_hatch,
            label=_format_text("Entangle (unused)", style),
        ),
        Patch(
            facecolor="white",
            edgecolor=style.comm_edge_color,
            hatch=style.comm_hatch,
            label=_format_text("Comm qubit", style),
        ),
    ]
    legend_kwargs: dict[str, Any] = {
        "handles": handles,
        "loc": style.legend_loc,
        "ncol": style.legend_ncol,
        "frameon": True,
    }
    if style.legend_bbox is not None:
        legend_kwargs["bbox_to_anchor"] = style.legend_bbox
    if style.legend_fontsize is not None:
        legend_kwargs["fontsize"] = style.legend_fontsize
    if style.legend_framed:
        legend_kwargs.update(
            columnspacing=1.4,
            handlelength=1.6,
            handletextpad=0.6,
            borderpad=0.7,
        )

    legend = ax.legend(**legend_kwargs)

    if style.legend_framed:
        frame = legend.get_frame()
        frame.set_facecolor("white")
        frame.set_edgecolor("#cbd5e1")
        frame.set_linewidth(0.8)
        frame.set_alpha(1.0)


def _format_text(text: str, style: _GanttStyle) -> str:
    """Apply the style's text casing to a chart string."""
    return text.upper() if style.uppercase_text else text


def _draw_bar_label(
    ax: Axes,
    x: float,
    y: float,
    text: str,
    style: _GanttStyle,
) -> None:
    """Draw a centered operation label, optionally with a white halo."""
    effects = (
        [patheffects.withStroke(linewidth=2.6, foreground="white")]
        if style.label_halo
        else None
    )
    ax.text(
        x,
        y,
        _format_text(text, style),
        ha="center",
        va="center",
        fontsize=style.label_fontsize,
        color=style.text_color,
        fontweight=style.label_fontweight,
        zorder=3,
        path_effects=effects,
    )


def _draw_zebra_rows(ax: Axes, row_count: int, style: _GanttStyle) -> None:
    """Shade alternating rows to aid horizontal scanning."""
    if style.zebra_fill is None:
        return
    for row in range(row_count):
        if row % 2 == 0:
            continue
        ax.axhspan(
            row - 0.5,
            row + 0.5,
            facecolor=style.zebra_fill,
            edgecolor="none",
            zorder=0,
        )


def _plot_qubit_rows(
    ax: Axes, schedule: OperationSchedule, style: _GanttStyle
) -> None:
    """Render one row for each physical qubit in the schedule."""
    qubit_order = [timeline.qubit for timeline in schedule.timelines]
    y_by_qubit = {
        qubit: len(qubit_order) - 1 - index
        for index, qubit in enumerate(qubit_order)
    }
    bar_height = style.bar_height

    _draw_zebra_rows(ax, len(qubit_order), style)

    for op in schedule.operations:
        fill_color = _operation_fill(op, style)
        y_positions = [y_by_qubit[qubit] for qubit in op.qubits]
        center_x = op.start_time + (op.duration / 2)

        if len(y_positions) > 1:
            connector = (
                style.remote_connector_color
                if op.is_remote
                else style.connector_color
            )
            ax.vlines(
                center_x,
                min(y_positions),
                max(y_positions),
                colors=connector,
                linewidth=style.connector_linewidth,
                linestyles="--" if op.is_remote else "-",
                zorder=1,
            )

        for qubit, y in zip(op.qubits, y_positions, strict=True):
            rectangle = Rectangle(
                (op.start_time, y - bar_height / 2),
                op.duration,
                bar_height,
                facecolor=fill_color,
                edgecolor=_rectangle_edge_color(qubit, style),
                hatch=_rectangle_hatch(qubit, style),
                linewidth=(
                    style.comm_bar_linewidth
                    if _is_comm_qubit_label(qubit)
                    else style.bar_linewidth
                ),
                zorder=2,
            )
            ax.add_patch(rectangle)

        if op.duration >= style.min_label_duration:
            _draw_bar_label(
                ax, center_x, min(y_positions), _event_label(op), style
            )

    ax.set_yticks(
        [y_by_qubit[qubit] for qubit in qubit_order],
        [_format_text(qubit, style) for qubit in qubit_order],
    )
    ax.set_ylim(-0.8, len(qubit_order) - 0.2)


def _plot_operation_rows(
    ax: Axes, schedule: OperationSchedule, style: _GanttStyle
) -> None:
    """Render one row for each scheduled event in dispatch order."""
    op_order = list(schedule.operations)
    bar_height = style.bar_height
    y_positions = [len(op_order) - 1 - index for index in range(len(op_order))]

    _draw_zebra_rows(ax, len(op_order), style)

    for op, y in zip(op_order, y_positions, strict=True):
        center_x = op.start_time + (op.duration / 2)
        rectangle = Rectangle(
            (op.start_time, y - bar_height / 2),
            op.duration,
            bar_height,
            facecolor=_operation_fill(op, style),
            edgecolor=_event_edge_color(op, style),
            hatch=_event_hatch(op, style),
            linewidth=(
                style.comm_bar_linewidth
                if _event_has_comm_qubits(op)
                else style.bar_linewidth
            ),
            zorder=2,
        )
        ax.add_patch(rectangle)

        if op.duration >= style.min_label_duration:
            _draw_bar_label(ax, center_x, y, _event_label(op), style)

    labels = [
        _format_text(_explicit_op_row_label(index, op), style)
        for index, op in enumerate(op_order, start=1)
    ]
    ax.set_yticks(y_positions, labels)
    ax.set_ylim(-0.8, len(op_order) - 0.2)


def _operation_fill(op: ScheduleEvent, style: _GanttStyle) -> str:
    """Return the face color for a scheduled event."""
    if isinstance(op, EntanglementGeneration):
        if not op.was_used:
            return style.entanglement_unused_fill
        return style.entanglement_fill
    if op.name == "rswap":
        return style.swap_fill
    if op.is_remote:
        return style.remote_fill
    if op.name == "measure":
        return style.measure_fill
    return style.local_fill


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


def _rectangle_edge_color(qubit: str, style: _GanttStyle) -> str:
    """Return the rectangle border color for a schedule qubit row."""
    if _is_comm_qubit_label(qubit):
        return style.comm_edge_color
    return style.edge_color


def _rectangle_hatch(qubit: str, style: _GanttStyle) -> str | None:
    """Return the hatch pattern for a schedule qubit row."""
    if _is_comm_qubit_label(qubit):
        return style.comm_hatch
    return None


def _event_has_comm_qubits(op: ScheduleEvent) -> bool:
    """Return whether a scheduled event touches any communication qubits."""
    return any(_is_comm_qubit_label(qubit) for qubit in op.qubits)


def _event_edge_color(op: ScheduleEvent, style: _GanttStyle) -> str:
    """Return the rectangle border color for an operation-row event."""
    if _event_has_comm_qubits(op):
        return style.comm_edge_color
    return style.edge_color


def _event_hatch(op: ScheduleEvent, style: _GanttStyle) -> str | None:
    """Return the hatch pattern for an operation-row event."""
    if _event_has_comm_qubits(op):
        return style.comm_hatch
    return None


# ===========================================================================
# Publication ("pretty") rendering helpers.
# ===========================================================================

_PRETTY_BAR_HEIGHT = 0.6


@dataclass(slots=True)
class _PrettyGroup:
    """One labelled row group (a module of qubits, or all comm qubits)."""

    title: str
    accent: str
    is_comm: bool
    labels: list[str]


def _pretty_event_text(op: ScheduleEvent) -> str:
    """Return the upper-cased in-bar label for a scheduled event."""
    if isinstance(op, EntanglementGeneration):
        return "EPR"
    return op.name.upper()


def _group_qubits(labels: list[str]) -> list[_PrettyGroup]:
    """Cluster qubit labels into per-module groups, comm qubits last."""
    computation: dict[int | None, list[tuple[int, str]]] = {}
    computation_order: list[int | None] = []
    communication: list[tuple[int, int, str]] = []
    for label in labels:
        kind, qpu, qubit_id = _parse_qubit_label(label)
        if kind == "comm":
            communication.append(
                (qpu if qpu is not None else 10**9, qubit_id or 0, label)
            )
            continue
        if qpu not in computation:
            computation[qpu] = []
            computation_order.append(qpu)
        computation[qpu].append((qubit_id or 0, label))

    groups: list[_PrettyGroup] = []
    for qpu in computation_order:
        ordered = [lbl for _, lbl in sorted(computation[qpu])]
        title = f"MODULE {qpu}" if qpu is not None else "QUBITS"
        groups.append(
            _PrettyGroup(title, _PRETTY_MODULE_ACCENT, False, ordered)
        )
    if communication:
        ordered = [
            lbl
            for *_, lbl in sorted(communication, key=lambda t: (-t[0], t[1]))
        ]
        groups.append(_PrettyGroup("COMM", _PRETTY_COMM_ACCENT, True, ordered))
    return groups


def _layout_pretty_groups(
    groups: list[_PrettyGroup],
) -> tuple[
    dict[str, float], list[tuple[str, str, bool, float, float]], int, list[str]
]:
    """Assign row positions, leaving a blank row between groups.

    Returns the per-qubit y position, the (title, accent, is_comm, y_min,
    y_max) span for each group, the total row count, and the ordered qubit
    labels (top to bottom).
    """
    rows: list[str | None] = []
    for index, group in enumerate(groups):
        if index:
            rows.append(None)
        rows.extend(group.labels)

    row_count = len(rows)
    positions: dict[str, float] = {}
    ordered: list[str] = []
    for index, row in enumerate(rows):
        if row is None:
            continue
        positions[row] = float((row_count - 1) - index)
        ordered.append(row)

    spans: list[tuple[str, str, bool, float, float]] = []
    for group in groups:
        ys = [positions[label] for label in group.labels]
        spans.append(
            (group.title, group.accent, group.is_comm, min(ys), max(ys))
        )
    return positions, spans, row_count, ordered


def _nice_tick_step(span: float) -> float:
    """Return a tidy major-gridline interval for the given time span.

    Targets roughly seven major gridlines and snaps to a 1/2/5 ladder scaled
    to the span's magnitude, so the step stays sensible for both tiny and very
    large makespans (the latter previously fell off the fixed ladder).
    """
    if span <= 0:
        return 1.0
    target = span / 7.0
    # Floor the magnitude at 1.0 so the step never drops below one time unit,
    # matching the original fixed ladder for small spans.
    magnitude = 10.0 ** math.floor(math.log10(max(target, 1.0)))
    for candidate in (1.0, 2.0, 5.0):
        step = candidate * magnitude
        if step >= target:
            return step
    return 10.0 * magnitude
    return 100.0


def _draw_pretty_label(
    ax: Axes, x: float, y: float, text: str, color: str
) -> None:
    """Draw a centered monospace bar label with a white halo on dark text."""
    effects = (
        None
        if color.lower() == _PRETTY_REMOTE_TEXT
        else [patheffects.withStroke(linewidth=2.4, foreground="white")]
    )
    ax.text(
        x,
        y,
        text,
        ha="center",
        va="center",
        fontsize=9.0,
        fontweight="bold",
        color=color,
        zorder=5,
        path_effects=effects,
    )


def _draw_pretty_link(
    ax: Axes, x: float, ys: list[float], *, color: str, dashed: bool
) -> None:
    """Draw a thin vertical connector spanning every partner row, dotted."""
    ax.plot(
        [x, x],
        [min(ys), max(ys)],
        color=color,
        linewidth=1.1,
        linestyle=(0, (4, 2)) if dashed else "-",
        solid_capstyle="round",
        zorder=3,
    )
    ax.plot(
        [x] * len(ys),
        ys,
        linestyle="none",
        marker="o",
        markersize=3.0,
        markerfacecolor=color,
        markeredgecolor=color,
        zorder=4,
    )


def _draw_pretty_group_bands(
    ax: Axes, spans: list[tuple[str, str, bool, float, float]]
) -> None:
    """Shade a subtle background band behind each row group."""
    for _, _, is_comm, y_min, y_max in spans:
        ax.axhspan(
            y_min - 0.5,
            y_max + 0.5,
            facecolor=_PRETTY_COMM_BAND if is_comm else _PRETTY_MODULE_BAND,
            edgecolor="none",
            zorder=0,
        )


def _left_margin_transform(ax: Axes, dx_inch: float) -> Transform:
    """Return a transform: x a fixed inch offset left of the axes, y in data.

    Using a fixed inch offset (rather than an axes fraction) keeps the
    bracket and labels tight against the axis regardless of figure width.
    """
    return ax.get_yaxis_transform() + ScaledTranslation(
        dx_inch, 0.0, ax.figure.dpi_scale_trans
    )


def _draw_pretty_brackets(
    ax: Axes,
    spans: list[tuple[str, str, bool, float, float]],
    row_count: int,
) -> None:
    """Draw a left-margin bracket and rotated title for each group."""
    bracket_transform = _left_margin_transform(ax, -0.60)
    title_transform = _left_margin_transform(ax, -0.80)
    for title, accent, _, y_min, y_max in spans:
        ax.plot(
            [0.0, 0.0],
            [y_min - 0.4, y_max + 0.4],
            transform=bracket_transform,
            color=accent,
            linewidth=3.0,
            solid_capstyle="round",
            clip_on=False,
            zorder=5,
        )
        ax.text(
            0.0,
            (y_min + y_max) / 2.0,
            title,
            transform=title_transform,
            color=accent,
            fontsize=8.5,
            fontweight="bold",
            ha="center",
            va="center",
            rotation=90,
            clip_on=False,
            zorder=5,
        )
    ax.text(
        0.0,
        (row_count - 1) / 2.0,
        "PHYSICAL QUBIT",
        transform=_left_margin_transform(ax, -1.08),
        color="#3a3550",
        fontsize=10.0,
        fontweight="bold",
        ha="center",
        va="center",
        rotation=90,
        clip_on=False,
        zorder=5,
    )


def _draw_pretty_bars(
    ax: Axes, schedule: OperationSchedule, positions: dict[str, float]
) -> tuple[bool, bool]:
    """Draw operation bars, links, and labels; report which links appear."""
    drew_local_link = False
    drew_remote_link = False
    for op in schedule.operations:
        role = _pretty_role(op)
        face, edge, hatch, text_color = _PRETTY_ROLE_VISUAL[role]
        # Remote gates are drawn only on their two data operands; the comm
        # qubits carry their own entanglement bars.
        bar_qubits = op.qubits[:2] if role == "remote" else op.qubits
        drawn_ys = [
            positions[qubit] for qubit in bar_qubits if qubit in positions
        ]
        if not drawn_ys:
            continue
        for qubit in bar_qubits:
            y = positions.get(qubit)
            if y is None:
                continue
            ax.add_patch(
                Rectangle(
                    (op.start_time, y - _PRETTY_BAR_HEIGHT / 2),
                    op.duration,
                    _PRETTY_BAR_HEIGHT,
                    facecolor=face,
                    edgecolor=edge,
                    hatch=hatch,
                    linewidth=1.0,
                    zorder=2,
                )
            )

        label = _pretty_event_text(op)
        if label and op.duration > 0:
            center_x = op.start_time + op.duration / 2.0
            _draw_pretty_label(ax, center_x, min(drawn_ys), label, text_color)

        if role in ("local", "remote", "epr_consumed", "epr_unused"):
            # Connect every qubit the operation touches: for remote gates this
            # spans the data operands and the comm qubits carrying the link.
            link_ys = [
                positions[qubit] for qubit in op.qubits if qubit in positions
            ]
            if len(link_ys) >= 2 and max(link_ys) != min(link_ys):
                center_x = op.start_time + op.duration / 2.0
                if role == "local":
                    _draw_pretty_link(
                        ax,
                        center_x,
                        link_ys,
                        color=_PRETTY_LINK_LOCAL,
                        dashed=False,
                    )
                    drew_local_link = True
                else:
                    _draw_pretty_link(
                        ax,
                        center_x,
                        link_ys,
                        color=_PRETTY_LINK_REMOTE,
                        dashed=True,
                    )
                    drew_remote_link = True
    return drew_local_link, drew_remote_link


def _pretty_present_roles(schedule: OperationSchedule) -> set[str]:
    """Return the set of palette roles that actually appear."""
    return {_pretty_role(op) for op in schedule.operations}


def _configure_pretty_xaxis(ax: Axes, schedule: OperationSchedule) -> None:
    """Apply the shared x-axis limits, gridlines, and label."""
    makespan = max(schedule.makespan, 1.0)
    ax.set_xlim(0.0, makespan)
    step = _nice_tick_step(makespan)
    ax.xaxis.set_major_locator(MultipleLocator(step))
    # Five minor divisions per major step keeps the minor-tick count bounded;
    # a fixed per-unit step would exceed Matplotlib's locator limit on large
    # makespans.
    ax.xaxis.set_minor_locator(MultipleLocator(step / 5.0))
    ax.set_axisbelow(True)
    ax.grid(
        axis="x", which="major", color=_PRETTY_GRID, linewidth=0.8, zorder=0
    )
    ax.grid(
        axis="x",
        which="minor",
        color=_PRETTY_GRID_MINOR,
        linewidth=0.5,
        zorder=0,
    )
    ax.tick_params(axis="x", which="both", length=0)
    ax.set_xlabel(f"TIME ({_pretty_time_unit_label()})", labelpad=8.0)


def _pretty_legend(
    ax: Axes,
    present_roles: set[str],
    drew_remote_link: bool,
) -> None:
    """Attach a compact 3-column legend just above the axes.

    Only keys that actually appear are shown. The local two-qubit link is
    omitted on purpose: a vertical line between two gate cells is unambiguous
    to a quantum-computing reader and would only add clutter.
    """
    handles: list[Any] = []
    role_order = (
        "local",
        "remote",
        "measure",
        "swap",
        "epr_consumed",
        "reserved",
        "epr_unused",
    )
    for role in role_order:
        if role not in present_roles:
            continue
        face, edge, hatch, _ = _PRETTY_ROLE_VISUAL[role]
        handles.append(
            Patch(
                facecolor=face,
                edgecolor=edge,
                hatch=hatch,
                label=_PRETTY_ROLE_LEGEND[role],
            )
        )
    if drew_remote_link:
        handles.append(
            Line2D(
                [0],
                [0],
                color=_PRETTY_LINK_REMOTE,
                linewidth=1.4,
                linestyle=(0, (4, 2)),
                label="Remote / EPR link",
            )
        )
    ax.legend(
        handles=handles,
        loc="lower center",
        bbox_to_anchor=(0.5, 1.012),
        ncol=min(len(handles), 3),
        frameon=False,
        fontsize=8.5,
        handlelength=1.4,
        columnspacing=1.3,
        handletextpad=0.5,
        labelspacing=0.5,
        borderaxespad=0.0,
    )


def _render_pretty_gantt(
    schedule: OperationSchedule,
    *,
    ax: Axes | None,
    title: str | None,
    show: bool,
    explicit_ops: bool,
) -> Axes:
    """Render the publication-ready Gantt chart."""
    if explicit_ops:
        return _render_pretty_op_rows(schedule, ax=ax, title=title, show=show)

    groups = _group_qubits([timeline.qubit for timeline in schedule.timelines])
    positions, spans, row_count, ordered = _layout_pretty_groups(groups)

    if ax is None:
        figure_width = min(
            _MAX_AUTO_FIGURE_WIDTH, max(9.0, schedule.makespan * 0.42 + 3.6)
        )
        figure_height = max(3.6, row_count * 0.46 + 2.4)
        fig, ax = plt.subplots(figsize=(figure_width, figure_height))
        fig.subplots_adjust(
            left=min(0.3, 1.4 / figure_width),
            right=0.985,
            top=1.0 - min(0.14, 0.62 / figure_height),
            bottom=min(0.18, 1.0 / figure_height),
        )

    _draw_pretty_group_bands(ax, spans)
    _, drew_remote = _draw_pretty_bars(ax, schedule, positions)

    _configure_pretty_xaxis(ax, schedule)
    ax.set_ylim(-0.7, row_count - 0.3)
    ax.set_yticks(
        [positions[label] for label in ordered],
        [label.upper() for label in ordered],
    )
    ax.tick_params(axis="y", length=0)
    for side in ("top", "right", "left"):
        ax.spines[side].set_visible(False)

    _draw_pretty_brackets(ax, spans, row_count)
    _pretty_legend(ax, _pretty_present_roles(schedule), drew_remote)

    if show:
        plt.show()
    return ax


def _render_pretty_op_rows(
    schedule: OperationSchedule,
    *,
    ax: Axes | None,
    title: str | None,
    show: bool,
) -> Axes:
    """Render the publication variant with one row per scheduled event."""
    ops = list(schedule.operations)
    row_count = len(ops)
    y_positions = [float(row_count - 1 - index) for index in range(row_count)]

    if ax is None:
        figure_width = min(
            _MAX_AUTO_FIGURE_WIDTH, max(9.0, schedule.makespan * 0.42 + 3.6)
        )
        figure_height = max(3.6, row_count * 0.42 + 2.4)
        fig, ax = plt.subplots(figsize=(figure_width, figure_height))
        fig.subplots_adjust(
            left=min(0.32, 2.4 / figure_width),
            right=0.985,
            top=1.0 - min(0.14, 0.62 / figure_height),
            bottom=min(0.18, 1.0 / figure_height),
        )

    for op, y in zip(ops, y_positions, strict=True):
        role = _pretty_role(op)
        face, edge, hatch, text_color = _PRETTY_ROLE_VISUAL[role]
        ax.add_patch(
            Rectangle(
                (op.start_time, y - _PRETTY_BAR_HEIGHT / 2),
                op.duration,
                _PRETTY_BAR_HEIGHT,
                facecolor=face,
                edgecolor=edge,
                hatch=hatch,
                linewidth=1.0,
                zorder=2,
            )
        )
        label = _pretty_event_text(op)
        if label and op.duration > 0:
            _draw_pretty_label(
                ax, op.start_time + op.duration / 2.0, y, label, text_color
            )

    ax.set_yticks(
        y_positions,
        [
            f"{index}: {_pretty_event_text(op)}"
            for index, op in enumerate(ops, start=1)
        ],
    )
    ax.set_ylim(-0.7, row_count - 0.3)
    _configure_pretty_xaxis(ax, schedule)
    ax.set_ylabel("OPERATION", labelpad=8.0)
    ax.tick_params(axis="y", length=0)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)

    _pretty_legend(ax, _pretty_present_roles(schedule), False)

    if show:
        plt.show()
    return ax
