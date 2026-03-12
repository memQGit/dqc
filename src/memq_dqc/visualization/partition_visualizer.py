"""SVG-based partition visualization helpers."""

from __future__ import annotations

from typing import TYPE_CHECKING

from memq_dqc.visualization.svg_document import SvgCanvas, SvgDocument

if TYPE_CHECKING:
    from memq_dqc.partition.partitioner import QPU

PartitionTimeline = list[dict["QPU", set[int]]]

__all__ = ["plot_partition_heatmap", "plot_migration_timeline"]

_COLOR_SCHEME = ["#4801b0", "#d702fe", "#6a4cff", "#1e293b", "#38bdf8"]
_TEXT_COLOR = "#102a43"
_MUTED_TEXT = "#52606d"


def plot_partition_heatmap(
    partition: PartitionTimeline,
    *,
    title: str | None = None,
    top_k_most_moved: int | None = None,
    sample_stride: int | None = None,
    sort_by_final_qpu: bool = False,
    x_tick_stride: int | None = 5,
    x_tick_rotation: float = 0.0,
    y_tick_fontsize: int = 8,
    ax: object | None = None,
    cmap: str = "tab20",
    show: bool = False,
) -> SvgDocument:
    """Render a qubit-vs-window partition heatmap as SVG.

    Args:
        partition: Timeline of partitions (window -> QPU -> qubit set).
        title: Optional chart title.
        top_k_most_moved: If provided, keep only the qubits that moved most
            often across windows.
        sample_stride: If provided, keep every Nth qubit after filtering.
        sort_by_final_qpu: Whether to group rows by the final window QPU.
        x_tick_stride: Window tick spacing. If None, show every window.
        x_tick_rotation: Ignored legacy parameter retained for compatibility.
        y_tick_fontsize: Font size for y-axis labels.
        ax: Ignored legacy parameter retained for compatibility.
        cmap: Ignored legacy parameter retained for compatibility.
        show: Ignored legacy parameter retained for compatibility.

    Returns:
        An SVG document containing the heatmap.
    """
    del ax, cmap, show, x_tick_rotation

    assignments, num_qpus = _assignments_and_qpu_count(partition)
    qubits = _collect_qubits(assignments)
    qubit_order = _order_qubits(
        qubits,
        assignments,
        top_k_most_moved=top_k_most_moved,
        sample_stride=sample_stride,
        sort_by_final_qpu=sort_by_final_qpu,
    )
    header_visible = title != ""
    resolved_title = "Partition Heatmap" if title is None else title

    cell_width = 10.0 if len(assignments) > 80 else 16.0
    cell_height = 10.0 if len(qubit_order) > 50 else 14.0
    left = 54.0
    top = 104.0 if header_visible else 78.0
    right = 18.0
    bottom = 36.0
    legend_height = 34.0
    base_width = left + right + len(assignments) * cell_width
    width = int(max(base_width, 420.0))
    height = int(top + bottom + len(qubit_order) * cell_height + legend_height)
    canvas = SvgCanvas(width=width, height=height, background="#ffffff")

    if header_visible:
        _draw_title(
            canvas,
            width=width,
            title=resolved_title,
            subtitle=(
                "QPU assignment of each logical qubit across partition windows"
            ),
        )
    _draw_heatmap_legend(
        canvas,
        num_qpus=num_qpus,
        x=left,
        y=16.0 if not header_visible else 72.0,
    )

    for row_index, qubit in enumerate(qubit_order):
        y = top + row_index * cell_height
        if row_index % 2 == 0:
            canvas.rect(
                x=left,
                y=y,
                width=len(assignments) * cell_width,
                height=cell_height,
                fill="#f8fafc",
                opacity=0.9,
            )
        canvas.text(
            x=left - 10.0,
            y=y + cell_height * 0.72,
            text=str(qubit),
            fill=_TEXT_COLOR,
            font_size=float(y_tick_fontsize),
            anchor="end",
        )
        for col_index, assignment in enumerate(assignments):
            value = assignment.get(qubit)
            fill = "#e2e8f0" if value is None else _qpu_color(value)
            canvas.rect(
                x=left + col_index * cell_width,
                y=y,
                width=cell_width,
                height=cell_height,
                fill=fill,
                stroke="#ffffff",
                stroke_width=0.5,
            )

    if x_tick_stride is None:
        x_tick_stride = 1
    for window_index in range(0, len(assignments), max(1, x_tick_stride)):
        x = left + window_index * cell_width + cell_width / 2
        canvas.text(
            x=x,
            y=height - 18.0,
            text=str(window_index),
            fill=_MUTED_TEXT,
            font_size=10.0,
            anchor="middle",
        )

    canvas.text(
        x=width / 2,
        y=height - 4.0,
        text="Partition window",
        fill=_MUTED_TEXT,
        font_size=12.0,
        anchor="middle",
    )
    canvas.text(
        x=16.0,
        y=height / 2,
        text="Logical qubit",
        fill=_MUTED_TEXT,
        font_size=12.0,
    )
    return canvas.to_document()


def plot_migration_timeline(
    partition: PartitionTimeline,
    *,
    title: str | None = None,
    window_entanglement_cost: list[float] | None = None,
    ax: object | None = None,
    show: bool = False,
) -> SvgDocument:
    """Render moved-qubits-per-window as an SVG line chart.

    Args:
        partition: Timeline of partitions (window -> QPU -> qubit set).
        title: Optional chart title.
        window_entanglement_cost: Optional series to plot on a secondary axis.
        ax: Ignored legacy parameter retained for compatibility.
        show: Ignored legacy parameter retained for compatibility.

    Returns:
        An SVG document containing the migration timeline.
    """
    del ax, show

    assignments, _ = _assignments_and_qpu_count(partition)
    movement = _movement_counts(assignments)
    window_indices = list(range(1, len(assignments)))
    if window_entanglement_cost is not None and len(
        window_entanglement_cost
    ) != len(movement):
        raise ValueError(
            "window_entanglement_cost must match number of transitions."
        )
    header_visible = title != ""
    resolved_title = "Migration Timeline" if title is None else title

    top = 102.0 if header_visible else 74.0
    left = 50.0
    right = 44.0 if window_entanglement_cost is not None else 18.0
    bottom = 36.0
    chart_height = 228.0
    window_step = 18.0 if len(window_indices) > 60 else 24.0
    base_width = (
        left + right + max(1, len(window_indices) - 1) * window_step + 20.0
    )
    width = int(max(base_width, 420.0))
    height = int(top + bottom + chart_height)
    canvas = SvgCanvas(width=width, height=height, background="#ffffff")

    if header_visible:
        _draw_title(
            canvas,
            width=width,
            title=resolved_title,
            subtitle="Moved logical qubits across adjacent partition windows",
        )

    max_primary = max(movement, default=0)
    max_secondary = max(window_entanglement_cost or [0.0], default=0.0)
    chart_bottom = top + chart_height
    for tick in range(5):
        y = chart_bottom - chart_height * tick / 4
        canvas.line(
            x1=left,
            y1=y,
            x2=width - right,
            y2=y,
            stroke="#eef2f7",
            stroke_width=1.0,
        )
        canvas.text(
            x=left - 8.0,
            y=y + 4.0,
            text=f"{max_primary * tick / 4:.0f}",
            fill=_MUTED_TEXT,
            font_size=10.0,
            anchor="end",
        )
        if window_entanglement_cost is not None:
            canvas.text(
                x=width - right + 8.0,
                y=y + 4.0,
                text=f"{max_secondary * tick / 4:.1f}",
                fill=_MUTED_TEXT,
                font_size=10.0,
                anchor="start",
            )

    if movement:
        points = []
        for offset, value in enumerate(movement):
            x = left + offset * window_step
            y = chart_bottom - chart_height * value / max(1, max_primary)
            points.append((x, y))
        _draw_polyline(canvas, points, stroke="#4801b0", stroke_width=2.0)
        for x, y in points:
            canvas.circle(cx=x, cy=y, r=3.0, fill="#4801b0")

    if window_entanglement_cost is not None and window_entanglement_cost:
        points = []
        for offset, value in enumerate(window_entanglement_cost):
            x = left + offset * window_step
            y = chart_bottom - chart_height * value / max(1.0, max_secondary)
            points.append((x, y))
        _draw_polyline(canvas, points, stroke="#d702fe", stroke_width=1.8)
        for x, y in points:
            canvas.circle(cx=x, cy=y, r=2.4, fill="#d702fe")

    for offset, window_index in enumerate(window_indices):
        if (
            len(window_indices) <= 12
            or offset % max(1, len(window_indices) // 10) == 0
        ):
            x = left + offset * window_step
            canvas.text(
                x=x,
                y=height - 18.0,
                text=str(window_index),
                fill=_MUTED_TEXT,
                font_size=10.0,
                anchor="middle",
            )

    canvas.text(
        x=width / 2,
        y=height - 4.0,
        text="Window transition",
        fill=_MUTED_TEXT,
        font_size=12.0,
        anchor="middle",
    )
    return canvas.to_document()


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
        if {qpu.id for qpu in window} != qpu_ids:
            raise ValueError("All windows must use the same QPU identifiers")
        mapping: dict[int, int] = {}
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
        qubits.update(mapping)
    return sorted(qubits)


def _movement_counts(assignments: list[dict[int, int]]) -> list[int]:
    movement: list[int] = []
    for idx in range(1, len(assignments)):
        prev = assignments[idx - 1]
        curr = assignments[idx]
        all_qubits = set(prev) | set(curr)
        movement.append(
            sum(
                1 for qubit in all_qubits if prev.get(qubit) != curr.get(qubit)
            )
        )
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
        order.sort(key=lambda qubit: (final_assignment.get(qubit, -1), qubit))
    if sample_stride is not None and sample_stride > 1:
        order = order[::sample_stride]
    return order


def _qubit_movement_counts(
    qubits: list[int],
    assignments: list[dict[int, int]],
) -> list[tuple[int, int]]:
    counts: list[tuple[int, int]] = []
    for qubit in qubits:
        moved = 0
        previous = assignments[0].get(qubit)
        for assignment in assignments[1:]:
            current = assignment.get(qubit)
            if current != previous:
                moved += 1
            previous = current
        counts.append((qubit, moved))
    return counts


def _draw_title(
    canvas: SvgCanvas,
    *,
    width: int,
    title: str,
    subtitle: str,
) -> None:
    canvas.text(
        x=width / 2,
        y=40.0,
        text=title,
        fill=_TEXT_COLOR,
        font_size=24.0,
        font_weight="600",
        anchor="middle",
    )
    canvas.text(
        x=width / 2,
        y=64.0,
        text=subtitle,
        fill=_MUTED_TEXT,
        font_size=12.0,
        anchor="middle",
    )


def _draw_heatmap_legend(
    canvas: SvgCanvas,
    *,
    num_qpus: int,
    x: float,
    y: float,
) -> None:
    width = num_qpus * 70.0 + 18.0
    canvas.rect(
        x=x - 10.0,
        y=y - 10.0,
        width=width,
        height=34.0,
        fill="#ffffff",
        stroke="#d8deea",
        stroke_width=0.9,
        opacity=0.96,
        rx=9.0,
    )
    current_x = x
    for qpu_id in range(num_qpus):
        canvas.rect(
            x=current_x,
            y=y,
            width=14.0,
            height=14.0,
            fill=_qpu_color(qpu_id),
            stroke="none",
            rx=2.0,
        )
        canvas.text(
            x=current_x + 22.0,
            y=y + 11.0,
            text=f"QPU {qpu_id}",
            fill=_TEXT_COLOR,
            font_size=11.0,
        )
        current_x += 74.0


def _draw_polyline(
    canvas: SvgCanvas,
    points: list[tuple[float, float]],
    *,
    stroke: str,
    stroke_width: float,
) -> None:
    if not points:
        return
    commands = [f"M {points[0][0]:.2f} {points[0][1]:.2f}"]
    commands.extend(f"L {x:.2f} {y:.2f}" for x, y in points[1:])
    canvas.path(
        d=" ".join(commands),
        stroke=stroke,
        stroke_width=stroke_width,
    )


def _qpu_color(qpu_id: int) -> str:
    return _COLOR_SCHEME[qpu_id % len(_COLOR_SCHEME)]
