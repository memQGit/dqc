"""Discrete-time ILP scheduler for distributed circuits."""

from __future__ import annotations

import math
import sys
import threading
import time
from dataclasses import dataclass
from typing import cast

import networkx as nx
import pulp

from memq_dqc.circuit import DistributedCircuit, Op
from memq_dqc.network import PhysicalQubit
from memq_dqc.scheduler.schedule import (
    DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE,
    DEFAULT_SCHEDULER_MODALITY,
    BaseScheduler,
    EntanglementGeneration,
    OperationSchedule,
    ScheduledOperation,
    ScheduleEvent,
    SchedulerEntanglementProfile,
    SchedulerHardwareProfile,
    SchedulerModality,
    _build_qubit_timelines,
    _catent_ebit_labels,
    _ebit_assignment_labels,
    _is_catent_operation,
    _operation_duration,
    _physical_qubit_label,
    _remote_ebit_assignment_candidates,
    _remote_operation_qubit_labels,
    _remote_ops_with_catent_predecessor,
)

_PROGRESS_BAR_WIDTH = 24
_PROGRESS_REFRESH_SECONDS = 0.1
_SOLVER_WAIT_MESSAGE = "Solving ILP"
_INTEGRAL_TOLERANCE = 1e-9
_BINARY_TOLERANCE = 1e-6
_ILP_TIME_STEP = 1.0


@dataclass(frozen=True, slots=True)
class _EprWindow:
    """One just-in-time EPR window tied to a remote operation start."""

    pair_index: int
    qubits: tuple[str, str]
    duration_steps: int
    duration_time: float
    start_offset_steps: int


@dataclass(frozen=True, slots=True)
class _OperationMode:
    """One scheduler-selectable resource mode for an operation."""

    mode_index: int
    qubits: tuple[str, ...]
    epr_windows: tuple[_EprWindow, ...]

    @property
    def earliest_start(self) -> int:
        """Return the earliest non-negative start for this mode."""
        if not self.epr_windows:
            return 0
        return max(window.start_offset_steps for window in self.epr_windows)


@dataclass(frozen=True, slots=True)
class _OperationActivity:
    """Discrete-time activity data for one circuit operation."""

    op: Op
    duration: float
    duration_steps: int
    modes: tuple[_OperationMode, ...]

    @property
    def earliest_start(self) -> int:
        """Return the earliest non-negative start across operation modes."""
        return min(mode.earliest_start for mode in self.modes)


class _ProgressReporter:
    """Emit simple terminal progress for long-running scheduler phases."""

    def __init__(self, *, enabled: bool, total_steps: int) -> None:
        self._enabled = enabled
        self._total_steps = max(total_steps, 1)
        self._current_step = 0
        self._spinner_stop = threading.Event()
        self._spinner_thread: threading.Thread | None = None

    def advance(self, message: str) -> None:
        """Advance the finite progress bar to the next phase."""
        if not self._enabled:
            return

        self._current_step = min(self._current_step + 1, self._total_steps)
        filled = math.floor(
            (_PROGRESS_BAR_WIDTH * self._current_step) / self._total_steps
        )
        bar = ("#" * filled).ljust(_PROGRESS_BAR_WIDTH, "-")
        self._write(
            f"[{bar}] {self._current_step}/{self._total_steps} {message}"
        )

    def start_spinner(self, message: str = _SOLVER_WAIT_MESSAGE) -> None:
        """Start an indeterminate progress spinner for the solver call."""
        if not self._enabled:
            return

        self.stop_spinner(message="Preparing solve output")
        self._spinner_stop.clear()
        self._write(f"[{'-' * _PROGRESS_BAR_WIDTH}] {message}    0.0s")
        self._spinner_thread = threading.Thread(
            target=self._spin,
            args=(message,),
            daemon=True,
        )
        self._spinner_thread.start()

    def stop_spinner(self, *, message: str = "Solver finished") -> None:
        """Stop the active solver spinner, if any."""
        if not self._enabled or self._spinner_thread is None:
            return

        self._spinner_stop.set()
        self._spinner_thread.join()
        self._spinner_thread = None
        self._write(f"[{'#' * _PROGRESS_BAR_WIDTH}] {message}")

    def _spin(self, message: str) -> None:
        frames = (
            "[#-----------------------]",
            "[###---------------------]",
            "[#####-------------------]",
            "[#######-----------------]",
            "[#########---------------]",
            "[###########-------------]",
            "[#############-----------]",
            "[###############---------]",
            "[#################-------]",
            "[###################-----]",
            "[#####################---]",
            "[#######################-]",
        )
        start_time = time.perf_counter()
        frame_index = 0
        while not self._spinner_stop.wait(_PROGRESS_REFRESH_SECONDS):
            elapsed = time.perf_counter() - start_time
            frame = frames[frame_index % len(frames)]
            self._write(f"{frame} {message} {elapsed:6.1f}s")
            frame_index += 1

    def _write(self, message: str) -> None:
        sys.stderr.write(f"\r{message.ljust(80)}")
        sys.stderr.flush()

    def finish(self) -> None:
        """Terminate progress output on a fresh terminal line."""
        if not self._enabled:
            return
        sys.stderr.write("\n")
        sys.stderr.flush()


class ILPScheduler(BaseScheduler):
    """Schedule a distributed circuit with a discrete-time ILP model."""

    def __init__(
        self,
        distributed_circuit: DistributedCircuit,
        *,
        profile: SchedulerHardwareProfile | None = None,
        modality: SchedulerModality = DEFAULT_SCHEDULER_MODALITY,
        entanglement_profile: SchedulerEntanglementProfile = (
            DEFAULT_SCHEDULER_ENTANGLEMENT_PROFILE
        ),
        multiplex_entangle: bool = True,
        show_progress: bool = True,
    ) -> None:
        """Initialize the ILP scheduler configuration.

        Args:
            distributed_circuit: Distributed circuit DAG to schedule.
            profile: Optional convenience object selecting both modality and
                entanglement profile. When provided, ``modality`` and
                ``entanglement_profile`` must be left at their defaults.
            modality: Hardware timing profile used for local 1Q/2Q gate
                durations. Defaults to ``"trapped_ion.ba"`` (Ba+ trapped ion).
            entanglement_profile: Entanglement-generation profile used for
                entanglement timing. Defaults to ``"ion.time_bin"``.
            multiplex_entangle: Whether EPR generation for multi-pair remote
                operations can overlap.
            show_progress: Whether to print a terminal progress bar and solver
                spinner while building and solving the ILP.
        """
        super().__init__(
            distributed_circuit,
            profile=profile,
            modality=modality,
            entanglement_profile=entanglement_profile,
            multiplex_entangle=multiplex_entangle,
        )
        self.show_progress = show_progress
        self.time_step = _ILP_TIME_STEP

    def run(self) -> None:
        """Build an operation schedule using a discrete-time ILP."""
        reporter = _ProgressReporter(enabled=self.show_progress, total_steps=5)
        try:
            reporter.advance("Preparing activities")
            activities = self._build_activities()
            qubit_order = self._build_qubit_order(activities)
            if not activities:
                self.schedule = OperationSchedule(
                    operations=(),
                    timelines=(),
                    makespan=0.0,
                )
                return

            reporter.advance("Computing horizon")
            horizon = self._build_horizon(activities)
            earliest_starts = self._build_earliest_starts(activities)
            latest_starts = self._build_latest_starts(activities, horizon)

            reporter.advance("Creating ILP variables")
            problem = pulp.LpProblem("memq_dqc_ilp_schedule", pulp.LpMinimize)
            start_variables = self._build_start_variables(
                activities=activities,
                earliest_starts=earliest_starts,
                latest_starts=latest_starts,
            )
            start_expressions = {
                op_id: pulp.lpSum(
                    start_time * variable
                    for (_, start_time), variable in variables.items()
                )
                for op_id, variables in start_variables.items()
            }
            c_max = pulp.LpVariable(
                "c_max",
                lowBound=0,
                upBound=horizon,
                cat=pulp.LpInteger,
            )

            reporter.advance("Adding constraints")
            self._add_unique_start_constraints(problem, start_variables)
            self._add_precedence_constraints(
                problem=problem,
                activities=activities,
                start_expressions=start_expressions,
            )
            self._add_resource_constraints(
                problem=problem,
                activities=activities,
                start_variables=start_variables,
                horizon=horizon,
            )
            self._add_makespan_constraints(
                problem=problem,
                activities=activities,
                start_expressions=start_expressions,
                c_max=c_max,
            )
            problem += self._build_objective(
                activities=activities,
                start_expressions=start_expressions,
                c_max=c_max,
                horizon=horizon,
            )

            reporter.start_spinner()
            solver = pulp.PULP_CBC_CMD(msg=False)
            problem.solve(solver)
        finally:
            reporter.stop_spinner()
            reporter.finish()

        status = pulp.LpStatus[problem.status]
        if status != "Optimal":
            raise RuntimeError(
                "ILP scheduler failed to find an optimal solution: "
                f"status={status}."
            )

        reporter.advance("Reconstructing schedule")
        selected_modes = self._extract_selected_modes(start_variables)
        scheduled_operations = self._build_schedule_events(
            activities=activities,
            selected_modes=selected_modes,
        )
        makespan = max(
            (
                scheduled_event.end_time
                for scheduled_event in scheduled_operations
            ),
            default=0.0,
        )
        self.schedule = OperationSchedule(
            operations=tuple(scheduled_operations),
            timelines=_build_qubit_timelines(
                scheduled_operations, qubit_order
            ),
            makespan=makespan,
        )

    def _build_activities(self) -> dict[int, _OperationActivity]:
        if not self.distributed_circuit.ops:
            return {}

        activities: dict[int, _OperationActivity] = {}
        for op in self.distributed_circuit.ops:
            duration = _operation_duration(op, self.timing_model)
            duration_steps = _duration_to_steps(duration, self.time_step)
            activities[op.op_id] = _OperationActivity(
                op=op,
                duration=_steps_to_time(duration_steps, self.time_step),
                duration_steps=duration_steps,
                modes=self._build_modes(op),
            )
        return activities

    def _build_modes(self, op: Op) -> tuple[_OperationMode, ...]:
        """Build scheduler resource modes for one operation."""
        if _is_catent_operation(op):
            if len(op.qubits) == 2:
                modes: list[_OperationMode] = []
                for mode_index, assignment in enumerate(
                    _remote_ebit_assignment_candidates(
                        self.distributed_circuit,
                        op,
                    )
                ):
                    modes.append(
                        _OperationMode(
                            mode_index=mode_index,
                            qubits=_remote_operation_qubit_labels(
                                op,
                                assignment,
                            ),
                            epr_windows=self._build_epr_windows(assignment),
                        )
                    )
                return tuple(modes)

            return (
                _OperationMode(
                    mode_index=0,
                    qubits=tuple(
                        _physical_qubit_label(qubit) for qubit in op.qubits
                    ),
                    epr_windows=self._build_epr_windows_from_labels(
                        _catent_ebit_labels(op)
                    ),
                ),
            )

        if not op.is_remote:
            return (
                _OperationMode(
                    mode_index=0,
                    qubits=tuple(
                        _physical_qubit_label(qubit) for qubit in op.qubits
                    ),
                    epr_windows=(),
                ),
            )

        if op.op_id in _remote_ops_with_catent_predecessor(
            self.distributed_circuit
        ):
            return (
                _OperationMode(
                    mode_index=0,
                    qubits=tuple(
                        _physical_qubit_label(qubit) for qubit in op.qubits
                    ),
                    epr_windows=(),
                ),
            )

        modes: list[_OperationMode] = []
        for mode_index, assignment in enumerate(
            _remote_ebit_assignment_candidates(self.distributed_circuit, op)
        ):
            modes.append(
                _OperationMode(
                    mode_index=mode_index,
                    qubits=_remote_operation_qubit_labels(op, assignment),
                    epr_windows=self._build_epr_windows(assignment),
                )
            )
        return tuple(modes)

    def _build_epr_windows(
        self,
        assignment: tuple[tuple[PhysicalQubit, PhysicalQubit], ...],
    ) -> tuple[_EprWindow, ...]:
        """Build just-in-time EPR windows for one e-bit assignment."""
        return self._build_epr_windows_from_labels(
            _ebit_assignment_labels(assignment)
        )

    def _build_epr_windows_from_labels(
        self,
        pair_labels: tuple[tuple[str, str], ...],
    ) -> tuple[_EprWindow, ...]:
        """Build just-in-time EPR windows for labeled e-bit pairs."""
        duration_steps = _duration_to_steps(
            self.timing_model.entanglement_time,
            self.time_step,
        )
        duration_time = _steps_to_time(duration_steps, self.time_step)
        if self.multiplex_entangle or len(pair_labels) == 1:
            return tuple(
                _EprWindow(
                    pair_index=index,
                    qubits=pair,
                    duration_steps=duration_steps,
                    duration_time=duration_time,
                    start_offset_steps=duration_steps,
                )
                for index, pair in enumerate(pair_labels)
            )

        total_pairs = len(pair_labels)
        return tuple(
            _EprWindow(
                pair_index=index,
                qubits=pair,
                duration_steps=duration_steps,
                duration_time=duration_time,
                start_offset_steps=(total_pairs - index) * duration_steps,
            )
            for index, pair in enumerate(pair_labels)
        )

    def _build_qubit_order(
        self,
        activities: dict[int, _OperationActivity],
    ) -> tuple[str, ...]:
        qubit_order: list[str] = []
        seen_qubits: set[str] = set()
        for op in self.distributed_circuit.ops:
            for mode in activities[op.op_id].modes:
                for qubit in mode.qubits:
                    if qubit in seen_qubits:
                        continue
                    seen_qubits.add(qubit)
                    qubit_order.append(qubit)
        return tuple(qubit_order)

    def _build_horizon(self, activities: dict[int, _OperationActivity]) -> int:
        makespan_upper_bound = self._build_fifo_upper_bound(activities)
        if makespan_upper_bound <= 0:
            return 0
        return makespan_upper_bound

    def _build_fifo_upper_bound(
        self,
        activities: dict[int, _OperationActivity],
    ) -> int:
        qubit_timers: dict[str, int] = {}
        for layer in self.distributed_circuit.dag.layers:
            for op in layer:
                activity = activities[op.op_id]
                best_start_time: int | None = None
                best_mode: _OperationMode | None = None
                for mode in activity.modes:
                    for qubit in mode.qubits:
                        qubit_timers.setdefault(qubit, 0)

                    start_time = max(
                        (qubit_timers[qubit] for qubit in mode.qubits),
                        default=0,
                    )
                    if mode.epr_windows:
                        data_qubits = mode.qubits[:2]
                        start_time = max(
                            (qubit_timers[qubit] for qubit in data_qubits),
                            default=0,
                        )
                        if (
                            self.multiplex_entangle
                            or len(mode.epr_windows) == 1
                        ):
                            start_time = max(
                                start_time,
                                max(
                                    max(
                                        qubit_timers[window.qubits[0]],
                                        qubit_timers[window.qubits[1]],
                                    )
                                    + window.duration_steps
                                    for window in mode.epr_windows
                                ),
                            )
                        else:
                            total_pairs = len(mode.epr_windows)
                            for index, window in enumerate(mode.epr_windows):
                                slot_count = total_pairs - index
                                pair_ready = max(
                                    qubit_timers[window.qubits[0]],
                                    qubit_timers[window.qubits[1]],
                                )
                                start_time = max(
                                    start_time,
                                    pair_ready
                                    + (slot_count * window.duration_steps),
                                )

                    if best_start_time is None or start_time < best_start_time:
                        best_start_time = start_time
                        best_mode = mode

                if best_start_time is None or best_mode is None:
                    raise RuntimeError(
                        f"Operation {op.op_id} has no ILP activity modes."
                    )

                end_time = best_start_time + activity.duration_steps
                for qubit in best_mode.qubits:
                    qubit_timers[qubit] = end_time
        return max(qubit_timers.values(), default=0)

    def _build_earliest_starts(
        self,
        activities: dict[int, _OperationActivity],
    ) -> dict[int, int]:
        graph = self.distributed_circuit.dag.graph
        earliest_starts: dict[int, int] = {}
        for op_id in nx.topological_sort(graph):
            activity = activities[op_id]
            predecessors = tuple(graph.predecessors(op_id))
            earliest_start = activity.earliest_start
            if predecessors:
                earliest_start = max(
                    earliest_start,
                    max(
                        earliest_starts[predecessor]
                        + activities[predecessor].duration_steps
                        for predecessor in predecessors
                    ),
                )
            earliest_starts[op_id] = earliest_start
        return earliest_starts

    def _build_latest_starts(
        self,
        activities: dict[int, _OperationActivity],
        horizon: int,
    ) -> dict[int, int]:
        graph = self.distributed_circuit.dag.graph
        latest_starts: dict[int, int] = {}
        reverse_order = list(nx.topological_sort(graph))
        reverse_order.reverse()
        for op_id in reverse_order:
            activity = activities[op_id]
            latest_start = horizon - activity.duration_steps
            successors = tuple(graph.successors(op_id))
            if successors:
                latest_start = min(
                    latest_start,
                    min(
                        latest_starts[successor] - activity.duration_steps
                        for successor in successors
                    ),
                )
            latest_starts[op_id] = max(latest_start, activity.earliest_start)
        return latest_starts

    def _build_start_variables(
        self,
        *,
        activities: dict[int, _OperationActivity],
        earliest_starts: dict[int, int],
        latest_starts: dict[int, int],
    ) -> dict[int, dict[tuple[int, int], pulp.LpVariable]]:
        start_variables: dict[int, dict[tuple[int, int], pulp.LpVariable]] = {}
        for op_id in earliest_starts:
            earliest_start = earliest_starts[op_id]
            latest_start = latest_starts[op_id]
            if latest_start < earliest_start:
                raise RuntimeError(
                    "ILP scheduler computed an invalid start domain for "
                    f"operation {op_id}: [{earliest_start}, {latest_start}]."
                )

            start_variables[op_id] = {}
            for mode in activities[op_id].modes:
                mode_earliest_start = max(
                    earliest_start,
                    mode.earliest_start,
                )
                for start_time in range(mode_earliest_start, latest_start + 1):
                    start_variables[op_id][(mode.mode_index, start_time)] = (
                        pulp.LpVariable(
                            f"start_{op_id}_{mode.mode_index}_{start_time}",
                            cat=pulp.LpBinary,
                        )
                    )
            if not start_variables[op_id]:
                raise RuntimeError(
                    f"ILP scheduler found no feasible starts for operation {op_id}."
                )
        return start_variables

    def _add_unique_start_constraints(
        self,
        problem: pulp.LpProblem,
        start_variables: dict[int, dict[tuple[int, int], pulp.LpVariable]],
    ) -> None:
        for op_id, variables in start_variables.items():
            problem += (
                pulp.lpSum(variables.values()) == 1,
                f"unique_start_{op_id}",
            )

    def _add_precedence_constraints(
        self,
        *,
        problem: pulp.LpProblem,
        activities: dict[int, _OperationActivity],
        start_expressions: dict[int, pulp.LpAffineExpression],
    ) -> None:
        graph = self.distributed_circuit.dag.graph
        for predecessor, successor in graph.edges:
            problem += (
                start_expressions[successor]
                >= start_expressions[predecessor]
                + activities[predecessor].duration_steps,
                f"precedence_{predecessor}_{successor}",
            )

    def _add_resource_constraints(
        self,
        *,
        problem: pulp.LpProblem,
        activities: dict[int, _OperationActivity],
        start_variables: dict[int, dict[tuple[int, int], pulp.LpVariable]],
        horizon: int,
    ) -> None:
        qubit_terms: dict[tuple[str, int], list[pulp.LpVariable]] = {}
        for activity in activities.values():
            modes_by_index = {mode.mode_index: mode for mode in activity.modes}
            for (mode_index, start_time), variable in start_variables[
                activity.op.op_id
            ].items():
                mode = modes_by_index[mode_index]
                for active_time in range(
                    start_time,
                    start_time + activity.duration_steps,
                ):
                    for qubit in mode.qubits:
                        qubit_terms.setdefault(
                            (qubit, active_time), []
                        ).append(variable)
                for window in mode.epr_windows:
                    epr_start_time = start_time - window.start_offset_steps
                    for active_time in range(
                        epr_start_time,
                        epr_start_time + window.duration_steps,
                    ):
                        for qubit in window.qubits:
                            qubit_terms.setdefault(
                                (qubit, active_time), []
                            ).append(variable)

        for (qubit, active_time), terms in qubit_terms.items():
            if active_time < 0 or active_time >= horizon:
                raise RuntimeError(
                    "ILP scheduler built an out-of-range resource term for "
                    f"{qubit} at time {active_time}."
                )
            if len(terms) <= 1:
                continue
            problem += (
                pulp.lpSum(terms) <= 1,
                f"resource_{_sanitize_name(qubit)}_{active_time}",
            )

    def _add_makespan_constraints(
        self,
        *,
        problem: pulp.LpProblem,
        activities: dict[int, _OperationActivity],
        start_expressions: dict[int, pulp.LpAffineExpression],
        c_max: pulp.LpVariable,
    ) -> None:
        for op_id, activity in activities.items():
            problem += (
                c_max >= start_expressions[op_id] + activity.duration_steps,
                f"makespan_{op_id}",
            )

    def _build_objective(
        self,
        *,
        activities: dict[int, _OperationActivity],
        start_expressions: dict[int, pulp.LpAffineExpression],
        c_max: pulp.LpVariable,
        horizon: int,
    ) -> pulp.LpAffineExpression:
        secondary_weight = (len(activities) * max(horizon, 1)) + 1
        return (secondary_weight * c_max) + pulp.lpSum(
            start_expressions.values()
        )

    def _extract_selected_modes(
        self,
        start_variables: dict[int, dict[tuple[int, int], pulp.LpVariable]],
    ) -> dict[int, tuple[int, int]]:
        selected_modes: dict[int, tuple[int, int]] = {}
        for op_id, variables in start_variables.items():
            chosen_modes: list[tuple[int, int]] = []
            for mode_and_start, variable in variables.items():
                variable_value = cast(float | None, pulp.value(variable))
                if variable_value is None:
                    continue
                if float(variable_value) > 1.0 - _BINARY_TOLERANCE:
                    chosen_modes.append(mode_and_start)
            if len(chosen_modes) != 1:
                raise RuntimeError(
                    "ILP scheduler expected exactly one selected start for "
                    f"operation {op_id}, found {chosen_modes!r}."
                )
            selected_modes[op_id] = chosen_modes[0]
        return selected_modes

    def _build_schedule_events(
        self,
        *,
        activities: dict[int, _OperationActivity],
        selected_modes: dict[int, tuple[int, int]],
    ) -> list[ScheduleEvent]:
        ordered_events: list[
            tuple[tuple[int, int, int, int], ScheduleEvent]
        ] = []
        for op in self.distributed_circuit.ops:
            activity = activities[op.op_id]
            selected_mode_index, op_start_step = selected_modes[op.op_id]
            mode = next(
                mode
                for mode in activity.modes
                if mode.mode_index == selected_mode_index
            )
            op_start_time = _steps_to_time(op_start_step, self.time_step)
            for window in mode.epr_windows:
                epr_start_step = op_start_step - window.start_offset_steps
                ordered_events.append(
                    (
                        (epr_start_step, 1, op.op_id, window.pair_index),
                        EntanglementGeneration(
                            qubits=window.qubits,
                            start_time=_steps_to_time(
                                epr_start_step,
                                self.time_step,
                            ),
                            duration=window.duration_time,
                        ),
                    )
                )

            ordered_events.append(
                (
                    (op_start_step, 0, op.op_id, 0),
                    ScheduledOperation(
                        op_id=op.op_id,
                        statement_id=op.statement_id,
                        name=op.name,
                        qubits=mode.qubits,
                        start_time=op_start_time,
                        duration=activity.duration,
                        is_remote=op.is_remote,
                    ),
                )
            )

        ordered_events.sort(key=lambda item: item[0])
        return [event for _, event in ordered_events]


def _duration_to_steps(duration: float, time_step: float) -> int:
    """Convert a floating-point duration into discrete scheduler steps."""
    if duration <= 0.0:
        raise ValueError(
            f"Scheduler durations must be positive, received {duration}."
        )
    scaled_duration = duration / time_step
    nearest_integer = round(scaled_duration)
    if abs(scaled_duration - nearest_integer) <= _INTEGRAL_TOLERANCE:
        return max(int(nearest_integer), 1)
    return max(math.ceil(scaled_duration - _INTEGRAL_TOLERANCE), 1)


def _steps_to_time(steps: int, time_step: float) -> float:
    """Convert integer scheduler steps back into schedule time units."""
    return float(steps * time_step)


def _sanitize_name(value: str) -> str:
    """Return a solver-safe identifier fragment."""
    return value.replace("[", "_").replace("]", "").replace(".", "_")
