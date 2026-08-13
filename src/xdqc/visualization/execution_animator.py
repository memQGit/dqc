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
"""Animated network-graph playback of a distributed circuit's execution.

This module draws a :class:`~xdqc.network.NetworkGraph` as a NetworkX plot in
which every node is a physical qubit and every edge is either an intra-QPU
(local) or inter-QPU (remote) connection, then plays an
:class:`~xdqc.scheduler.schedule.OperationSchedule` back over that graph. On
each frame the qubits and links taking part in the currently executing
operations are highlighted, so a distributed circuit's execution can be
watched from start to finish.

Operations are colored by the same roles the scheduler Gantt chart uses (see
:func:`xdqc.scheduler.schedule_visualizer._pretty_role`), so the animation and
the Gantt agree on what counts as a local gate, a remote gate, a routed swap,
a cat-entanglement region, or entanglement generation.

Two playback modes are available:

- ``"events"`` (default) advances one frame per schedule event boundary, so
  every operation gets equal screen time regardless of its duration. This is
  usually what you want to watch, because entanglement generation dominates
  wall-clock time in realistic hardware profiles.
- ``"time"`` samples the schedule at uniform time steps, which is physically
  faithful but spends most frames waiting on entanglement.

Example:
    Compile, schedule, and animate a circuit on a two-QPU network::

        from xdqc import Compiler, Scheduler
        from xdqc.network import NetworkGraph
        from xdqc.visualization import animate_circuit_execution

        network = NetworkGraph("demo/inputs/demo_network.json")
        compiler = Compiler("demo/inputs/qft_n4.qasm", network)
        compiler.compile(ebit_assignment=True)

        scheduler = Scheduler(compiler, algo="des_link_fifo")
        scheduler.run()

        animation = animate_circuit_execution(network, scheduler.schedule)
        animation.show()
"""

from __future__ import annotations

import math
from bisect import bisect_right
from dataclasses import dataclass
from os import PathLike
from typing import Literal

import matplotlib.patheffects as patheffects
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
from matplotlib.animation import FuncAnimation
from matplotlib.axes import Axes
from matplotlib.collections import LineCollection, PathCollection
from matplotlib.colors import to_rgba
from matplotlib.figure import Figure
from matplotlib.lines import Line2D
from matplotlib.patches import Circle, Patch, Rectangle
from matplotlib.text import Text
from matplotlib.widgets import Button, Slider

from xdqc.network import NetworkGraph, PhysicalQubit
from xdqc.scheduler.schedule import (
    EntanglementGeneration,
    OperationSchedule,
    ScheduleEvent,
)

# Role classification and legend wording are shared with the Gantt chart so
# the two views never drift apart on what an operation "is".
from xdqc.scheduler.schedule_visualizer import (
    _PRETTY_ROLE_LEGEND,
    _pretty_role,
)

PlaybackMode = Literal["events", "time"]

# --- Idle (background) network styling -------------------------------------
_COMP_IDLE_FILL = "#ece5f7"
_COMP_IDLE_EDGE = "#b9a5dd"
_COMM_IDLE_FILL = "#d8f5f1"
_COMM_IDLE_EDGE = "#7fcfc4"
_LOCAL_EDGE_COLOR = "#b7b7c4"
_REMOTE_EDGE_COLOR = "#c9b6ea"
_QPU_PATCH_FILL = "#f7f4fc"
_QPU_PATCH_EDGE = "#ded4f0"
_TEXT_COLOR = "#0f172a"
_MUTED_TEXT_COLOR = "#64748b"
_PROGRESS_TRACK_COLOR = "#e4e4ec"
_PROGRESS_FILL_COLOR = "#4801b0"

# --- Active (highlighted) styling, keyed by Gantt role ---------------------
# Saturated counterparts of the Gantt fills: a node plot needs stronger color
# than a bar chart to stay readable at small node sizes.
_ROLE_COLOR: dict[str, str] = {
    "local": "#6a4cff",
    "remote": "#d702fe",
    "measure": "#64748b",
    "swap": "#f59e0b",
    "reserved": "#4801b0",
    "epr_consumed": "#00dec6",
    "epr_unused": "#dc2626",
}

# When one qubit takes part in several concurrent events, the highest-priority
# role wins its color. Communication-heavy roles outrank plain local gates so
# the distributed part of the execution stays visible.
_ROLE_PRIORITY: dict[str, int] = {
    "remote": 6,
    "reserved": 5,
    "epr_unused": 4,
    "epr_consumed": 3,
    "swap": 2,
    "local": 1,
    "measure": 0,
}

# Legend order, chosen to read as a rough execution narrative.
_LEGEND_ROLE_ORDER: tuple[str, ...] = (
    "local",
    "remote",
    "swap",
    "measure",
    "reserved",
    "epr_consumed",
    "epr_unused",
)

#: Area multiplier applied to a node while it is executing an operation. Kept
#: modest because the two qubits of a gate are often layout neighbours, and a
#: larger pop would make them overlap.
_ACTIVE_NODE_SCALE = 1.35
_MAX_ACTIVE_OPS_LISTED = 6
#: Gap between the outermost qubit of a QPU and that QPU's background ring.
_QPU_RING_MARGIN = 0.14
#: Fraction of the typical node separation one node's diameter may occupy.
_NODE_FILL_FRACTION = 0.82
_MIN_NODE_DIAMETER_PT = 7.0
_MAX_NODE_DIAMETER_PT = 30.0


@dataclass(frozen=True, slots=True)
class ExecutionFrame:
    """One rendered instant of a schedule playback.

    Attributes:
        time: Schedule time this frame depicts, in scheduler time units.
        events: Events in flight at ``time``, ordered as in the schedule.
    """

    time: float
    events: tuple[ScheduleEvent, ...]


def qpu_clustered_layout(
    network: NetworkGraph,
    *,
    cluster_scale: float = 0.45,
    seed: int = 7,
) -> dict[PhysicalQubit, tuple[float, float]]:
    """Lay out a network graph as one visual cluster per QPU.

    Each QPU's qubits are laid out with a spring layout over that QPU's local
    edges only, normalized into a disk, and then placed at a QPU centre spaced
    evenly around a circle. Intra-QPU edges therefore stay short and inside a
    cluster while inter-QPU edges visibly span between clusters, which is the
    property that makes the two connection types easy to tell apart.

    The circle the centres sit on grows with the QPU count so that clusters
    never collide, and two QPUs are placed side by side rather than stacked.

    Args:
        network: Network whose graph should be laid out.
        cluster_scale: Radius of one QPU cluster in layout units.
        seed: Seed for the per-QPU spring layout, so layouts are reproducible.

    Returns:
        Mapping of every physical qubit to its ``(x, y)`` position.
    """
    graph = network.graph
    qpu_ids = [
        qpu_id
        for qpu_id in network.qpu_ids()
        if any(node.qpu_id == qpu_id for node in graph.nodes)
    ]
    positions: dict[PhysicalQubit, tuple[float, float]] = {}
    num_qpus = len(qpu_ids)
    if num_qpus == 0:
        return positions

    network_radius = _network_radius(num_qpus, cluster_scale)
    for index, qpu_id in enumerate(qpu_ids):
        centre = _qpu_centre(index, num_qpus, network_radius)
        members = [node for node in graph.nodes if node.qpu_id == qpu_id]
        local_subgraph = graph.subgraph(members).copy()
        local_subgraph.remove_edges_from(
            [
                (u, v)
                for u, v, data in local_subgraph.edges(data=True)
                if data.get("connection_type") != "local"
            ]
        )
        local_positions = nx.spring_layout(
            local_subgraph,
            seed=seed,
            iterations=120,
        )
        for node, offset in _normalized_offsets(local_positions).items():
            positions[node] = (
                centre[0] + cluster_scale * offset[0],
                centre[1] + cluster_scale * offset[1],
            )
    return positions


def animate_circuit_execution(
    network: NetworkGraph,
    schedule: OperationSchedule,
    *,
    mode: PlaybackMode = "events",
    num_frames: int = 240,
    interval: int = 400,
    repeat: bool = True,
    title: str | None = None,
    figsize: tuple[float, float] | None = None,
    pos: dict[PhysicalQubit, tuple[float, float]] | None = None,
    show_labels: bool = True,
    controls: bool = False,
) -> NetworkExecutionAnimation:
    """Animate a schedule over its network graph.

    Args:
        network: Network the schedule was produced for. Its graph supplies the
            nodes (physical qubits) and the local/remote edges.
        schedule: Operation schedule to play back.
        mode: ``"events"`` for one frame per event boundary, or ``"time"`` for
            uniform time sampling across the makespan.
        num_frames: Number of frames to sample in ``"time"`` mode. Ignored in
            ``"events"`` mode, where the schedule fixes the frame count.
        interval: Delay between frames in milliseconds.
        repeat: Whether playback loops back to the start when it finishes.
        title: Figure title. Defaults to a generated summary of the schedule.
        figsize: Figure size in inches.
        pos: Explicit node positions. Defaults to
            :func:`qpu_clustered_layout`.
        show_labels: Whether to draw physical-qubit labels on the nodes.
        controls: Whether to reserve space for, and attach, play/pause and
            scrub widgets. :meth:`NetworkExecutionAnimation.show` enables this
            automatically, so it is only needed when embedding the figure.

    Returns:
        The animation wrapper. Keep a reference to it for as long as playback
        should continue; dropping it lets the underlying timer be collected.

    Raises:
        ValueError: If the schedule has no events, if ``mode`` is unknown, or
            if the schedule references qubits absent from the network.
    """
    animation = NetworkExecutionAnimation(
        network=network,
        schedule=schedule,
        mode=mode,
        num_frames=num_frames,
        interval=interval,
        repeat=repeat,
        title=title,
        figsize=figsize,
        pos=pos,
        show_labels=show_labels,
        controls=controls,
    )
    return animation


class NetworkExecutionAnimation:
    """Playable animation of a schedule over a physical-qubit network graph.

    Instances build their figure and frame list eagerly, then expose the
    animation for display (:meth:`show`), notebook embedding
    (:meth:`to_jshtml`), or export (:meth:`save`).
    """

    def __init__(
        self,
        network: NetworkGraph,
        schedule: OperationSchedule,
        *,
        mode: PlaybackMode = "events",
        num_frames: int = 240,
        interval: int = 400,
        repeat: bool = True,
        title: str | None = None,
        figsize: tuple[float, float] | None = None,
        pos: dict[PhysicalQubit, tuple[float, float]] | None = None,
        show_labels: bool = True,
        controls: bool = False,
    ) -> None:
        """Initialize the animation and render its first frame.

        Args:
            network: Network the schedule was produced for.
            schedule: Operation schedule to play back.
            mode: ``"events"`` or ``"time"`` playback.
            num_frames: Frame count for ``"time"`` mode.
            interval: Delay between frames in milliseconds.
            repeat: Whether playback loops.
            title: Figure title, or ``None`` for a generated summary.
            figsize: Figure size in inches.
            pos: Explicit node positions, or ``None`` for the clustered
                layout.
            show_labels: Whether to label nodes with physical-qubit names.
            controls: Whether to attach play/pause and scrub widgets.

        Raises:
            ValueError: If the schedule is empty, ``mode`` is unknown, or the
                schedule references qubits absent from the network.
        """
        if not schedule.operations:
            raise ValueError(
                "Cannot animate an empty schedule: it has no operations."
            )
        if mode not in ("events", "time"):
            raise ValueError(
                f"Unknown playback mode {mode!r}. Expected 'events' or 'time'."
            )

        self._network = network
        self._schedule = schedule
        self._mode: PlaybackMode = mode
        self._nodes: list[PhysicalQubit] = list(network.graph.nodes)
        self._label_to_node = _build_label_index(self._nodes)
        _validate_schedule_qubits(schedule, self._label_to_node)

        self._event_nodes = {
            id(event): self._event_node_set(event)
            for event in schedule.operations
        }
        self._frames = _build_frames(schedule, mode, num_frames)
        self._pos = (
            dict(pos) if pos is not None else qpu_clustered_layout(network)
        )

        self._fig, self._ax = plt.subplots(
            figsize=figsize
            if figsize is not None
            else _auto_figsize(self._pos)
        )
        # Node size follows the layout rather than being fixed, so a QPU
        # holding many qubits does not render as a pile of overlapping discs.
        self._node_size, self._label_fontsize = _node_metrics(self._pos)
        self._controls_enabled = controls
        self._play_button: Button | None = None
        self._slider: Slider | None = None
        self._playing = True
        self._draw_static(title=title, show_labels=show_labels)

        self._anim = FuncAnimation(
            self._fig,
            self._render_frame,
            frames=len(self._frames),
            interval=interval,
            repeat=repeat,
            blit=False,
            cache_frame_data=False,
        )
        if controls:
            self._attach_controls()
        self._render_frame(0)

    # -- public surface ----------------------------------------------------

    @property
    def figure(self) -> Figure:
        """Return the matplotlib figure hosting the animation."""
        return self._fig

    @property
    def axes(self) -> Axes:
        """Return the axes the network graph is drawn on."""
        return self._ax

    @property
    def animation(self) -> FuncAnimation:
        """Return the underlying matplotlib animation."""
        return self._anim

    @property
    def frames(self) -> tuple[ExecutionFrame, ...]:
        """Return the frames this animation plays through."""
        return self._frames

    def show(self) -> None:
        """Display the animation in an interactive window with controls.

        Attaches play/pause and scrub widgets if they are not already present,
        then blocks on the active matplotlib backend.
        """
        if not self._controls_enabled:
            self._attach_controls()
            self._controls_enabled = True
        plt.show()

    def save(
        self,
        path: str | PathLike[str],
        *,
        fps: int = 3,
        dpi: int = 150,
    ) -> None:
        """Write the animation to a file.

        The writer is chosen from the extension: ``.gif`` uses Pillow, ``.mp4``
        needs ffmpeg on the path, and ``.html`` writes a self-contained
        JavaScript player.

        Args:
            path: Destination path, including extension.
            fps: Frames per second in the written file.
            dpi: Output resolution in dots per inch.
        """
        self._anim.save(str(path), fps=fps, dpi=dpi)

    def to_jshtml(self, *, fps: int = 3) -> str:
        """Return a self-contained HTML player for notebook display.

        Args:
            fps: Frames per second for the embedded player.

        Returns:
            HTML markup with play, pause, and scrub controls.
        """
        return self._anim.to_jshtml(fps=fps)

    def _repr_html_(self) -> str:
        """Return the HTML player so notebooks render the animation inline."""
        plt.close(self._fig)
        return self.to_jshtml()

    # -- static scene ------------------------------------------------------

    def _draw_static(self, *, title: str | None, show_labels: bool) -> None:
        """Draw every artist that does not change between frames.

        Args:
            title: Figure title, or ``None`` for a generated summary.
            show_labels: Whether to label nodes with physical-qubit names.
        """
        ax = self._ax
        ax.set_axis_off()
        ax.set_aspect("equal")
        # Snug limits plus an aspect-matched figure keep a wide, short network
        # (the common case for a few QPUs in a row) from being letterboxed
        # inside a tall axes.
        min_x, max_x, min_y, max_y = _content_bounds(self._pos)
        ax.set_xlim(min_x, max_x)
        ax.set_ylim(min_y, max_y)
        graph = self._network.graph

        self._draw_qpu_regions()

        local_edges = _edges_of_type(graph, "local")
        remote_edges = _edges_of_type(graph, "remote")
        nx.draw_networkx_edges(
            graph,
            self._pos,
            edgelist=local_edges,
            ax=ax,
            width=1.6,
            edge_color=_LOCAL_EDGE_COLOR,
            style="solid",
        )
        nx.draw_networkx_edges(
            graph,
            self._pos,
            edgelist=remote_edges,
            ax=ax,
            width=1.6,
            edge_color=_REMOTE_EDGE_COLOR,
            style=(0, (5, 4)),
        )

        # One collection redrawn per frame carries every highlighted link.
        self._highlight_edges = LineCollection(
            [],
            linewidths=4.0,
            zorder=3,
            capstyle="round",
        )
        ax.add_collection(self._highlight_edges)

        self._idle_face = [
            _COMM_IDLE_FILL if node.is_communication else _COMP_IDLE_FILL
            for node in self._nodes
        ]
        self._idle_edge = [
            _COMM_IDLE_EDGE if node.is_communication else _COMP_IDLE_EDGE
            for node in self._nodes
        ]
        self._node_collection: PathCollection = nx.draw_networkx_nodes(
            graph,
            self._pos,
            nodelist=self._nodes,
            ax=ax,
            node_size=self._node_size,
            node_color=self._idle_face,
            edgecolors=self._idle_edge,
            linewidths=1.4,
        )
        self._node_collection.set_zorder(4)

        if show_labels:
            labels = nx.draw_networkx_labels(
                graph,
                self._pos,
                labels={node: node.label for node in self._nodes},
                ax=ax,
                font_size=self._label_fontsize,
                font_family="sans-serif",
                font_color=_TEXT_COLOR,
            )
            # Labels must sit above the node collection, and a white halo
            # keeps them readable on both pale idle and saturated active
            # fills without recoloring text every frame.
            for label in labels.values():
                label.set_zorder(6)
                label.set_path_effects(
                    [patheffects.withStroke(linewidth=2.4, foreground="white")]
                )

        # Both header lines live in figure coordinates, above the strip
        # reserved by tight_layout. An axes title would instead sit inside the
        # plot area, where a QPU cluster label can collide with it.
        self._fig.suptitle(
            title if title is not None else self._default_title(),
            y=0.985,
            va="top",
            fontsize=12,
            color=_TEXT_COLOR,
        )
        self._time_text: Text = self._fig.text(
            0.5,
            0.949,
            "",
            ha="center",
            va="top",
            fontsize=10,
            color=_MUTED_TEXT_COLOR,
        )
        self._ops_text: Text = ax.text(
            0.0,
            0.0,
            "",
            transform=ax.transAxes,
            ha="left",
            va="bottom",
            fontsize=8.5,
            color=_TEXT_COLOR,
            linespacing=1.5,
            zorder=7,
        )
        self._draw_legend()
        # Reserve strips for the figure title and the progress bar so neither
        # can collide with the axes title or the status text, whatever aspect
        # ratio the equal-aspect axes settles on.
        self._fig.tight_layout(rect=(0.0, 0.05, 1.0, 0.94))
        self._draw_progress_bar()

    def _draw_qpu_regions(self) -> None:
        """Shade and label one background region per QPU."""
        by_qpu: dict[int, list[PhysicalQubit]] = {}
        for node in self._nodes:
            by_qpu.setdefault(node.qpu_id, []).append(node)

        for qpu_id, members in sorted(by_qpu.items()):
            xs = [self._pos[node][0] for node in members]
            ys = [self._pos[node][1] for node in members]
            centre = (sum(xs) / len(xs), sum(ys) / len(ys))
            radius = _QPU_RING_MARGIN + max(
                (math.dist(centre, self._pos[node]) for node in members),
                default=0.0,
            )
            self._ax.add_patch(
                Circle(
                    centre,
                    radius,
                    facecolor=_QPU_PATCH_FILL,
                    edgecolor=_QPU_PATCH_EDGE,
                    linewidth=1.2,
                    zorder=0,
                )
            )
            self._ax.text(
                centre[0],
                centre[1] + radius + 0.03,
                f"QPU {qpu_id}",
                ha="center",
                va="bottom",
                fontsize=9.5,
                fontweight="bold",
                color=_PROGRESS_FILL_COLOR,
                zorder=1,
            )

    def _draw_progress_bar(self) -> None:
        """Add the frame-progress track and its fill to the figure.

        The bar lives in figure coordinates rather than axes coordinates: the
        axes are held to an equal aspect ratio and can end up far narrower
        than the figure, which would make an axes-anchored bar misleading.
        """
        track_x, track_y = 0.08, 0.014
        self._progress_width = 0.84
        for width, color, zorder in (
            (self._progress_width, _PROGRESS_TRACK_COLOR, 5),
            (0.0, _PROGRESS_FILL_COLOR, 6),
        ):
            patch = Rectangle(
                (track_x, track_y),
                width,
                0.009,
                transform=self._fig.transFigure,
                facecolor=color,
                edgecolor="none",
                zorder=zorder,
            )
            self._fig.add_artist(patch)
            self._progress_fill = patch

    def _draw_legend(self) -> None:
        """Add a legend covering connection types and operation roles."""
        handles: list[Line2D | Patch] = [
            Line2D(
                [],
                [],
                color=_LOCAL_EDGE_COLOR,
                linewidth=1.8,
                label="Intra-QPU link",
            ),
            Line2D(
                [],
                [],
                color=_REMOTE_EDGE_COLOR,
                linewidth=1.8,
                linestyle=(0, (5, 4)),
                label="Inter-QPU link",
            ),
            Patch(
                facecolor=_COMM_IDLE_FILL,
                edgecolor=_COMM_IDLE_EDGE,
                label="Communication qubit",
            ),
            Patch(
                facecolor=_COMP_IDLE_FILL,
                edgecolor=_COMP_IDLE_EDGE,
                label="Computation qubit",
            ),
        ]
        handles += [
            Patch(
                facecolor=_ROLE_COLOR[role],
                edgecolor="none",
                label=_PRETTY_ROLE_LEGEND[role],
            )
            for role in _LEGEND_ROLE_ORDER
        ]
        self._ax.legend(
            handles=handles,
            loc="upper left",
            bbox_to_anchor=(1.005, 1.0),
            frameon=False,
            fontsize=8.5,
            handlelength=1.4,
            borderpad=0.0,
        )

    # -- per-frame rendering -----------------------------------------------

    def _render_frame(self, index: int) -> tuple[object, ...]:
        """Update every dynamic artist to depict one frame.

        Args:
            index: Frame index into :attr:`frames`.

        Returns:
            The artists that were updated.
        """
        frame = self._frames[min(index, len(self._frames) - 1)]
        node_roles = self._node_roles(frame)

        faces = list(self._idle_face)
        edges = list(self._idle_edge)
        sizes = [self._node_size] * len(self._nodes)
        for position, node in enumerate(self._nodes):
            role = node_roles.get(node)
            if role is None:
                continue
            faces[position] = _ROLE_COLOR[role]
            edges[position] = _ROLE_COLOR[role]
            sizes[position] = self._node_size * _ACTIVE_NODE_SCALE
        self._node_collection.set_facecolor(faces)
        self._node_collection.set_edgecolor(edges)
        self._node_collection.set_sizes(sizes)

        segments, colors, widths = self._highlighted_links(frame)
        self._highlight_edges.set_segments(segments)
        self._highlight_edges.set_color(colors)
        self._highlight_edges.set_linewidth(widths)

        self._time_text.set_text(
            f"frame {index + 1}/{len(self._frames)}   "
            f"t = {frame.time:,.0f} / {self._schedule.makespan:,.0f} "
            f"time units"
        )
        self._ops_text.set_text(_describe_events(frame))
        span = max(len(self._frames) - 1, 1)
        self._progress_fill.set_width(self._progress_width * (index / span))
        if self._slider is not None and self._playing:
            self._set_slider_silently(index)
        return (
            self._node_collection,
            self._highlight_edges,
            self._time_text,
            self._ops_text,
            self._progress_fill,
        )

    def _node_roles(self, frame: ExecutionFrame) -> dict[PhysicalQubit, str]:
        """Return the winning role for each qubit active in a frame.

        Args:
            frame: Frame to classify.

        Returns:
            Mapping of active qubit to the highest-priority role touching it.
        """
        roles: dict[PhysicalQubit, str] = {}
        for event in frame.events:
            role = _pretty_role(event)
            for node in self._event_nodes[id(event)]:
                current = roles.get(node)
                if current is None or (
                    _ROLE_PRIORITY[role] > _ROLE_PRIORITY[current]
                ):
                    roles[node] = role
        return roles

    def _highlighted_links(
        self, frame: ExecutionFrame
    ) -> tuple[
        list[list[tuple[float, float]]],
        list[tuple[float, float, float, float]],
        list[float],
    ]:
        """Return the drawing data for every link active in a frame.

        A link is active when both of its endpoints take part in the same
        event, which lights up the whole cat-entanglement path of a remote
        gate (data qubit to communication qubit, across the inter-QPU link,
        and back out to the far data qubit).

        Args:
            frame: Frame to inspect.

        Returns:
            Segment coordinates, RGBA colors, and line widths, aligned by
            index. Alpha is folded into the colors because a collection
            rejects an empty per-segment alpha array.

        """
        graph = self._network.graph
        segments: list[list[tuple[float, float]]] = []
        colors: list[tuple[float, float, float, float]] = []
        widths: list[float] = []
        for event in frame.events:
            role = _pretty_role(event)
            involved = self._event_nodes[id(event)]
            if len(involved) < 2:
                continue
            # Entanglement generation fades in as the pair builds up, which
            # makes the long EPR waits legible rather than a static line.
            alpha = 1.0
            if isinstance(event, EntanglementGeneration):
                alpha = 0.35 + 0.65 * _progress(event, frame.time)
            color = to_rgba(_ROLE_COLOR[role], alpha)
            for u, v in graph.subgraph(involved).edges():
                segments.append([self._pos[u], self._pos[v]])
                colors.append(color)
                widths.append(5.5 if role == "remote" else 4.0)
        return segments, colors, widths

    def _event_node_set(self, event: ScheduleEvent) -> set[PhysicalQubit]:
        """Return the physical qubits an event touches.

        Args:
            event: Schedule event to resolve.

        Returns:
            The event's qubits as network graph nodes.
        """
        return {
            self._label_to_node[label]
            for label in event.qubits
            if label in self._label_to_node
        }

    def _default_title(self) -> str:
        """Return a generated title summarizing the animated schedule."""
        return (
            f"Distributed circuit execution — "
            f"{self._network.num_qpus} QPUs, "
            f"{self._network.num_total_qubits} physical qubits, "
            f"{len(self._schedule.operations)} events "
            f"({self._mode} playback)"
        )

    # -- interactive controls ----------------------------------------------

    def _attach_controls(self) -> None:
        """Add play/pause and scrub widgets below the network plot."""
        if self._play_button is not None:
            return
        self._fig.subplots_adjust(bottom=0.16)
        button_ax = self._fig.add_axes((0.06, 0.045, 0.1, 0.055))
        slider_ax = self._fig.add_axes((0.22, 0.06, 0.62, 0.025))

        self._play_button = Button(
            button_ax,
            "Pause",
            color="#ece5f7",
            hovercolor="#d9ccf2",
        )
        self._play_button.on_clicked(self._toggle_play)
        self._slider = Slider(
            slider_ax,
            "frame",
            0,
            max(len(self._frames) - 1, 1),
            valinit=0,
            valstep=1,
            color=_PROGRESS_FILL_COLOR,
        )
        self._slider.on_changed(self._on_slider_changed)

    def _toggle_play(self, _event: object) -> None:
        """Toggle between playing and paused playback.

        Args:
            _event: Matplotlib click event, unused.
        """
        if self._play_button is None:
            return
        if self._playing:
            self._anim.pause()
            self._play_button.label.set_text("Play")
        else:
            self._anim.resume()
            self._play_button.label.set_text("Pause")
        self._playing = not self._playing

    def _on_slider_changed(self, value: float) -> None:
        """Jump to a frame in response to a user scrub.

        Args:
            value: Slider value, interpreted as a frame index.
        """
        if self._playing:
            # A drag during playback pauses first, so the animation timer does
            # not immediately overwrite the frame the user asked for.
            self._toggle_play(None)
        self._render_frame(int(value))
        self._fig.canvas.draw_idle()

    def _set_slider_silently(self, index: int) -> None:
        """Move the slider to follow playback without re-triggering a jump.

        Args:
            index: Frame index to display on the slider.
        """
        slider = self._slider
        if slider is None:
            return
        # ``eventson`` is the widget-level mute switch: it suppresses the
        # on_changed callback so following playback does not read back as a
        # user scrub (which would pause the animation on every frame).
        slider.eventson = False
        try:
            slider.set_val(index)
        finally:
            slider.eventson = True


# --- helpers ---------------------------------------------------------------


def _build_label_index(
    nodes: list[PhysicalQubit],
) -> dict[str, PhysicalQubit]:
    """Map scheduler qubit labels to network graph nodes.

    The scheduler emits physical qubits as ``q<qpu>[<id>]`` for computation
    qubits and ``c<qpu>[<id>]`` for communication qubits, which differs from
    the ``q_<qpu>_<id>`` form :attr:`PhysicalQubit.label` uses. The label is
    rebuilt from each node's own fields rather than parsed from the schedule,
    so the two stay in step.

    Args:
        nodes: Network graph nodes.

    Returns:
        Mapping of scheduler label to node.
    """
    index: dict[str, PhysicalQubit] = {}
    for node in nodes:
        prefix = "c" if node.is_communication else "q"
        index[f"{prefix}{node.qpu_id}[{node.qubit_id}]"] = node
    return index


def _validate_schedule_qubits(
    schedule: OperationSchedule,
    label_to_node: dict[str, PhysicalQubit],
) -> None:
    """Check that every qubit in a schedule exists in the network.

    Args:
        schedule: Schedule to validate.
        label_to_node: Mapping produced by :func:`_build_label_index`.

    Raises:
        ValueError: If the schedule names qubits the network does not have,
            which means the schedule and network do not correspond.
    """
    unknown = sorted(
        {
            label
            for event in schedule.operations
            for label in event.qubits
            if label not in label_to_node
        }
    )
    if unknown:
        raise ValueError(
            "Schedule references qubits that are not in the network graph: "
            f"{', '.join(unknown)}. The schedule must come from the same "
            "network being animated."
        )


def _build_frames(
    schedule: OperationSchedule,
    mode: PlaybackMode,
    num_frames: int,
) -> tuple[ExecutionFrame, ...]:
    """Build the frame list for a schedule.

    Args:
        schedule: Schedule to sample.
        mode: ``"events"`` or ``"time"``.
        num_frames: Frame count, used only in ``"time"`` mode.

    Returns:
        Frames in time order, each carrying the events in flight at its time.
    """
    events = schedule.operations
    if mode == "events":
        times = sorted(
            {event.start_time for event in events}
            | {event.end_time for event in events}
        )
    else:
        count = max(int(num_frames), 2)
        end = max(schedule.makespan, max(e.end_time for e in events))
        times = list(np.linspace(0.0, end, count))

    starts = sorted(event.start_time for event in events)
    by_start = sorted(events, key=lambda event: event.start_time)
    frames: list[ExecutionFrame] = []
    for time in times:
        # Only events that have already started can be in flight, so the
        # scan is bounded by a binary search instead of the whole schedule.
        limit = bisect_right(starts, time)
        active = tuple(
            event for event in by_start[:limit] if _is_active(event, time)
        )
        frames.append(ExecutionFrame(time=float(time), events=active))
    return tuple(frames)


def _is_active(event: ScheduleEvent, time: float) -> bool:
    """Return whether an event is in flight at a time.

    Zero-duration events are treated as active exactly at their start time so
    that instantaneous operations still appear in one frame.

    Args:
        event: Event to test.
        time: Schedule time to test at.

    Returns:
        True when the event occupies its qubits at ``time``.
    """
    if event.duration <= 0.0:
        return time == event.start_time
    return event.start_time <= time < event.end_time


def _progress(event: ScheduleEvent, time: float) -> float:
    """Return how far an event has advanced at a time, in ``[0, 1]``.

    Args:
        event: Event to measure.
        time: Schedule time to measure at.

    Returns:
        Fraction of the event's duration elapsed.
    """
    if event.duration <= 0.0:
        return 1.0
    fraction = (time - event.start_time) / event.duration
    return min(max(fraction, 0.0), 1.0)


def _describe_events(frame: ExecutionFrame) -> str:
    """Return a short multi-line description of a frame's active events.

    Args:
        frame: Frame to describe.

    Returns:
        One line per active event, truncated with a count when there are many.
    """
    if not frame.events:
        return "idle"
    lines = ["executing:"]
    for event in frame.events[:_MAX_ACTIVE_OPS_LISTED]:
        qubits = ", ".join(event.qubits)
        lines.append(f"  {event.name}  ({qubits})")
    remaining = len(frame.events) - _MAX_ACTIVE_OPS_LISTED
    if remaining > 0:
        lines.append(f"  +{remaining} more")
    return "\n".join(lines)


def _edges_of_type(
    graph: nx.Graph,
    connection_type: str,
) -> list[tuple[PhysicalQubit, PhysicalQubit]]:
    """Return the graph edges of one connection type.

    Args:
        graph: Network graph to filter.
        connection_type: ``"local"`` or ``"remote"``.

    Returns:
        Matching edges as endpoint pairs.
    """
    return [
        (u, v)
        for u, v, data in graph.edges(data=True)
        if data.get("connection_type") == connection_type
    ]


#: Blank layout space kept around each QPU cluster for its ring and label.
_CLUSTER_PADDING = 0.24


def _network_radius(num_qpus: int, cluster_scale: float) -> float:
    """Return the radius of the circle the QPU centres are placed on.

    Adjacent centres on a circle of radius ``R`` are ``2 * R * sin(pi / n)``
    apart, so the radius is solved for the separation that keeps padded
    clusters from touching. This keeps large networks legible instead of
    collapsing every cluster into the middle.

    Args:
        num_qpus: Number of QPUs being laid out.
        cluster_scale: Radius of one QPU cluster in layout units.

    Returns:
        The centre-circle radius in layout units.
    """
    if num_qpus < 2:
        return 0.0
    required = cluster_scale + _CLUSTER_PADDING
    return max(1.0, required / math.sin(math.pi / num_qpus))


def _qpu_centre(
    index: int,
    num_qpus: int,
    radius: float,
) -> tuple[float, float]:
    """Return the layout centre for one QPU cluster.

    Args:
        index: Position of the QPU in the ordered QPU list.
        num_qpus: Total number of QPUs being laid out.
        radius: Radius of the circle the centres sit on.

    Returns:
        The cluster's ``(x, y)`` centre.
    """
    if num_qpus == 1:
        return (0.0, 0.0)
    # Starting at pi puts the first QPU on the left, so a two-QPU network
    # reads left-to-right instead of stacking vertically.
    angle = math.pi + 2.0 * math.pi * index / num_qpus
    return (radius * math.cos(angle), radius * math.sin(angle))


def _normalized_offsets(
    positions: dict[PhysicalQubit, np.ndarray],
) -> dict[PhysicalQubit, tuple[float, float]]:
    """Centre and scale a sub-layout into the unit disk.

    Args:
        positions: Raw spring-layout positions for one QPU's qubits.

    Returns:
        Positions recentred on the origin and scaled to radius at most one.
    """
    if not positions:
        return {}
    if len(positions) == 1:
        return {node: (0.0, 0.0) for node in positions}

    xs = [float(point[0]) for point in positions.values()]
    ys = [float(point[1]) for point in positions.values()]
    centre_x = sum(xs) / len(xs)
    centre_y = sum(ys) / len(ys)
    offsets = {
        node: (float(point[0]) - centre_x, float(point[1]) - centre_y)
        for node, point in positions.items()
    }
    extent = max(math.hypot(x, y) for x, y in offsets.values())
    if extent == 0.0:
        return offsets
    return {node: (x / extent, y / extent) for node, (x, y) in offsets.items()}


#: Layout-unit breathing room added around the drawn network.
_CONTENT_MARGIN = 0.30
#: Inches of figure width reserved for the role legend.
_LEGEND_WIDTH_INCHES = 3.2
#: Inches of figure height reserved for titles, status text, and progress bar.
_CHROME_HEIGHT_INCHES = 2.0
_PLOT_WIDTH_INCHES = 8.8
_MIN_PLOT_HEIGHT_INCHES = 2.6
_MAX_PLOT_HEIGHT_INCHES = 9.0


def _content_bounds(
    pos: dict[PhysicalQubit, tuple[float, float]],
) -> tuple[float, float, float, float]:
    """Return padded axis limits enclosing every node position.

    Args:
        pos: Node positions to enclose.

    Returns:
        ``(min_x, max_x, min_y, max_y)`` with a uniform margin applied.
    """
    if not pos:
        return (-1.0, 1.0, -1.0, 1.0)
    xs = [point[0] for point in pos.values()]
    ys = [point[1] for point in pos.values()]
    margin = _CONTENT_MARGIN + _QPU_RING_MARGIN
    return (
        min(xs) - margin,
        max(xs) + margin,
        min(ys) - margin,
        max(ys) + margin,
    )


def _auto_figsize(
    pos: dict[PhysicalQubit, tuple[float, float]],
) -> tuple[float, float]:
    """Return a figure size shaped like the network being drawn.

    The axes hold an equal aspect ratio, so a figure whose proportions ignore
    the layout letterboxes the graph inside a band of whitespace. Deriving the
    height from the content's aspect ratio avoids that.

    Args:
        pos: Node positions the figure must accommodate.

    Returns:
        The ``(width, height)`` figure size in inches.
    """
    min_x, max_x, min_y, max_y = _content_bounds(pos)
    width_span = max(max_x - min_x, 1e-6)
    height_span = max(max_y - min_y, 1e-6)
    plot_height = _PLOT_WIDTH_INCHES * (height_span / width_span)
    plot_height = min(
        max(plot_height, _MIN_PLOT_HEIGHT_INCHES),
        _MAX_PLOT_HEIGHT_INCHES,
    )
    return (
        _PLOT_WIDTH_INCHES + _LEGEND_WIDTH_INCHES,
        plot_height + _CHROME_HEIGHT_INCHES,
    )


def _typical_separation(
    pos: dict[PhysicalQubit, tuple[float, float]],
) -> float:
    """Return a robust estimate of the gap between neighbouring nodes.

    Each node's distance to its nearest neighbour is collected and the lower
    quartile returned. A quartile rather than the strict minimum keeps one
    unusually tight pair from shrinking every node in the figure.

    Args:
        pos: Node positions to measure.

    Returns:
        The lower-quartile nearest-neighbour distance in layout units.
    """
    points = list(pos.values())
    if len(points) < 2:
        return 1.0
    nearest = [
        min(
            math.dist(point, other)
            for index, other in enumerate(points)
            if index != position
        )
        for position, point in enumerate(points)
    ]
    return float(np.percentile(nearest, 25))


def _node_metrics(
    pos: dict[PhysicalQubit, tuple[float, float]],
) -> tuple[float, float]:
    """Return the node marker area and label font size for a layout.

    Matplotlib marker sizes are in typographic points while layouts are in
    arbitrary data units, so the conversion goes through the known width of
    the plotting area.

    Args:
        pos: Node positions the markers must fit between.

    Returns:
        The marker area in points squared, and the label font size in points.
    """
    min_x, max_x, _, _ = _content_bounds(pos)
    width_span = max(max_x - min_x, 1e-6)
    points_per_unit = (_PLOT_WIDTH_INCHES * 72.0) / width_span
    diameter = _NODE_FILL_FRACTION * _typical_separation(pos)
    diameter_pt = min(
        max(diameter * points_per_unit, _MIN_NODE_DIAMETER_PT),
        _MAX_NODE_DIAMETER_PT,
    )
    font_size = min(max(diameter_pt * 0.30, 4.0), 8.0)
    return diameter_pt**2, font_size


__all__ = [
    "ExecutionFrame",
    "NetworkExecutionAnimation",
    "PlaybackMode",
    "animate_circuit_execution",
    "qpu_clustered_layout",
]
