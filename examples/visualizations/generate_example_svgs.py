"""Generate lightweight SVG examples for visualization gallery.

This script intentionally uses only the Python standard library so it can run
in minimal environments where plotting dependencies are unavailable.
"""

from __future__ import annotations

from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent

PARTITION = [
    {0: {0, 1, 2}, 1: {3, 4, 5}, 2: {6, 7}},
    {0: {0, 2, 5}, 1: {1, 3, 4}, 2: {6, 7}},
    {0: {0, 5, 6}, 1: {1, 2, 4}, 2: {3, 7}},
    {0: {0, 3, 6}, 1: {1, 2, 4}, 2: {5, 7}},
    {0: {0, 1, 6}, 1: {2, 3, 4}, 2: {5, 7}},
]

WINDOW_COUNTS = {
    "single": [1, 1, 1, 1, 1],
    "local": [2, 2, 1, 2, 2],
    "remote": [1, 1, 2, 1, 1],
}

MIGRATION = [2, 3, 2, 1]
ENTANGLEMENT = [2.0, 3.0, 2.0, 1.0]

PALETTE = ["#222636", "#3f5f81", "#a558b5"]


def _svg_header(width: int, height: int) -> str:
    return (
        f"<svg xmlns='http://www.w3.org/2000/svg' "
        f"width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}'>"
        "<rect width='100%' height='100%' fill='white'/>"
    )


def _write(name: str, body: str, width: int, height: int) -> None:
    path = OUT_DIR / name
    path.write_text(
        _svg_header(width, height) + body + "</svg>\n", encoding="utf-8"
    )


def _assignment() -> list[dict[int, int]]:
    rows: list[dict[int, int]] = []
    for window in PARTITION:
        mapping: dict[int, int] = {}
        for qpu, qubits in window.items():
            for qubit in qubits:
                mapping[qubit] = qpu
        rows.append(mapping)
    return rows


def make_heatmap() -> None:
    """Create a heatmap-style SVG for qubit assignment over windows."""
    assignments = _assignment()
    qubits = sorted(assignments[0])
    cell_width, cell_height = 70, 34
    origin_x, origin_y = 65, 45
    body = [
        "<text x='16' y='24' font-size='18' "
        "font-family='Arial'>Partition Heatmap</text>"
    ]
    for column_idx, _ in enumerate(assignments):
        x_pos = origin_x + column_idx * cell_width
        body.append(
            f"<text x='{x_pos + 28}' y='36' font-size='12' "
            "font-family='Arial'>"
            f"{column_idx}</text>"
        )
    for row_idx, qubit in enumerate(qubits):
        y_pos = origin_y + row_idx * cell_height
        body.append(
            f"<text x='30' y='{y_pos + 22}' font-size='12' font-family='Arial'>"
            f"q{qubit}</text>"
        )
        for column_idx, mapping in enumerate(assignments):
            x_pos = origin_x + column_idx * cell_width
            qpu = mapping[qubit]
            body.append(
                f"<rect x='{x_pos}' y='{y_pos}' width='{cell_width - 6}' "
                f"height='{cell_height - 6}' fill='{PALETTE[qpu]}' rx='4'/>"
            )
    _write("partition_heatmap_example.svg", "".join(body), 440, 340)


def make_flow() -> None:
    """Create a trajectory-style SVG for qubit movement between QPUs."""
    assignments = _assignment()
    tracked_qubits = list(range(8))
    origin_x, origin_y, width, height = 65, 40, 360, 230
    window_step = width / (len(assignments) - 1)
    qpu_step = height / 2
    body = [
        "<text x='16' y='24' font-size='18' font-family='Arial'>"
        "Qubit Flow</text>"
    ]
    for qpu in range(3):
        y_pos = origin_y + qpu * qpu_step
        body.append(
            f"<line x1='{origin_x}' y1='{y_pos}' x2='{origin_x + width}' "
            "y2='"
            f"{y_pos}' stroke='#ddd'/>"
        )
        body.append(
            f"<text x='30' y='{y_pos + 4}' font-size='11' font-family='Arial'>"
            f"QPU {qpu}</text>"
        )
    colors = [
        "#1f77b4",
        "#ff7f0e",
        "#2ca02c",
        "#d62728",
        "#9467bd",
        "#8c564b",
        "#e377c2",
        "#7f7f7f",
    ]
    for qubit in tracked_qubits:
        points = []
        for column_idx, mapping in enumerate(assignments):
            x_pos = origin_x + column_idx * window_step
            y_pos = origin_y + mapping[qubit] * qpu_step
            points.append(f"{x_pos},{y_pos}")
        body.append(
            f"<polyline points='{' '.join(points)}' fill='none' "
            f"stroke='{colors[qubit]}' stroke-width='2' opacity='0.9'/>"
        )
    _write("qubit_flow_example.svg", "".join(body), 460, 300)


def make_migration() -> None:
    """Create a dual-series timeline SVG for migrations and e-bit cost."""
    origin_x, origin_y, width, height = 65, 35, 360, 220
    window_step = width / (len(MIGRATION) - 1)
    y_scale = height / 4
    body = [
        "<text x='16' y='24' font-size='18' font-family='Arial'>"
        "Migration Timeline</text>"
    ]
    for idx, value in enumerate(MIGRATION):
        x_pos = origin_x + idx * window_step
        y_pos = origin_y + height - value * y_scale
        body.append(
            f"<circle cx='{x_pos}' cy='{y_pos}' r='4' fill='#1f77b4'/>"
        )
        if idx:
            prev_x = origin_x + (idx - 1) * window_step
            prev_y = origin_y + height - MIGRATION[idx - 1] * y_scale
            body.append(
                f"<line x1='{prev_x}' y1='{prev_y}' x2='{x_pos}' "
                f"y2='{y_pos}' stroke='#1f77b4' stroke-width='2'/>"
            )

        ent_y = origin_y + height - ENTANGLEMENT[idx] * y_scale
        body.append(
            f"<rect x='{x_pos - 3}' y='{ent_y - 3}' width='6' height='6' fill='#d95f02'/>"
        )
        if idx:
            prev_x = origin_x + (idx - 1) * window_step
            prev_ent_y = origin_y + height - ENTANGLEMENT[idx - 1] * y_scale
            body.append(
                f"<line x1='{prev_x}' y1='{prev_ent_y}' x2='{x_pos}' "
                f"y2='{ent_y}' stroke='#d95f02' stroke-width='2'/>"
            )
    _write("migration_timeline_example.svg", "".join(body), 460, 280)


def make_profile() -> None:
    """Create a stacked-bar SVG for per-window operation profile."""
    origin_x, origin_y, height = 70, 40, 220
    bar_width = 46
    bar_gap = 22
    scale = height / 5
    body = [
        "<text x='16' y='24' font-size='18' font-family='Arial'>"
        "Window Operation Profile</text>"
    ]
    for idx in range(5):
        x_pos = origin_x + idx * (bar_width + bar_gap)
        single_count = WINDOW_COUNTS["single"][idx]
        local_count = WINDOW_COUNTS["local"][idx]
        remote_count = WINDOW_COUNTS["remote"][idx]
        y_pos = origin_y + height
        for value, color in (
            (single_count, "#6baed6"),
            (local_count, "#74c476"),
            (remote_count, "#fb6a4a"),
        ):
            block_height = value * scale
            y_pos -= block_height
            body.append(
                f"<rect x='{x_pos}' y='{y_pos}' width='{bar_width}' "
                f"height='{block_height}' fill='{color}' rx='2'/>"
            )
    _write("window_operation_profile_example.svg", "".join(body), 460, 300)


def main() -> None:
    """Generate all SVG examples."""
    make_heatmap()
    make_flow()
    make_migration()
    make_profile()


if __name__ == "__main__":
    main()
