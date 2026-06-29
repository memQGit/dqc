# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================
"""Tests for the Scheduler.plot_gantt convenience method."""

import matplotlib

matplotlib.use("Agg")

import pytest
from matplotlib.axes import Axes

from memq_dqc import Partitioner, Scheduler


def _ran_scheduler(circuit_path, network_path) -> Scheduler:
    partitioner = Partitioner(
        network_path, circuit_path, algo_kwargs={"window_length": 2}
    )
    partitioner.run()
    scheduler = Scheduler(partitioner.distributed_circuit, algo="fifo")
    scheduler.run()
    return scheduler


def test_plot_gantt_returns_axes(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    scheduler = _ran_scheduler(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )

    ax = scheduler.plot_gantt(display="legacy")

    assert isinstance(ax, Axes)


def test_plot_gantt_saves_file(
    tmp_path,
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    scheduler = _ran_scheduler(
        simple1_circuit_path, three_comp_one_comm_x2_network_path
    )
    out_path = tmp_path / "gantt.png"

    scheduler.plot_gantt(display="legacy", save_path=out_path)

    assert out_path.is_file()
    assert out_path.stat().st_size > 0


def test_plot_gantt_requires_schedule(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    partitioner = Partitioner(
        three_comp_one_comm_x2_network_path,
        simple1_circuit_path,
        algo_kwargs={"window_length": 2},
    )
    partitioner.run()
    scheduler = Scheduler(partitioner.distributed_circuit, algo="fifo")

    with pytest.raises(ValueError, match="No schedule available"):
        scheduler.plot_gantt()
