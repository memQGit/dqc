"""SVG-based visualization helpers for distributed compilation artifacts."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import TYPE_CHECKING

from memq_dqc.builder import synthesize_state_teleportation_swaps
from memq_dqc.circuit.dag import CircuitDAG
from memq_dqc.preprocessing.qasm import (
    CleanedClassicalDeclaration,
    CleanedQuantumMeasurementStatement,
)
from memq_dqc.utils.common import qubit_partition_map
from memq_dqc.visualization.svg_document import SvgCanvas, SvgDocument

if TYPE_CHECKING:
    from memq_dqc.circuit import Circuit, Op
    from memq_dqc.partition.partitioner import (
        QPU,
        PartitionSchedule,
        PartitionWindows,
    )


_LOCAL_GATE_FILL = "#f8fbff"
_LOCAL_GATE_STROKE = "#6b7a90"
_REMOTE_GATE_FILL = "#faedff"
_REMOTE_GATE_STROKE = "#d702fe"
_MEASURE_GATE_FILL = "#e6fffa"
_MEASURE_GATE_STROKE = "#0f766e"
_SWAP_GATE_FILL = "#fff4db"
_SWAP_GATE_STROKE = "#b7791f"
_WIRE_STROKE = "#d3dae6"
_SEPARATOR_STROKE = "#4801b0"
_WINDOW_FILL = "#f8f5ff"
_TELEPORT_STROKE = "#4801b0"
_TEXT_COLOR = "#102a43"
_MUTED_TEXT = "#52606d"
_QPU_COLORS = ["#4801b0", "#d702fe", "#3a86ff", "#7c3aed", "#06b6d4"]
_CIRCUIT_LEGEND_WIDTH = 268.0
_REMOTE_GATE_NAMES = {
    "cx": "rcx",
    "cp": "rcp",
    "cry": "rcry",
    "cz": "rcz",
    "swap": "rswap",
}


@dataclass(frozen=True, slots=True)
class _SlotLayout:
    """Physical-slot row layout for QPU groups."""

    qpu_ids: tuple[int, ...]
    group_sizes: tuple[int, ...]
    y_by_position: dict[tuple[int, int], float]
    slot_labels: tuple[tuple[int, int, float], ...]
    group_labels: tuple[tuple[int, float], ...]
    separator_y: tuple[float, ...]
    total_height: float


@dataclass(frozen=True, slots=True)
class _SelectedWindow:
    """Visible window slice for rendering."""

    window_index: int
    ops: tuple[Op, ...]
    omitted_ops: int


@dataclass(frozen=True, slots=True)
class _ClassicalLayout:
    """Rendered row layout for classical bits."""

    labels: tuple[tuple[str, float], ...]
    y_by_cbit: dict[tuple[str, int], float]
    group_center_y: float
    wire_gap: float
    total_height: float


@dataclass(frozen=True, slots=True)
class _MeasurementArrow:
    """Connection from a measurement gate to a classical bit."""

    x: float
    start_y: float
    cbit_key: tuple[str, int]


@dataclass(frozen=True, slots=True)
class _GanttTask:
    """One rendered operation row in the Gantt chart."""

    time_index: int
    window_index: int
    op: Op
    is_remote: bool
    slot_positions: tuple[tuple[int, int], ...]


def plot_distributed_circuit(
    circuit: Circuit,
    *,
    schedule: PartitionSchedule | None = None,
    windows: PartitionWindows | None = None,
    start_window: int = 0,
    max_windows: int | None = None,
    max_ops_per_window: int | None = None,
    title: str | None = None,
    ax: object | None = None,
    show: bool = False,
) -> SvgDocument:
    """Render a distributed circuit view as SVG.

    Wires represent QPU-local physical slots rather than global logical-qubit
    indices. Slot labels restart from zero inside each QPU group, and QPU
    boundaries are separated by dotted rules. Remote gates use a red dashed
    variant of the local-gate style, while state teleportation swaps are shown
    as forward-leaning connectors between QPU groups. If the circuit declares
    classical bits, they are rendered as double-line wires beneath the quantum
    rows, with dotted measurement arrows from ``M_z`` boxes to their targets.

    Args:
        circuit: Circuit to render.
        schedule: Optional partition schedule used for QPU-aware placement.
        windows: Optional partition windows aligned with ``schedule``.
        start_window: First window to render.
        max_windows: Optional cap on the number of windows to render.
        max_ops_per_window: Optional cap on visible operations per window.
        title: Optional chart title.
        ax: Ignored legacy parameter retained for compatibility.
        show: Ignored legacy parameter retained for compatibility.

    Returns:
        An SVG document containing the circuit visualization.

    Raises:
        ValueError: If schedule and windows do not align or the selected
            window slice is empty.
    """
    del ax, show

    if (schedule is None) != (windows is None):
        raise ValueError("schedule and windows must be provided together.")

    if schedule is None or windows is None:
        windows = [list(circuit.mono.ops)]
        schedule = [_single_qpu_assignment(circuit.mono.ops)]

    if len(schedule) != len(windows):
        raise ValueError("schedule and windows must have the same length.")
    if not schedule:
        raise ValueError("schedule must contain at least one window.")

    selected_windows = _select_windows(
        windows,
        start_window=start_window,
        max_windows=max_windows,
        max_ops_per_window=max_ops_per_window,
    )
    if not selected_windows:
        raise ValueError("Selected window slice is empty.")

    slot_layout = _build_slot_layout(schedule)
    classical_bits = _extract_classical_bits(circuit)
    classical_layout = (
        _build_classical_layout(classical_bits) if classical_bits else None
    )
    positions_by_window = [
        _assignment_positions(window) for window in schedule
    ]
    swap_schedule = synthesize_state_teleportation_swaps(schedule)
    header_visible = title != ""
    resolved_title = "Distributed Circuit View" if title is None else title
    legend_y = 24.0 if header_visible else 12.0

    header_height = 110.0 if header_visible else 62.0
    left_margin = 138.0
    bottom_padding = 44.0
    classical_section_gap = 28.0 if classical_layout is not None else 0.0
    op_step = 42.0
    inter_window_gap = 78.0
    trailing_padding = 26.0
    gate_column_count = sum(
        len(window.ops) + int(window.omitted_ops > 0)
        for window in selected_windows
    )
    body_width = (
        gate_column_count * op_step
        + max(0, len(selected_windows) - 1) * inter_window_gap
        + 24.0
    )
    plot_right = left_margin + body_width
    width = int(max(plot_right + trailing_padding, 620.0))
    classical_height = (
        classical_layout.total_height if classical_layout is not None else 0.0
    )
    height = int(
        header_height
        + slot_layout.total_height
        + classical_section_gap
        + classical_height
        + bottom_padding
    )
    canvas = SvgCanvas(width=width, height=height, background="#fffdfc")
    classical_top = (
        header_height + slot_layout.total_height + classical_section_gap
    )
    background_height = (
        slot_layout.total_height
        + 18.0
        + classical_section_gap
        + classical_height
    )

    x_cursor = left_margin
    window_bounds: list[tuple[int, float, float]] = []
    op_centers: dict[tuple[int, int], float] = {}
    teleport_centers: dict[int, float] = {}
    measurement_arrows: list[_MeasurementArrow] = []
    for offset, selected in enumerate(selected_windows):
        window_start = x_cursor
        for op_offset, _ in enumerate(selected.ops):
            op_centers[(selected.window_index, op_offset)] = (
                x_cursor + op_step / 2
            )
            x_cursor += op_step
        if selected.omitted_ops > 0:
            x_cursor += op_step
        window_end = x_cursor
        window_bounds.append((selected.window_index, window_start, window_end))
        if offset < len(selected_windows) - 1:
            teleport_centers[selected.window_index] = (
                x_cursor + inter_window_gap / 2
            )
            x_cursor += inter_window_gap

    if header_visible:
        _draw_title(
            canvas,
            width=width,
            center_x=46.0,
            title=resolved_title,
            subtitle=_circuit_subtitle(
                selected_windows, windows, max_ops_per_window
            ),
            anchor="start",
        )
    _draw_circuit_legend(
        canvas,
        x=width - _CIRCUIT_LEGEND_WIDTH - 24.0,
        y=legend_y,
    )
    _draw_circuit_background(
        canvas,
        bounds=window_bounds,
        top=header_height - 20.0,
        height=background_height,
    )
    _draw_slot_labels(
        canvas,
        slot_layout,
        left_margin=left_margin,
        right=plot_right,
        top=header_height,
    )
    _draw_slot_wires(
        canvas,
        slot_layout,
        left=left_margin,
        right=plot_right,
        top=header_height,
    )
    if classical_layout is not None:
        _draw_quantum_classical_separator(
            canvas,
            left=left_margin - 10.0,
            right=plot_right,
            y=classical_top - classical_section_gap / 2,
        )
        _draw_classical_labels(
            canvas,
            classical_layout,
            left_margin=left_margin,
            top=classical_top,
        )
        _draw_classical_wires(
            canvas,
            classical_layout,
            left=left_margin,
            right=plot_right,
            top=classical_top,
        )
    _draw_window_headers(canvas, window_bounds, y=header_height - 28.0)

    for selected in selected_windows:
        window_positions = positions_by_window[selected.window_index]
        for op_offset, op in enumerate(selected.ops):
            x_center = op_centers[(selected.window_index, op_offset)]
            slot_positions = tuple(
                window_positions[q] for q in op.qubit_indices
            )
            y_positions = tuple(
                header_height + slot_layout.y_by_position[pos]
                for pos in slot_positions
            )
            qpu_ids = tuple(position[0] for position in slot_positions)
            is_remote = len(set(qpu_ids)) > 1
            _draw_gate(
                canvas,
                x_center=x_center,
                y_positions=y_positions,
                label=_gate_label(op.name, is_remote),
                is_remote=is_remote,
            )
            cbit_key = _measurement_cbit_key(circuit, op)
            if cbit_key is not None and classical_layout is not None:
                measurement_arrows.append(
                    _MeasurementArrow(
                        x=x_center,
                        start_y=y_positions[0] + 11.0,
                        cbit_key=cbit_key,
                    )
                )

        if selected.omitted_ops > 0:
            omitted_x = _omitted_ops_x(
                bounds=window_bounds,
                window_index=selected.window_index,
            )
            canvas.text(
                x=omitted_x,
                y=header_height - 6.0,
                text=f"+{selected.omitted_ops} ops",
                fill=_MUTED_TEXT,
                font_size=11.0,
                anchor="middle",
            )

    for selected_index in range(len(selected_windows) - 1):
        selected = selected_windows[selected_index]
        next_selected = selected_windows[selected_index + 1]
        boundary_index = selected.window_index
        center_x = teleport_centers[boundary_index]
        for swap in swap_schedule[boundary_index]:
            _draw_teleport_pair(
                canvas,
                center_x=center_x,
                start_y=header_height + slot_layout.y_by_position[swap.pos0],
                end_y=header_height + slot_layout.y_by_position[swap.pos1],
            )
            _draw_teleport_pair(
                canvas,
                center_x=center_x + 5.0,
                start_y=header_height + slot_layout.y_by_position[swap.pos1],
                end_y=header_height + slot_layout.y_by_position[swap.pos0],
            )
        del next_selected

    if classical_layout is not None:
        for arrow in measurement_arrows:
            target_y = (
                classical_top + classical_layout.y_by_cbit[arrow.cbit_key]
            )
            _draw_measurement_arrow(
                canvas,
                x=arrow.x,
                start_y=arrow.start_y,
                end_y=target_y,
            )

    return canvas.to_document()


def plot_partition_flow(
    schedule: PartitionSchedule,
    *,
    show_node_counts: bool | None = None,
    title: str | None = None,
    ax: object | None = None,
    show: bool = False,
) -> SvgDocument:
    """Render an alluvial-style partition flow view as SVG.

    Args:
        schedule: Timeline of partition assignments.
        show_node_counts: Whether occupancy labels should be drawn inside the
            QPU boxes. If omitted, labels appear only for shorter schedules.
        title: Optional chart title.
        ax: Ignored legacy parameter retained for compatibility.
        show: Ignored legacy parameter retained for compatibility.

    Returns:
        An SVG document containing the partition-flow visualization.
    """
    del ax, show

    assignments = _assignment_maps(schedule)
    qpu_ids = _sorted_qpu_ids(schedule)
    if show_node_counts is None:
        show_node_counts = len(schedule) <= 30
    header_visible = title != ""
    resolved_title = "Partition Flow" if title is None else title

    top = 102.0 if header_visible else 74.0
    left = 54.0
    right = 18.0
    bottom = 36.0
    lane_step = 72.0
    window_step = 16.0 if len(schedule) > 60 else 22.0
    base_width = left + right + (len(schedule) - 1) * window_step + 18.0
    width = int(max(base_width, 480.0))
    height = int(top + bottom + max(1, len(qpu_ids) - 1) * lane_step + 36.0)
    canvas = SvgCanvas(width=width, height=height, background="#ffffff")

    if header_visible:
        _draw_title(
            canvas,
            width=width,
            title=resolved_title,
            subtitle="QPU occupancy and migration between partition windows",
        )
    _draw_flow_legend(canvas, x=left, y=16.0 if not header_visible else 72.0)

    y_by_qpu = {
        qpu_id: top + idx * lane_step for idx, qpu_id in enumerate(qpu_ids)
    }
    for qpu_id, y in y_by_qpu.items():
        canvas.line(
            x1=left - 6.0,
            y1=y,
            x2=width - right,
            y2=y,
            stroke="#e5e7eb",
            stroke_width=1.0,
        )
        canvas.text(
            x=left - 20.0,
            y=y + 5.0,
            text=f"QPU {qpu_id}",
            fill=_TEXT_COLOR,
            font_size=12.0,
            anchor="end",
        )

    transition_counts = _transition_counts(assignments)
    for window_idx, flows in transition_counts.items():
        x0 = left + window_idx * window_step
        x1 = x0 + window_step
        for (src_qpu, dst_qpu), count in sorted(flows.items()):
            y0 = y_by_qpu[src_qpu]
            y1 = y_by_qpu[dst_qpu]
            canvas.path(
                d=(
                    f"M {x0:.2f} {y0:.2f} "
                    f"C {x0 + window_step * 0.35:.2f} {y0:.2f}, "
                    f"{x1 - window_step * 0.35:.2f} {y1:.2f}, "
                    f"{x1:.2f} {y1:.2f}"
                ),
                stroke=_qpu_color(src_qpu),
                stroke_width=0.9 + count * 0.65,
                opacity=0.18 if src_qpu == dst_qpu else 0.42,
            )

    for window_idx, window in enumerate(schedule):
        x = left + window_idx * window_step
        for qpu, qubits in sorted(window.items(), key=lambda item: item[0].id):
            y = y_by_qpu[qpu.id]
            canvas.rect(
                x=x - 6.0,
                y=y - 16.0,
                width=12.0,
                height=32.0,
                fill="#ffffff",
                stroke=_qpu_color(qpu.id),
                stroke_width=1.0,
                rx=4.5,
            )
            if show_node_counts:
                canvas.text(
                    x=x,
                    y=y + 4.0,
                    text=str(len(qubits)),
                    fill=_TEXT_COLOR,
                    font_size=9.0,
                    anchor="middle",
                )

    return canvas.to_document()


def plot_operation_gantt(
    circuit: Circuit,
    *,
    schedule: PartitionSchedule | None = None,
    windows: PartitionWindows | None = None,
    start_window: int = 0,
    max_windows: int | None = None,
    max_ops_per_window: int | None = None,
    title: str | None = None,
    ax: object | None = None,
    show: bool = False,
) -> SvgDocument:
    """Render an operation-level Gantt chart as SVG.

    Time progresses left-to-right in unit intervals, and every operation spans
    one interval. Operations that share a DAG layer occupy the same time slot
    and are stacked on separate rows so parallel work appears vertically
    aligned instead of serialized along the x-axis.

    Args:
        circuit: Circuit to render.
        schedule: Optional partition schedule used for QPU-aware placement.
        windows: Optional partition windows aligned with ``schedule``.
        start_window: First window to render.
        max_windows: Optional cap on the number of windows to render.
        max_ops_per_window: Optional cap on visible operations per window.
        title: Optional chart title.
        ax: Ignored legacy parameter retained for compatibility.
        show: Ignored legacy parameter retained for compatibility.

    Returns:
        An SVG document containing the Gantt visualization.

    Raises:
        ValueError: If schedule and windows do not align or the selected
            window slice is empty.
    """
    del ax, show

    if not hasattr(circuit, "mono"):
        raise ValueError(
            "plot_operation_gantt expects a Circuit plus aligned "
            "schedule/windows. Pass partitioner.circuit instead of "
            "partitioner.circuit.distributed."
        )

    if (schedule is None) != (windows is None):
        raise ValueError("schedule and windows must be provided together.")

    if schedule is None or windows is None:
        windows = [list(circuit.mono.ops)]
        schedule = [_single_qpu_assignment(circuit.mono.ops)]

    if len(schedule) != len(windows):
        raise ValueError("schedule and windows must have the same length.")
    if not schedule:
        raise ValueError("schedule must contain at least one window.")

    selected_windows = _select_windows(
        windows,
        start_window=start_window,
        max_windows=max_windows,
        max_ops_per_window=max_ops_per_window,
    )
    if not selected_windows:
        raise ValueError("Selected window slice is empty.")

    slot_layout = _build_slot_layout(schedule)
    positions_by_window = [
        _assignment_positions(window) for window in schedule
    ]
    remote_ops = _remote_op_ids(circuit, schedule, windows)
    header_visible = title != ""
    resolved_title = "Operation Gantt" if title is None else title
    legend_y = 24.0 if header_visible else 12.0

    header_height = 110.0 if header_visible else 62.0
    left_margin = 138.0
    right_padding = 28.0
    bottom_padding = 52.0
    bar_height = 18.0
    interval_width = 88.0
    axis_top = header_height - 6.0
    lane_top = header_height + 8.0

    tasks, window_time_bounds, total_intervals = _build_gantt_tasks(
        selected_windows,
        positions_by_window=positions_by_window,
        remote_ops=remote_ops,
    )
    plot_right = left_margin + max(1, total_intervals) * interval_width
    width = int(max(plot_right + right_padding, 760.0))
    height = int(header_height + slot_layout.total_height + bottom_padding)
    canvas = SvgCanvas(width=width, height=height, background="#fffdfc")

    if header_visible:
        _draw_title(
            canvas,
            width=width,
            center_x=46.0,
            title=resolved_title,
            subtitle=_circuit_subtitle(
                selected_windows,
                windows,
                max_ops_per_window,
            ),
            anchor="start",
        )
    _draw_gantt_legend(canvas, x=width - 252.0, y=legend_y)
    _draw_gantt_window_backgrounds(
        canvas,
        bounds=window_time_bounds,
        left_margin=left_margin,
        interval_width=interval_width,
        top=header_height - 18.0,
        height=slot_layout.total_height + 18.0,
    )
    _draw_slot_labels(
        canvas,
        slot_layout,
        left_margin=left_margin,
        right=plot_right,
        top=lane_top,
    )
    _draw_slot_wires(
        canvas,
        slot_layout,
        left=left_margin,
        right=plot_right,
        top=lane_top,
    )
    _draw_gantt_time_axis(
        canvas,
        total_intervals=total_intervals,
        left_margin=left_margin,
        interval_width=interval_width,
        top=axis_top,
        bottom=lane_top + slot_layout.total_height - 12.0,
        right=plot_right,
    )
    _draw_gantt_window_headers(
        canvas,
        bounds=window_time_bounds,
        left_margin=left_margin,
        interval_width=interval_width,
        y=header_height - 28.0,
    )

    for task in tasks:
        y_positions = tuple(
            lane_top + slot_layout.y_by_position[position]
            for position in task.slot_positions
        )
        _draw_gantt_operation(
            canvas,
            left=left_margin + task.time_index * interval_width + 10.0,
            right=left_margin + (task.time_index + 1) * interval_width - 10.0,
            y_positions=y_positions,
            label=_gate_label(task.op.name, task.is_remote),
            op_name=task.op.name,
            is_remote=task.is_remote,
            bar_height=bar_height,
        )

    for selected in selected_windows:
        if selected.omitted_ops > 0:
            omitted_x = _omitted_ops_x(
                bounds=[
                    (
                        window_index,
                        left_margin + start_time * interval_width,
                        left_margin + end_time * interval_width,
                    )
                    for window_index, start_time, end_time in window_time_bounds
                ],
                window_index=selected.window_index,
            )
            canvas.text(
                x=omitted_x,
                y=header_height - 6.0,
                text=f"+{selected.omitted_ops} ops",
                fill=_MUTED_TEXT,
                font_size=11.0,
                anchor="middle",
            )

    canvas.text(
        x=width / 2,
        y=height - 18.0,
        text="Time interval",
        fill=_MUTED_TEXT,
        font_size=12.0,
        anchor="middle",
    )

    return canvas.to_document()


def plot_window_activity(
    circuit: Circuit,
    schedule: PartitionSchedule,
    windows: PartitionWindows,
    *,
    title: str | None = None,
    ax: object | None = None,
    show: bool = False,
) -> SvgDocument:
    """Render per-window gate composition and movement pressure as SVG.

    Args:
        circuit: Circuit providing the operation set.
        schedule: Partition schedule aligned with ``windows``.
        windows: Operation windows from the partitioner.
        title: Optional chart title.
        ax: Ignored legacy parameter retained for compatibility.
        show: Ignored legacy parameter retained for compatibility.

    Returns:
        An SVG document containing the window-activity summary.
    """
    del ax, show

    if len(schedule) != len(windows):
        raise ValueError("schedule and windows must have the same length.")
    if not schedule:
        raise ValueError("schedule must contain at least one window.")
    header_visible = title != ""
    resolved_title = "Window Activity" if title is None else title

    remote_ops = _remote_op_ids(circuit, schedule, windows)
    single_counts: list[int] = []
    local_two_counts: list[int] = []
    remote_two_counts: list[int] = []
    for window in windows:
        single_count = 0
        local_two_count = 0
        remote_two_count = 0
        for op in window:
            if len(op.qubits) == 1:
                single_count += 1
            elif op.op_id in remote_ops:
                remote_two_count += 1
            else:
                local_two_count += 1
        single_counts.append(single_count)
        local_two_counts.append(local_two_count)
        remote_two_counts.append(remote_two_count)

    movement = _movement_counts(_assignment_maps(schedule))
    max_ops = max(
        single + local + remote
        for single, local, remote in zip(
            single_counts,
            local_two_counts,
            remote_two_counts,
            strict=True,
        )
    )
    max_movement = max(movement, default=0)

    top = 110.0 if header_visible else 86.0
    left = 54.0
    right = 42.0
    bottom = 38.0
    chart_height = 246.0
    window_step = 14.0 if len(windows) > 80 else 22.0
    bar_width = max(5.0, min(18.0, window_step * 0.7))
    base_width = left + right + (len(windows) - 1) * window_step + 22.0
    width = int(max(base_width, 500.0))
    height = int(top + bottom + chart_height)
    canvas = SvgCanvas(width=width, height=height, background="#ffffff")

    if header_visible:
        _draw_title(
            canvas,
            width=width,
            title=resolved_title,
            subtitle="Stacked gate counts with movement pressure overlay",
        )
    _draw_activity_legend(
        canvas, x=left, y=16.0 if not header_visible else 72.0
    )

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
        value = max_ops * tick / 4
        canvas.text(
            x=left - 10.0,
            y=y + 4.0,
            text=f"{value:.0f}",
            fill=_MUTED_TEXT,
            font_size=10.0,
            anchor="end",
        )

    for window_idx in range(len(windows)):
        x = left + window_idx * window_step
        single_height = (
            chart_height * single_counts[window_idx] / max(1, max_ops)
        )
        local_height = (
            chart_height * local_two_counts[window_idx] / max(1, max_ops)
        )
        remote_height = (
            chart_height * remote_two_counts[window_idx] / max(1, max_ops)
        )
        current_top = chart_bottom
        for height_value, fill in (
            (single_height, "#dbeafe"),
            (local_height, "#c4b5fd"),
            (remote_height, "#d702fe"),
        ):
            if height_value <= 0:
                continue
            current_top -= height_value
            canvas.rect(
                x=x - bar_width / 2,
                y=current_top,
                width=bar_width,
                height=height_value,
                fill=fill,
                stroke="none",
                rx=2.0,
            )

    if movement:
        movement_points = []
        for offset, count in enumerate(movement, start=1):
            x = left + offset * window_step
            y = chart_bottom - chart_height * count / max(1, max_movement)
            movement_points.append((x, y))
        path_segments = [
            f"M {movement_points[0][0]:.2f} {movement_points[0][1]:.2f}"
        ]
        path_segments.extend(
            f"L {x:.2f} {y:.2f}" for x, y in movement_points[1:]
        )
        canvas.path(
            d=" ".join(path_segments),
            stroke="#4801b0",
            stroke_width=2.0,
        )
        for x, y in movement_points:
            canvas.circle(cx=x, cy=y, r=2.8, fill="#4801b0")
        for tick in range(5):
            y = chart_bottom - chart_height * tick / 4
            value = max_movement * tick / 4
            canvas.text(
                x=width - right + 10.0,
                y=y + 4.0,
                text=f"{value:.0f}",
                fill=_MUTED_TEXT,
                font_size=10.0,
                anchor="start",
            )

    canvas.text(
        x=width / 2,
        y=height - 18.0,
        text="Partition window",
        fill=_MUTED_TEXT,
        font_size=12.0,
        anchor="middle",
    )

    return canvas.to_document()


def _select_windows(
    windows: PartitionWindows,
    *,
    start_window: int,
    max_windows: int | None,
    max_ops_per_window: int | None,
) -> list[_SelectedWindow]:
    if start_window < 0 or start_window >= len(windows):
        raise ValueError("start_window is outside the available window range.")
    end_window = len(windows)
    if max_windows is not None:
        end_window = min(end_window, start_window + max_windows)

    selected: list[_SelectedWindow] = []
    for window_index in range(start_window, end_window):
        ops = windows[window_index]
        if max_ops_per_window is None:
            visible_ops = tuple(ops)
            omitted_ops = 0
        else:
            visible_ops = tuple(ops[:max_ops_per_window])
            omitted_ops = max(0, len(ops) - len(visible_ops))
        selected.append(
            _SelectedWindow(
                window_index=window_index,
                ops=visible_ops,
                omitted_ops=omitted_ops,
            )
        )
    return selected


def _build_slot_layout(schedule: PartitionSchedule) -> _SlotLayout:
    first_assignment = schedule[0]
    qpu_ids = tuple(sorted(qpu.id for qpu in first_assignment))
    group_sizes: dict[int, int] = {}
    for qpu_id in qpu_ids:
        group_sizes[qpu_id] = len(
            next(
                qubits
                for qpu, qubits in first_assignment.items()
                if qpu.id == qpu_id
            )
        )

    for assignment in schedule[1:]:
        current_sizes = {
            qpu.id: len(qubits) for qpu, qubits in assignment.items()
        }
        if tuple(sorted(current_sizes)) != qpu_ids:
            raise ValueError("All schedule windows must use the same QPU ids.")
        for qpu_id in qpu_ids:
            if current_sizes[qpu_id] != group_sizes[qpu_id]:
                raise ValueError(
                    "All schedule windows must preserve QPU slot counts."
                )

    row_step = 30.0
    group_gap = 16.0
    slot_labels: list[tuple[int, int, float]] = []
    group_labels: list[tuple[int, float]] = []
    separator_y: list[float] = []
    y_by_position: dict[tuple[int, int], float] = {}
    current_y = 0.0
    for index, qpu_id in enumerate(qpu_ids):
        group_size = group_sizes[qpu_id]
        start_y = current_y
        for slot_idx in range(group_size):
            y = current_y + slot_idx * row_step
            y_by_position[(qpu_id, slot_idx)] = y
            slot_labels.append((qpu_id, slot_idx, y))
        end_y = start_y + max(0, group_size - 1) * row_step
        group_labels.append((qpu_id, (start_y + end_y) / 2))
        current_y += group_size * row_step
        if index < len(qpu_ids) - 1:
            separator_y.append(current_y - row_step / 2 + group_gap / 2)
            current_y += group_gap

    total_height = current_y - row_step + 24.0
    return _SlotLayout(
        qpu_ids=qpu_ids,
        group_sizes=tuple(group_sizes[qpu_id] for qpu_id in qpu_ids),
        y_by_position=y_by_position,
        slot_labels=tuple(slot_labels),
        group_labels=tuple(group_labels),
        separator_y=tuple(separator_y),
        total_height=total_height,
    )


def _extract_classical_bits(
    circuit: Circuit,
) -> tuple[tuple[str, int], ...]:
    declared_bits: list[tuple[str, int]] = []
    for statement in circuit.mono.statements:
        if isinstance(statement, CleanedClassicalDeclaration):
            declared_bits.extend(
                (statement.name, index) for index in range(statement.size)
            )
    if declared_bits:
        return tuple(declared_bits)

    measured_bits: list[tuple[str, int]] = []
    seen: set[tuple[str, int]] = set()
    for statement in circuit.mono.statements:
        if not isinstance(statement, CleanedQuantumMeasurementStatement):
            continue
        if statement.cbit is None:
            continue
        key = (statement.cbit.register_name, statement.cbit.index)
        if key in seen:
            continue
        seen.add(key)
        measured_bits.append(key)
    return tuple(measured_bits)


def _build_classical_layout(
    classical_bits: tuple[tuple[str, int], ...],
) -> _ClassicalLayout:
    row_step = 22.0
    wire_gap = 5.0
    labels: list[tuple[str, float]] = []
    y_by_cbit: dict[tuple[str, int], float] = {}
    current_y = 0.0
    for register_name, index in classical_bits:
        labels.append((f"{register_name}[{index}]", current_y))
        y_by_cbit[(register_name, index)] = current_y
        current_y += row_step

    if labels:
        group_center_y = labels[-1][1] / 2
        total_height = labels[-1][1] + 18.0
    else:
        group_center_y = 0.0
        total_height = 0.0

    return _ClassicalLayout(
        labels=tuple(labels),
        y_by_cbit=y_by_cbit,
        group_center_y=group_center_y,
        wire_gap=wire_gap,
        total_height=total_height,
    )


def _draw_title(
    canvas: SvgCanvas,
    *,
    width: int,
    center_x: float | None = None,
    title: str,
    subtitle: str,
    anchor: str = "middle",
) -> None:
    x = width / 2 if center_x is None else center_x
    canvas.text(
        x=x,
        y=40.0,
        text=title,
        fill=_TEXT_COLOR,
        font_size=26.0,
        font_weight="600",
        anchor=anchor,
    )
    canvas.text(
        x=x,
        y=64.0,
        text=subtitle,
        fill=_MUTED_TEXT,
        font_size=12.0,
        anchor=anchor,
    )


def _draw_circuit_legend(canvas: SvgCanvas, *, x: float, y: float) -> None:
    canvas.rect(
        x=x,
        y=y,
        width=_CIRCUIT_LEGEND_WIDTH,
        height=52.0,
        fill="#ffffff",
        stroke="#d8deea",
        stroke_width=0.9,
        opacity=0.96,
        rx=10.0,
    )
    canvas.rect(
        x=x + 12.0,
        y=y + 10.0,
        width=16.0,
        height=10.0,
        fill=_LOCAL_GATE_FILL,
        stroke=_LOCAL_GATE_STROKE,
        stroke_width=0.9,
        rx=3.0,
    )
    canvas.text(
        x=x + 36.0,
        y=y + 18.0,
        text="Local gate",
        fill=_TEXT_COLOR,
        font_size=10.0,
    )
    canvas.rect(
        x=x + 112.0,
        y=y + 10.0,
        width=16.0,
        height=10.0,
        fill=_REMOTE_GATE_FILL,
        stroke=_REMOTE_GATE_STROKE,
        stroke_width=0.9,
        rx=3.0,
    )
    canvas.text(
        x=x + 136.0,
        y=y + 18.0,
        text="Remote gate",
        fill=_TEXT_COLOR,
        font_size=10.0,
    )
    canvas.path(
        d=f"M {x + 12:.2f} {y + 34:.2f} C {x + 20:.2f} {y + 30:.2f}, "
        f"{x + 28:.2f} {y + 40:.2f}, {x + 38:.2f} {y + 34:.2f}",
        stroke=_TELEPORT_STROKE,
        stroke_width=1.7,
    )
    canvas.circle(cx=x + 12.0, cy=y + 34.0, r=2.2, fill=_TELEPORT_STROKE)
    canvas.circle(cx=x + 38.0, cy=y + 34.0, r=2.2, fill=_TELEPORT_STROKE)
    canvas.text(
        x=x + 48.0,
        y=y + 38.0,
        text="State teleportation",
        fill=_TEXT_COLOR,
        font_size=10.0,
    )
    canvas.line(
        x1=x + 166.0,
        y1=y + 31.5,
        x2=x + 192.0,
        y2=y + 31.5,
        stroke=_LOCAL_GATE_STROKE,
        stroke_width=1.0,
    )
    canvas.line(
        x1=x + 166.0,
        y1=y + 36.5,
        x2=x + 192.0,
        y2=y + 36.5,
        stroke=_LOCAL_GATE_STROKE,
        stroke_width=1.0,
    )
    canvas.text(
        x=x + 202.0,
        y=y + 38.0,
        text="CBIT",
        fill=_TEXT_COLOR,
        font_size=10.0,
    )


def _draw_flow_legend(canvas: SvgCanvas, *, x: float, y: float) -> None:
    canvas.rect(
        x=x,
        y=y,
        width=198.0,
        height=40.0,
        fill="#ffffff",
        stroke="#d8deea",
        stroke_width=0.9,
        rx=9.0,
    )
    canvas.line(
        x1=x + 12.0,
        y1=y + 15.0,
        x2=x + 34.0,
        y2=y + 15.0,
        stroke="#4801b0",
        stroke_width=3.0,
        opacity=0.3,
    )
    canvas.text(
        x=x + 44.0,
        y=y + 19.0,
        text="Migrating qubits",
        fill=_TEXT_COLOR,
        font_size=11.0,
    )
    canvas.rect(
        x=x + 12.0,
        y=y + 22.0,
        width=18.0,
        height=10.0,
        fill="#ffffff",
        stroke="#6b7a90",
        stroke_width=0.9,
        rx=3.0,
    )
    canvas.text(
        x=x + 44.0,
        y=y + 31.0,
        text="QPU occupancy",
        fill=_TEXT_COLOR,
        font_size=11.0,
    )


def _draw_activity_legend(canvas: SvgCanvas, *, x: float, y: float) -> None:
    legend_items = (
        ("Single-qubit / measure", "#dbeafe", x, y),
        ("Local 2-qubit", "#c4b5fd", x + 120.0, y),
        ("Remote 2-qubit", "#d702fe", x, y + 22.0),
    )
    for label, fill, item_x, item_y in legend_items:
        canvas.rect(
            x=item_x,
            y=item_y,
            width=14.0,
            height=14.0,
            fill=fill,
            stroke="none",
            rx=2.0,
        )
        canvas.text(
            x=item_x + 22.0,
            y=item_y + 11.0,
            text=label,
            fill=_TEXT_COLOR,
            font_size=11.0,
        )
    line_y = y + 29.0
    canvas.line(
        x1=x + 152.0,
        y1=line_y,
        x2=x + 172.0,
        y2=line_y,
        stroke="#4801b0",
        stroke_width=2.0,
    )
    canvas.circle(cx=x + 162.0, cy=line_y, r=2.6, fill="#4801b0")
    canvas.text(
        x=x + 180.0,
        y=line_y + 4.0,
        text="Moved qubits",
        fill=_TEXT_COLOR,
        font_size=11.0,
    )


def _draw_gantt_legend(canvas: SvgCanvas, *, x: float, y: float) -> None:
    canvas.rect(
        x=x,
        y=y,
        width=228.0,
        height=52.0,
        fill="#ffffff",
        stroke="#d8deea",
        stroke_width=0.9,
        opacity=0.96,
        rx=10.0,
    )
    legend_items = (
        ("Local op", _LOCAL_GATE_FILL, _LOCAL_GATE_STROKE, x + 12.0, y + 10.0),
        (
            "Remote op",
            _REMOTE_GATE_FILL,
            _REMOTE_GATE_STROKE,
            x + 118.0,
            y + 10.0,
        ),
        (
            "Measure",
            _MEASURE_GATE_FILL,
            _MEASURE_GATE_STROKE,
            x + 12.0,
            y + 30.0,
        ),
        ("Swap", _SWAP_GATE_FILL, _SWAP_GATE_STROKE, x + 118.0, y + 30.0),
    )
    for label, fill, stroke, item_x, item_y in legend_items:
        canvas.rect(
            x=item_x,
            y=item_y,
            width=16.0,
            height=10.0,
            fill=fill,
            stroke=stroke,
            stroke_width=0.9,
            rx=3.0,
        )
        canvas.text(
            x=item_x + 24.0,
            y=item_y + 8.0,
            text=label,
            fill=_TEXT_COLOR,
            font_size=10.0,
        )


def _build_gantt_tasks(
    selected_windows: list[_SelectedWindow],
    *,
    positions_by_window: list[dict[int, tuple[int, int]]],
    remote_ops: set[int],
) -> tuple[list[_GanttTask], list[tuple[int, int, int]], int]:
    """Build physical-slot tasks and time bounds for the Gantt chart."""
    tasks: list[_GanttTask] = []
    window_bounds: list[tuple[int, int, int]] = []
    time_index = 0

    for selected in selected_windows:
        local_layers = CircuitDAG(list(selected.ops)).layers
        window_positions = positions_by_window[selected.window_index]
        window_start = time_index
        for local_layer in local_layers:
            for op in local_layer:
                tasks.append(
                    _GanttTask(
                        time_index=time_index,
                        window_index=selected.window_index,
                        op=op,
                        is_remote=op.op_id in remote_ops,
                        slot_positions=tuple(
                            window_positions[qubit]
                            for qubit in op.qubit_indices
                        ),
                    )
                )
            time_index += 1
        window_end = (
            time_index if time_index > window_start else time_index + 1
        )
        window_bounds.append((selected.window_index, window_start, window_end))
        if time_index == window_start:
            time_index += 1

    return tasks, window_bounds, max(1, time_index)


def _draw_gantt_window_backgrounds(
    canvas: SvgCanvas,
    *,
    bounds: list[tuple[int, int, int]],
    left_margin: float,
    interval_width: float,
    top: float,
    height: float,
) -> None:
    for window_index, start_time, end_time in bounds:
        del window_index
        canvas.rect(
            x=left_margin + start_time * interval_width + 4.0,
            y=top,
            width=max(12.0, (end_time - start_time) * interval_width - 8.0),
            height=height,
            fill=_WINDOW_FILL,
            stroke="none",
            opacity=0.58,
            rx=10.0,
        )


def _draw_gantt_time_axis(
    canvas: SvgCanvas,
    *,
    total_intervals: int,
    left_margin: float,
    interval_width: float,
    top: float,
    bottom: float,
    right: float,
) -> None:
    for interval in range(total_intervals + 1):
        x = left_margin + interval * interval_width
        canvas.line(
            x1=x,
            y1=top,
            x2=x,
            y2=bottom,
            stroke="#e3e8f3",
            stroke_width=1.0,
        )
        if interval < total_intervals:
            canvas.text(
                x=x + interval_width / 2,
                y=top - 10.0,
                text=f"t{interval}",
                fill=_MUTED_TEXT,
                font_size=11.0,
                anchor="middle",
            )
    canvas.line(
        x1=left_margin,
        y1=bottom,
        x2=right,
        y2=bottom,
        stroke="#c9d3e3",
        stroke_width=1.1,
    )


def _draw_gantt_window_headers(
    canvas: SvgCanvas,
    bounds: list[tuple[int, int, int]],
    *,
    left_margin: float,
    interval_width: float,
    y: float,
) -> None:
    for window_index, start_time, end_time in bounds:
        canvas.text(
            x=left_margin + (start_time + end_time) * interval_width / 2,
            y=y,
            text=f"W{window_index}",
            fill=_MUTED_TEXT,
            font_size=12.0,
            font_weight="600",
            anchor="middle",
        )


def _gantt_row_label(op: Op, window_index: int) -> str:
    """Format the left-hand row label for a Gantt operation."""
    qubits = ", ".join(_op_qubit_label(qubit) for qubit in op.qubits)
    return f"W{window_index}  #{op.op_id}  {op.name} {qubits}".strip()


def _draw_quantum_classical_separator(
    canvas: SvgCanvas,
    *,
    left: float,
    right: float,
    y: float,
) -> None:
    canvas.line(
        x1=left,
        y1=y,
        x2=right,
        y2=y,
        stroke=_SEPARATOR_STROKE,
        stroke_width=1.1,
        opacity=0.36,
        dasharray="5 6",
    )


def _draw_circuit_background(
    canvas: SvgCanvas,
    *,
    bounds: list[tuple[int, float, float]],
    top: float,
    height: float,
) -> None:
    for window_index, left, right in bounds:
        del window_index
        canvas.rect(
            x=left - 10.0,
            y=top,
            width=right - left + 20.0,
            height=height,
            fill=_WINDOW_FILL,
            stroke="none",
            opacity=0.58,
            rx=10.0,
        )


def _draw_slot_labels(
    canvas: SvgCanvas,
    slot_layout: _SlotLayout,
    *,
    left_margin: float,
    right: float,
    top: float,
) -> None:
    for qpu_id, center_y in slot_layout.group_labels:
        canvas.text(
            x=44.0,
            y=top + center_y + 5.0,
            text=f"QPU {qpu_id}",
            fill=_TEXT_COLOR,
            font_size=13.0,
            font_weight="600",
        )
    for _, slot_idx, y in slot_layout.slot_labels:
        canvas.text(
            x=110.0,
            y=top + y + 5.0,
            text=str(slot_idx),
            fill=_MUTED_TEXT,
            font_size=11.0,
            anchor="end",
        )
    for y in slot_layout.separator_y:
        canvas.line(
            x1=left_margin - 82.0,
            y1=top + y,
            x2=right,
            y2=top + y,
            stroke=_SEPARATOR_STROKE,
            stroke_width=1.0,
            opacity=0.42,
            dasharray="2.5 7.5",
        )


def _draw_slot_wires(
    canvas: SvgCanvas,
    slot_layout: _SlotLayout,
    *,
    left: float,
    right: float,
    top: float,
) -> None:
    for _, slot_idx, y in slot_layout.slot_labels:
        del slot_idx
        canvas.line(
            x1=left,
            y1=top + y,
            x2=right,
            y2=top + y,
            stroke=_WIRE_STROKE,
            stroke_width=0.9,
        )


def _draw_classical_labels(
    canvas: SvgCanvas,
    classical_layout: _ClassicalLayout,
    *,
    left_margin: float,
    top: float,
) -> None:
    del left_margin
    canvas.text(
        x=22.0,
        y=top + classical_layout.group_center_y + 5.0,
        text="CBITS",
        fill=_TEXT_COLOR,
        font_size=12.0,
        font_weight="600",
    )
    for label, y in classical_layout.labels:
        canvas.text(
            x=122.0,
            y=top + y + 4.0,
            text=label,
            fill=_MUTED_TEXT,
            font_size=10.0,
            anchor="end",
        )


def _draw_classical_wires(
    canvas: SvgCanvas,
    classical_layout: _ClassicalLayout,
    *,
    left: float,
    right: float,
    top: float,
) -> None:
    half_gap = classical_layout.wire_gap / 2
    for _, center_y in classical_layout.labels:
        upper_y = top + center_y - half_gap
        lower_y = top + center_y + half_gap
        canvas.line(
            x1=left,
            y1=upper_y,
            x2=right,
            y2=upper_y,
            stroke=_LOCAL_GATE_STROKE,
            stroke_width=0.9,
        )
        canvas.line(
            x1=left,
            y1=lower_y,
            x2=right,
            y2=lower_y,
            stroke=_LOCAL_GATE_STROKE,
            stroke_width=0.9,
        )


def _draw_window_headers(
    canvas: SvgCanvas,
    bounds: list[tuple[int, float, float]],
    *,
    y: float,
) -> None:
    for window_index, left, right in bounds:
        canvas.text(
            x=(left + right) / 2,
            y=y,
            text=f"W{window_index}",
            fill=_MUTED_TEXT,
            font_size=12.0,
            font_weight="600",
            anchor="middle",
        )


def _draw_gate(
    canvas: SvgCanvas,
    *,
    x_center: float,
    y_positions: tuple[float, ...],
    label: str,
    is_remote: bool,
) -> None:
    fill = _REMOTE_GATE_FILL if is_remote else _LOCAL_GATE_FILL
    stroke = _REMOTE_GATE_STROKE if is_remote else _LOCAL_GATE_STROKE
    dasharray = "4 4" if is_remote else None

    if len(y_positions) == 1:
        y = y_positions[0]
        canvas.rect(
            x=x_center - 16.0,
            y=y - 11.0,
            width=32.0,
            height=22.0,
            fill=fill,
            stroke=stroke,
            stroke_width=1.0,
            rx=5.5,
        )
        _draw_gate_text(canvas, x=x_center, y=y + 4.0, label=label)
        return

    top_y = min(y_positions)
    bottom_y = max(y_positions)
    canvas.line(
        x1=x_center,
        y1=top_y,
        x2=x_center,
        y2=bottom_y,
        stroke=stroke,
        stroke_width=1.0,
        dasharray=dasharray,
    )
    for y in y_positions:
        canvas.circle(cx=x_center, cy=y, r=3.4, fill=stroke)
    canvas.rect(
        x=x_center - 18.0,
        y=(top_y + bottom_y) / 2 - 11.0,
        width=36.0,
        height=22.0,
        fill=fill,
        stroke=stroke,
        stroke_width=1.0,
        rx=5.5,
    )
    _draw_gate_text(
        canvas,
        x=x_center,
        y=(top_y + bottom_y) / 2 + 4.0,
        label=label,
    )


def _draw_teleport_pair(
    canvas: SvgCanvas,
    *,
    center_x: float,
    start_y: float,
    end_y: float,
) -> None:
    x0 = center_x - 10.0
    x1 = center_x + 14.0
    control_x = center_x + 2.0
    control_y = (start_y + end_y) / 2
    canvas.path(
        d=(
            f"M {x0:.2f} {start_y:.2f} "
            f"Q {control_x:.2f} {control_y:.2f} {x1:.2f} {end_y:.2f}"
        ),
        stroke=_TELEPORT_STROKE,
        stroke_width=1.7,
        opacity=0.92,
    )
    canvas.circle(cx=x0, cy=start_y, r=2.8, fill=_TELEPORT_STROKE)
    canvas.circle(cx=x1, cy=end_y, r=2.8, fill=_TELEPORT_STROKE)


def _draw_measurement_arrow(
    canvas: SvgCanvas,
    *,
    x: float,
    start_y: float,
    end_y: float,
) -> None:
    arrow_base_y = end_y - 7.0
    canvas.line(
        x1=x,
        y1=start_y,
        x2=x,
        y2=arrow_base_y,
        stroke=_TELEPORT_STROKE,
        stroke_width=1.0,
        dasharray="3 5",
    )
    canvas.path(
        d=(
            f"M {x - 4:.2f} {arrow_base_y - 0.5:.2f} "
            f"L {x:.2f} {end_y:.2f} "
            f"L {x + 4:.2f} {arrow_base_y - 0.5:.2f} Z"
        ),
        fill=_TELEPORT_STROKE,
    )


def _draw_gantt_operation(
    canvas: SvgCanvas,
    *,
    left: float,
    right: float,
    y_positions: tuple[float, ...],
    label: str,
    op_name: str,
    is_remote: bool,
    bar_height: float,
) -> None:
    fill, stroke, dasharray = _gantt_bar_style(op_name, is_remote)
    width = right - left
    center_x = (left + right) / 2
    half_height = bar_height / 2
    if len(y_positions) == 1:
        y = y_positions[0]
        canvas.rect(
            x=left,
            y=y - half_height,
            width=width,
            height=bar_height,
            fill=fill,
            stroke=stroke,
            stroke_width=1.0,
            dasharray=dasharray,
            rx=5.5,
        )
        _draw_gate_text(
            canvas,
            x=center_x,
            y=y + 4.0,
            label=label,
        )
        return

    top_y = min(y_positions)
    bottom_y = max(y_positions)
    canvas.line(
        x1=center_x,
        y1=top_y,
        x2=center_x,
        y2=bottom_y,
        stroke=stroke,
        stroke_width=1.0,
        dasharray=dasharray,
    )
    for y in y_positions:
        canvas.rect(
            x=left,
            y=y - half_height,
            width=width,
            height=bar_height,
            fill=fill,
            stroke=stroke,
            stroke_width=1.0,
            dasharray=dasharray,
            rx=5.5,
        )
    badge_width = min(42.0, width + 6.0)
    badge_y = (top_y + bottom_y) / 2
    canvas.rect(
        x=center_x - badge_width / 2,
        y=badge_y - 9.0,
        width=badge_width,
        height=18.0,
        fill=fill,
        stroke=stroke,
        stroke_width=1.0,
        dasharray=dasharray,
        rx=5.0,
    )
    _draw_gate_text(
        canvas,
        x=center_x,
        y=badge_y + 4.0,
        label=label,
    )


def _draw_gate_text(
    canvas: SvgCanvas,
    *,
    x: float,
    y: float,
    label: str,
) -> None:
    if label == "MEASURE":
        canvas.text_spans(
            x=x,
            y=y,
            spans=[
                ("M", None),
                (
                    "z",
                    {
                        "baseline_shift": "sub",
                        "font_size": "7.5",
                    },
                ),
            ],
            fill=_TEXT_COLOR,
            font_size=10.0,
            font_weight="600",
            anchor="middle",
        )
        return

    canvas.text(
        x=x,
        y=y,
        text=label,
        fill=_TEXT_COLOR,
        font_size=10.0,
        font_weight="600",
        anchor="middle",
    )


def _measurement_cbit_key(
    circuit: Circuit,
    op: Op,
) -> tuple[str, int] | None:
    statement = circuit.mono.statements[op.statement_id]
    if not isinstance(statement, CleanedQuantumMeasurementStatement):
        return None
    if statement.cbit is None:
        return None
    return (statement.cbit.register_name, statement.cbit.index)


def _gantt_bar_style(
    op_name: str,
    is_remote: bool,
) -> tuple[str, str, str | None]:
    if is_remote:
        return _REMOTE_GATE_FILL, _REMOTE_GATE_STROKE, "4 4"
    if op_name == "measure":
        return _MEASURE_GATE_FILL, _MEASURE_GATE_STROKE, None
    if op_name == "swap":
        return _SWAP_GATE_FILL, _SWAP_GATE_STROKE, None
    return _LOCAL_GATE_FILL, _LOCAL_GATE_STROKE, None


def _op_qubit_label(qubit: object) -> str:
    """Format a qubit-like object for compact row labels."""
    register_name = getattr(qubit, "register_name", "q")
    index = getattr(qubit, "index", "?")
    return f"{register_name}[{index}]"


def _gate_label(name: str, is_remote: bool) -> str:
    gate_name = _REMOTE_GATE_NAMES.get(name, f"r{name}") if is_remote else name
    return gate_name.upper()


def _assignment_positions(
    assignment: dict[QPU, set[int]],
) -> dict[int, tuple[int, int]]:
    positions: dict[int, tuple[int, int]] = {}
    for qpu, logical_qubits in sorted(
        assignment.items(), key=lambda item: item[0].id
    ):
        for slot_idx, logical_qubit in enumerate(sorted(logical_qubits)):
            positions[logical_qubit] = (qpu.id, slot_idx)
    return positions


def _assignment_maps(schedule: PartitionSchedule) -> list[dict[int, int]]:
    if not schedule:
        raise ValueError("schedule must contain at least one window.")
    return [qubit_partition_map(window) for window in schedule]


def _sorted_qpu_ids(schedule: PartitionSchedule) -> list[int]:
    return sorted({qpu.id for window in schedule for qpu in window})


def _transition_counts(
    assignments: list[dict[int, int]],
) -> dict[int, Counter[tuple[int, int]]]:
    transitions: dict[int, Counter[tuple[int, int]]] = {}
    for window_idx in range(len(assignments) - 1):
        counts: Counter[tuple[int, int]] = Counter()
        prev = assignments[window_idx]
        curr = assignments[window_idx + 1]
        for qubit in sorted(set(prev) | set(curr)):
            counts[(prev[qubit], curr[qubit])] += 1
        transitions[window_idx] = counts
    return transitions


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


def _remote_op_ids(
    circuit: Circuit,
    schedule: PartitionSchedule,
    windows: PartitionWindows,
) -> set[int]:
    op_to_window: dict[int, int] = {}
    for window_index, window in enumerate(windows):
        for op in window:
            op_to_window[op.op_id] = window_index

    remote_ops: set[int] = set()
    for op in circuit.mono.ops:
        if len(op.qubits) != 2:
            continue
        window_index = op_to_window[op.op_id]
        assignment = qubit_partition_map(schedule[window_index])
        q0, q1 = op.qubit_indices
        if assignment[q0] != assignment[q1]:
            remote_ops.add(op.op_id)
    return remote_ops


def _single_qpu_assignment(ops: list[Op]) -> dict[QPU, set[int]]:
    from memq_dqc.partition.partitioner import QPU

    qubits = {qubit for op in ops for qubit in op.qubit_indices}
    return {QPU(id=0): qubits}


def _circuit_subtitle(
    selected_windows: list[_SelectedWindow],
    all_windows: PartitionWindows,
    max_ops_per_window: int | None,
) -> str:
    first_window = selected_windows[0].window_index
    last_window = selected_windows[-1].window_index
    subtitle = (
        f"Windows {first_window}-{last_window} of {len(all_windows) - 1}"
        if len(all_windows) > 1
        else "Single-window circuit"
    )
    if max_ops_per_window is not None:
        subtitle += f" | first {max_ops_per_window} ops per window"
    return subtitle


def _omitted_ops_x(
    *,
    bounds: list[tuple[int, float, float]],
    window_index: int,
) -> float:
    for bound_window, _left, right in bounds:
        if bound_window == window_index:
            return right - 21.0
    raise ValueError(f"Missing bounds for window {window_index}.")


def _qpu_color(qpu_id: int) -> str:
    return _QPU_COLORS[qpu_id % len(_QPU_COLORS)]
