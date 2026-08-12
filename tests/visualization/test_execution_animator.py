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
"""Tests for the network execution animator."""

import math

import matplotlib

matplotlib.use("Agg")

import matplotlib.colors as mcolors
import matplotlib.pyplot as plt
import pytest

from xdqc.network import NetworkGraph, PhysicalQubit
from xdqc.scheduler.schedule import (
    EntanglementGeneration,
    OperationSchedule,
    ScheduledOperation,
    ScheduledQubitTimeline,
)
from xdqc.scheduler.schedule_visualizer import _pretty_role
from xdqc.visualization.execution_animator import (
    _ROLE_COLOR,
    _ROLE_PRIORITY,
    _build_frames,
    _build_label_index,
    _is_active,
    _node_metrics,
    _progress,
    _typical_separation,
    animate_circuit_execution,
    qpu_clustered_layout,
)


@pytest.fixture()
def network(simple1_network_path) -> NetworkGraph:
    return NetworkGraph(str(simple1_network_path))


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


def _schedule(*events) -> OperationSchedule:
    """Wrap events in a schedule with per-qubit timelines."""
    qubits: list[str] = []
    for event in events:
        for qubit in event.qubits:
            if qubit not in qubits:
                qubits.append(qubit)
    timelines = tuple(
        ScheduledQubitTimeline(
            qubit=qubit,
            operations=tuple(
                event for event in events if qubit in event.qubits
            ),
        )
        for qubit in qubits
    )
    makespan = max((event.end_time for event in events), default=0.0)
    return OperationSchedule(
        operations=tuple(events),
        timelines=timelines,
        makespan=makespan,
    )


@pytest.fixture()
def remote_gate_schedule() -> OperationSchedule:
    """A local gate, an EPR generation, then a remote gate that consumes it."""
    return _schedule(
        _op(0, "h", ["q1[0]"], 0.0, 10.0),
        EntanglementGeneration(
            qubits=("c1[0]", "c2[0]"),
            start_time=10.0,
            duration=500.0,
            was_used=True,
        ),
        _op(
            1,
            "rcx",
            ["q1[0]", "q2[0]", "c1[0]", "c2[0]"],
            510.0,
            20.0,
            remote=True,
        ),
        _op(2, "measure", ["q2[0]"], 530.0, 3.0),
    )


# --- label mapping ---------------------------------------------------------


def test_label_index_uses_scheduler_label_format(network):
    index = _build_label_index(list(network.graph.nodes))

    assert index["q1[0]"] == PhysicalQubit(
        qpu_id=1, qubit_id=0, qubit_type="computation"
    )
    assert index["c2[1]"] == PhysicalQubit(
        qpu_id=2, qubit_id=1, qubit_type="communication"
    )
    # Every node is reachable, so no schedule label can go unmapped.
    assert len(index) == network.num_total_qubits


def test_unknown_schedule_qubit_is_rejected(network):
    schedule = _schedule(_op(0, "h", ["q9[7]"], 0.0, 1.0))

    with pytest.raises(ValueError, match="not in the network graph"):
        animate_circuit_execution(network, schedule)


def test_empty_schedule_is_rejected(network):
    schedule = OperationSchedule(operations=(), timelines=(), makespan=0.0)

    with pytest.raises(ValueError, match="empty schedule"):
        animate_circuit_execution(network, schedule)


def test_unknown_mode_is_rejected(network, remote_gate_schedule):
    with pytest.raises(ValueError, match="Unknown playback mode"):
        animate_circuit_execution(
            network, remote_gate_schedule, mode="realtime"
        )


# --- frame construction ----------------------------------------------------


def test_event_frames_land_on_every_boundary(remote_gate_schedule):
    frames = _build_frames(remote_gate_schedule, "events", 0)

    times = [frame.time for frame in frames]
    assert times == [0.0, 10.0, 510.0, 530.0, 533.0]


def test_event_frames_hold_only_events_in_flight(remote_gate_schedule):
    frames = {
        frame.time: {event.name for event in frame.events}
        for frame in _build_frames(remote_gate_schedule, "events", 0)
    }

    assert frames[0.0] == {"h"}
    assert frames[10.0] == {"epr"}
    assert frames[510.0] == {"rcx"}
    assert frames[530.0] == {"measure"}
    # The final boundary is the makespan, where execution has finished.
    assert frames[533.0] == set()


def test_time_mode_samples_uniformly(remote_gate_schedule):
    frames = _build_frames(remote_gate_schedule, "time", 12)

    assert len(frames) == 12
    assert frames[0].time == pytest.approx(0.0)
    assert frames[-1].time == pytest.approx(remote_gate_schedule.makespan)
    steps = [
        frames[i + 1].time - frames[i].time for i in range(len(frames) - 1)
    ]
    assert steps == pytest.approx([steps[0]] * len(steps))


def test_concurrent_events_share_a_frame(network):
    schedule = _schedule(
        _op(0, "x", ["q1[0]"], 0.0, 10.0),
        _op(1, "x", ["q2[0]"], 0.0, 10.0),
    )

    frames = _build_frames(schedule, "events", 0)

    assert {event.op_id for event in frames[0].events} == {0, 1}


def test_zero_duration_event_still_gets_a_frame():
    event = _op(0, "barrier", ["q1[0]"], 5.0, 0.0)

    assert _is_active(event, 5.0) is True
    assert _is_active(event, 5.1) is False
    assert _progress(event, 5.0) == 1.0


def test_active_window_excludes_end_time():
    event = _op(0, "h", ["q1[0]"], 0.0, 10.0)

    assert _is_active(event, 0.0) is True
    assert _is_active(event, 9.999) is True
    # A qubit is free again at the instant its operation ends.
    assert _is_active(event, 10.0) is False


def test_progress_is_clamped_to_unit_interval():
    event = _op(0, "h", ["q1[0]"], 10.0, 100.0)

    assert _progress(event, 0.0) == 0.0
    assert _progress(event, 60.0) == pytest.approx(0.5)
    assert _progress(event, 999.0) == 1.0


# --- palette contract ------------------------------------------------------


def test_every_gantt_role_has_a_color_and_priority():
    """The animator reuses the Gantt's roles, so coverage must stay total."""
    roles = {
        _pretty_role(_op(0, name, ["q1[0]"], 0.0, 1.0, remote=remote))
        for name, remote in (
            ("h", False),
            ("rcx", True),
            ("rswap", False),
            ("measure", False),
            ("catent", False),
            ("catdisent", False),
        )
    }
    roles |= {
        _pretty_role(
            EntanglementGeneration(
                qubits=("c1[0]", "c2[0]"),
                start_time=0.0,
                duration=1.0,
                was_used=used,
            )
        )
        for used in (True, False)
    }

    assert roles <= set(_ROLE_COLOR)
    assert roles <= set(_ROLE_PRIORITY)


# --- layout ----------------------------------------------------------------


def test_clustered_layout_positions_every_qubit(network):
    pos = qpu_clustered_layout(network)

    assert set(pos) == set(network.graph.nodes)


def test_clusters_are_separated_by_qpu(network):
    pos = qpu_clustered_layout(network)

    centroids: dict[int, tuple[float, float]] = {}
    for qpu_id in network.qpu_ids():
        members = [n for n in network.graph.nodes if n.qpu_id == qpu_id]
        xs = [pos[n][0] for n in members]
        ys = [pos[n][1] for n in members]
        centroids[qpu_id] = (sum(xs) / len(xs), sum(ys) / len(ys))

    # Every qubit sits nearer its own QPU's centroid than any other's.
    for node in network.graph.nodes:
        own = math.dist(pos[node], centroids[node.qpu_id])
        others = [
            math.dist(pos[node], centre)
            for qpu_id, centre in centroids.items()
            if qpu_id != node.qpu_id
        ]
        assert own < min(others)


def test_layout_is_deterministic(network):
    assert qpu_clustered_layout(network) == qpu_clustered_layout(network)


def test_nodes_are_sized_to_fit_between_neighbours(network):
    pos = qpu_clustered_layout(network)

    area, font_size = _node_metrics(pos)

    diameter_pt = math.sqrt(area)
    assert diameter_pt > 0.0
    assert 4.0 <= font_size <= 8.0
    # A marker must not be wider than the gap it has to sit in.
    separation = _typical_separation(pos)
    assert separation > 0.0


def test_single_node_layout_has_no_separation_error():
    assert _typical_separation({}) == 1.0


# --- rendering -------------------------------------------------------------


def test_active_qubits_are_recolored_by_role(network, remote_gate_schedule):
    animation = animate_circuit_execution(network, remote_gate_schedule)
    try:
        nodes = list(network.graph.nodes)
        remote_frame = next(
            index
            for index, frame in enumerate(animation.frames)
            if any(event.name == "rcx" for event in frame.events)
        )
        animation.animation._func(remote_frame)

        faces = animation._node_collection.get_facecolor()
        expected = mcolors.to_rgba(_ROLE_COLOR["remote"])
        involved = {"q1[0]", "q2[0]", "c1[0]", "c2[0]"}
        index = _build_label_index(nodes)
        for label in involved:
            position = nodes.index(index[label])
            assert tuple(faces[position]) == pytest.approx(expected)
    finally:
        plt.close(animation.figure)


def test_remote_gate_highlights_the_inter_qpu_link(
    network, remote_gate_schedule
):
    animation = animate_circuit_execution(network, remote_gate_schedule)
    try:
        epr_frame = next(
            frame
            for frame in animation.frames
            if any(event.name == "epr" for event in frame.events)
        )
        segments, colors, _ = animation._highlighted_links(epr_frame)

        index = _build_label_index(list(network.graph.nodes))
        expected = {tuple(sorted((index["c1[0]"], index["c2[0]"]), key=str))}
        drawn = {
            tuple(
                sorted(
                    (
                        _node_at(animation, segment[0]),
                        _node_at(animation, segment[1]),
                    ),
                    key=str,
                )
            )
            for segment in segments
        }
        assert drawn == expected
        assert len(colors) == 1
    finally:
        plt.close(animation.figure)


def test_idle_frame_draws_no_highlights(network, remote_gate_schedule):
    animation = animate_circuit_execution(network, remote_gate_schedule)
    try:
        final = animation.frames[-1]
        assert final.events == ()

        segments, colors, widths = animation._highlighted_links(final)
        assert segments == []
        assert colors == []
        assert widths == []
        # Rendering an idle frame must not raise on the empty collection.
        animation.animation._func(len(animation.frames) - 1)
    finally:
        plt.close(animation.figure)


def test_figure_adapts_to_the_network_shape(network, remote_gate_schedule):
    animation = animate_circuit_execution(network, remote_gate_schedule)
    try:
        width, height = animation.figure.get_size_inches()
        # A two-QPU network is laid out side by side, so it is wider than tall.
        assert width > height
    finally:
        plt.close(animation.figure)


def test_explicit_figsize_is_respected(network, remote_gate_schedule):
    animation = animate_circuit_execution(
        network, remote_gate_schedule, figsize=(7.0, 5.0)
    )
    try:
        assert tuple(animation.figure.get_size_inches()) == (7.0, 5.0)
    finally:
        plt.close(animation.figure)


# --- playback controls -----------------------------------------------------


def test_controls_add_play_button_and_scrubber(network, remote_gate_schedule):
    animation = animate_circuit_execution(
        network, remote_gate_schedule, controls=True
    )
    try:
        assert animation._play_button is not None
        assert animation._slider is not None
        assert animation._slider.valmax == len(animation.frames) - 1
    finally:
        plt.close(animation.figure)


def test_play_button_toggles_playback(network, remote_gate_schedule):
    animation = animate_circuit_execution(
        network, remote_gate_schedule, controls=True
    )
    try:
        assert animation._playing is True
        assert animation._play_button.label.get_text() == "Pause"

        animation._toggle_play(None)
        assert animation._playing is False
        assert animation._play_button.label.get_text() == "Play"

        animation._toggle_play(None)
        assert animation._playing is True
        assert animation._play_button.label.get_text() == "Pause"
    finally:
        plt.close(animation.figure)


def test_scrubbing_pauses_and_jumps(network, remote_gate_schedule):
    animation = animate_circuit_execution(
        network, remote_gate_schedule, controls=True
    )
    try:
        target = len(animation.frames) - 2
        animation._slider.set_val(target)

        # A drag during playback must pause, or the timer would immediately
        # overwrite the frame the user asked to see.
        assert animation._playing is False
        assert f"frame {target + 1}/" in animation._time_text.get_text()
    finally:
        plt.close(animation.figure)


def test_following_playback_does_not_pause(network, remote_gate_schedule):
    animation = animate_circuit_execution(
        network, remote_gate_schedule, controls=True
    )
    try:
        # Rendering while playing moves the slider; that must not read back
        # as a user scrub and stop playback.
        animation.animation._func(2)

        assert animation._playing is True
        assert animation._slider.val == 2
        assert animation._slider.eventson is True
    finally:
        plt.close(animation.figure)


def test_show_attaches_controls_lazily(
    network, remote_gate_schedule, monkeypatch
):
    animation = animate_circuit_execution(network, remote_gate_schedule)
    try:
        assert animation._play_button is None

        monkeypatch.setattr(plt, "show", lambda: None)
        animation.show()

        assert animation._play_button is not None
    finally:
        plt.close(animation.figure)


def _node_at(animation, point) -> PhysicalQubit:
    """Return the qubit drawn at a segment endpoint."""
    for node, position in animation._pos.items():
        if math.isclose(position[0], point[0]) and math.isclose(
            position[1], point[1]
        ):
            return node
    raise AssertionError(f"No node at {point!r}")
