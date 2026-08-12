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
"""Tests for the Scheduler.plot_gantt convenience method."""

import matplotlib

matplotlib.use("Agg")

import pytest
from matplotlib.axes import Axes

from xdqc import Partitioner, Scheduler


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
