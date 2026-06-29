# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Tests for the scheduler Gantt visualization."""

import matplotlib

matplotlib.use("Agg")

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pytest
from matplotlib.axes import Axes

from memq_dqc.scheduler.schedule import (
    EntanglementGeneration,
    OperationSchedule,
    ScheduledOperation,
    ScheduledQubitTimeline,
)
from memq_dqc.scheduler.schedule_visualizer import (
    _PRETTY_LOCAL_FILL,
    _PRETTY_REMOTE_FILL,
    _PRETTY_TEAL,
    _group_qubits,
    _nice_tick_step,
    _parse_qubit_label,
    _pretty_role,
    _pretty_time_unit_label,
    plot_schedule_gantt,
)


def _op(
    op_id: int,
    name: str,
    qubits: list[str],
    start: float,
    duration: float,
    *,
    remote: bool = False,
) -> ScheduledOperation:
    return ScheduledOperation(
        op_id=op_id,
        statement_id=op_id,
        name=name,
        qubits=tuple(qubits),
        start_time=start,
        duration=duration,
        is_remote=remote,
    )


def _schedule() -> OperationSchedule:
    """Build a two-module schedule covering every palette role."""
    ops: tuple = (
        _op(0, "h", ["q1[0]"], 0.0, 1.0),
        _op(1, "cx", ["q1[0]", "q1[1]"], 1.0, 1.0),
        _op(2, "rcx", ["q1[1]", "q0[0]"], 6.0, 1.5, remote=True),
        _op(3, "catdisent", ["q0[0]"], 7.5, 4.0),
        _op(4, "measure", ["q1[0]"], 12.0, 3.0),
        EntanglementGeneration(
            qubits=("c1[0]", "c0[0]"), start_time=2.0, duration=2.0
        ),
        _op(5, "catent", ["c0[0]"], 4.0, 3.0),
    )
    qubits = ["q1[0]", "q1[1]", "q0[0]", "c1[0]", "c0[0]"]
    timelines = tuple(
        ScheduledQubitTimeline(
            qubit=q,
            operations=tuple(o for o in ops if q in o.qubits),
        )
        for q in qubits
    )
    return OperationSchedule(
        operations=ops, timelines=timelines, makespan=15.0
    )


def _facecolors(ax: Axes) -> set[str]:
    return {mcolors.to_hex(patch.get_facecolor()) for patch in ax.patches}


def _legend_texts(ax: Axes) -> set[str]:
    legend = ax.get_legend()
    if legend is None:
        return set()
    return {text.get_text() for text in legend.get_texts()}


# --- shared helpers --------------------------------------------------------


def test_parse_qubit_label() -> None:
    assert _parse_qubit_label("q1[2]") == ("comp", 1, 2)
    assert _parse_qubit_label("c0[0]") == ("comm", 0, 0)
    assert _parse_qubit_label("q0") == ("comp", None, None)
    assert _parse_qubit_label("cx") == ("comm", None, None)


def test_group_qubits_clusters_modules_with_comm_last() -> None:
    groups = _group_qubits(
        ["q1[0]", "q1[2]", "q1[1]", "q0[0]", "c0[0]", "c1[0]"]
    )
    assert [g.title for g in groups] == ["MODULE 1", "MODULE 0", "COMM"]
    # Sorted within each module group.
    assert groups[0].labels == ["q1[0]", "q1[1]", "q1[2]"]
    assert groups[1].labels == ["q0[0]"]
    # Comm grouped last, higher module first.
    assert groups[2].is_comm is True
    assert groups[2].labels == ["c1[0]", "c0[0]"]


def test_pretty_role_classification() -> None:
    assert _pretty_role(_op(0, "cx", ["q0[0]"], 0, 1)) == "local"
    assert (
        _pretty_role(_op(0, "rcx", ["q0[0]"], 0, 1, remote=True)) == "remote"
    )
    assert _pretty_role(_op(0, "measure", ["q0[0]"], 0, 1)) == "measure"
    assert _pretty_role(_op(0, "rswap", ["q0[0]"], 0, 1)) == "swap"
    assert _pretty_role(_op(0, "catent", ["c0[0]"], 0, 1)) == "reserved"
    assert _pretty_role(_op(0, "catdisent", ["q0[0]"], 0, 1)) == "reserved"
    consumed = EntanglementGeneration(qubits=("c1[0]", "c0[0]"), start_time=0)
    unused = EntanglementGeneration(
        qubits=("c1[0]", "c0[0]"), start_time=0, was_used=False
    )
    assert _pretty_role(consumed) == "epr_consumed"
    assert _pretty_role(unused) == "epr_unused"


def test_nice_tick_step() -> None:
    assert _nice_tick_step(31.0) == 5.0
    assert _nice_tick_step(8.0) == 2.0
    assert _nice_tick_step(3.0) == 1.0


def test_pretty_time_unit_label_uses_settings() -> None:
    # The packaged settings configure microseconds ("us").
    assert _pretty_time_unit_label() == "μs"


# --- legacy (on-screen / diagnostic) rendering -----------------------------


def test_plot_schedule_gantt_legacy_returns_axes() -> None:
    ax = plot_schedule_gantt(_schedule(), display="legacy")
    assert isinstance(ax, Axes)
    assert ax.patches
    plt.close(ax.figure)


def test_plot_schedule_gantt_legacy_keeps_original_casing() -> None:
    ax = plot_schedule_gantt(
        _schedule(), title="my schedule", display="legacy"
    )
    assert ax.get_title() == "my schedule"
    assert ax.get_xlabel() == f"Time ({_pretty_time_unit_label()})"
    bar_labels = {text.get_text() for text in ax.texts}
    assert "measure" in bar_labels
    plt.close(ax.figure)


def test_plot_schedule_gantt_rejects_empty_schedule() -> None:
    empty = OperationSchedule(operations=(), timelines=(), makespan=0.0)
    with pytest.raises(ValueError, match="at least one qubit timeline"):
        plot_schedule_gantt(empty)


def test_plot_schedule_gantt_explicit_ops_requires_operations() -> None:
    timeline = ScheduledQubitTimeline(qubit="q0[0]", operations=())
    schedule = OperationSchedule(
        operations=(), timelines=(timeline,), makespan=0.0
    )
    with pytest.raises(ValueError, match="at least one operation"):
        plot_schedule_gantt(schedule, explicit_ops=True)


def test_plot_schedule_gantt_rejects_unknown_display() -> None:
    with pytest.raises(ValueError, match="display must be"):
        plot_schedule_gantt(_schedule(), display="fancy")  # type: ignore[arg-type]


# --- pretty (publication) rendering — the default --------------------------


def test_plot_schedule_gantt_pretty_is_default() -> None:
    # No display argument should produce the publication variant.
    ax = plot_schedule_gantt(_schedule())
    texts = {text.get_text() for text in ax.texts}
    assert "PHYSICAL QUBIT" in texts
    assert isinstance(ax, Axes)
    assert ax.patches
    plt.close(ax.figure)


def test_plot_schedule_gantt_pretty_uses_print_palette() -> None:
    ax = plot_schedule_gantt(_schedule(), display="pretty")
    facecolors = _facecolors(ax)
    assert mcolors.to_hex(_PRETTY_LOCAL_FILL) in facecolors
    assert mcolors.to_hex(_PRETTY_REMOTE_FILL) in facecolors
    assert mcolors.to_hex(_PRETTY_TEAL) in facecolors
    plt.close(ax.figure)


def test_plot_schedule_gantt_pretty_uppercases_labels_not_legend() -> None:
    ax = plot_schedule_gantt(_schedule())
    assert ax.get_xlabel() == f"TIME ({_pretty_time_unit_label()})"
    assert ax.get_title() == ""  # no baked-in title by default
    tick_labels = {label.get_text() for label in ax.get_yticklabels()}
    assert "Q1[0]" in tick_labels
    assert "C0[0]" in tick_labels
    bar_labels = {text.get_text() for text in ax.texts}
    assert {"RCX", "EPR", "CATENT", "MEASURE"} <= bar_labels
    # Legend stays sentence case.
    legend_texts = _legend_texts(ax)
    assert "Local gate" in legend_texts
    plt.close(ax.figure)


def test_plot_schedule_gantt_pretty_legend_only_present_roles() -> None:
    ax = plot_schedule_gantt(_schedule())
    legend_texts = _legend_texts(ax)
    # Present in the schedule.
    assert "Remote (non-local) gate" in legend_texts
    assert "Entanglement generation" in legend_texts
    assert "Entanglement — reserved" in legend_texts
    assert "Remote / EPR link" in legend_texts
    # Absent from the schedule -> omitted.
    assert "Routed swap" not in legend_texts
    assert "Entanglement — unused" not in legend_texts
    # The local two-qubit link is intentionally omitted from the legend.
    assert "Two-qubit gate link" not in legend_texts
    plt.close(ax.figure)


def test_plot_schedule_gantt_pretty_renders_module_brackets() -> None:
    ax = plot_schedule_gantt(_schedule())
    texts = {text.get_text() for text in ax.texts}
    assert {"MODULE 1", "MODULE 0", "COMM", "PHYSICAL QUBIT"} <= texts
    plt.close(ax.figure)


def test_plot_schedule_gantt_pretty_explicit_ops() -> None:
    ax = plot_schedule_gantt(_schedule(), explicit_ops=True)
    assert isinstance(ax, Axes)
    assert ax.get_ylabel() == "OPERATION"
    assert ax.patches
    plt.close(ax.figure)


def test_nice_tick_step_handles_large_span() -> None:
    # Regression: spans beyond the old fixed ladder returned None.
    step = _nice_tick_step(860_000.0)
    assert step > 0.0
    assert 860_000.0 / step <= 12.0


def test_plot_schedule_gantt_pretty_renders_large_makespan() -> None:
    # Regression: a per-unit minor locator exceeded Matplotlib's tick limit
    # and broke rendering for large makespans.
    makespan = 860_000.0
    ops: tuple = (
        _op(0, "h", ["q0[0]"], 0.0, 10.0),
        EntanglementGeneration(
            qubits=("c0[0]", "c1[0]"),
            start_time=10.0,
            duration=makespan - 10.0,
        ),
    )
    qubits = ["q0[0]", "c0[0]", "c1[0]"]
    schedule = OperationSchedule(
        operations=ops,
        timelines=tuple(
            ScheduledQubitTimeline(
                qubit=q, operations=tuple(o for o in ops if q in o.qubits)
            )
            for q in qubits
        ),
        makespan=makespan,
    )
    ax = plot_schedule_gantt(schedule)
    ax.figure.canvas.draw()  # force a full render; would raise on the old bug
    assert isinstance(ax, Axes)
    plt.close(ax.figure)
