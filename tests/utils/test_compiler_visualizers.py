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

import pytest

from xdqc.circuit import Circuit
from xdqc.network import NetworkGraph
from xdqc.partition import Partitioner
from xdqc.partition.partitioner import QPU
from xdqc.preprocessing.qasm.io import load_qasm_program
from xdqc.visualization import (
    SvgDashboardPanel,
    SvgDashboardSection,
    SvgDocument,
    build_svg_dashboard_html,
    plot_distributed_circuit,
    plot_operation_gantt,
    plot_partition_flow,
    plot_window_activity,
)


def _sample_schedule() -> list[dict[QPU, set[int]]]:
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    return [
        {qpu0: {0, 1}, qpu1: {2, 3}},
        {qpu0: {0, 2}, qpu1: {1, 3}},
        {qpu0: {0, 2}, qpu1: {1, 3}},
        {qpu0: {0, 1}, qpu1: {2, 3}},
    ]


def test_plot_distributed_circuit_marks_remote_gates(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    circuit = Circuit(program)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo_kwargs={"window_length": 3},
    )
    partitioner.run()
    assert partitioner.schedule is not None
    assert partitioner.windows is not None

    document = plot_distributed_circuit(
        circuit,
        schedule=partitioner.schedule,
        windows=partitioner.windows,
    )

    assert isinstance(document, SvgDocument)
    assert "RCX" in document.svg
    assert "State teleportation" in document.svg
    assert "CBITS" not in document.svg


def test_plot_distributed_circuit_renders_measurement_subscript() -> None:
    program = load_qasm_program("examples/circuits/simple1.qasm")
    circuit = Circuit(program)
    network = NetworkGraph("examples/networks/3comp_1comm_x2.json")
    partitioner = Partitioner(
        network,
        program,
        algo_kwargs={"window_length": 3},
    )
    partitioner.run()
    assert partitioner.schedule is not None
    assert partitioner.windows is not None

    document = plot_distributed_circuit(
        circuit,
        schedule=partitioner.schedule,
        windows=partitioner.windows,
    )

    assert isinstance(document, SvgDocument)
    assert "CBITS" in document.svg
    assert "b[0]" in document.svg
    assert 'dasharray="3 5"' in document.svg
    assert 'baseline-shift="sub"' in document.svg


def test_plot_distributed_circuit_rejects_removed_legacy_kwargs(
    bell_circuit_path,
) -> None:
    circuit = Circuit(str(bell_circuit_path))

    with pytest.raises(TypeError, match="unexpected keyword argument 'show'"):
        plot_distributed_circuit(circuit, show=True)


def test_plot_partition_flow_draws_paths() -> None:
    document = plot_partition_flow(_sample_schedule())

    assert isinstance(document, SvgDocument)
    assert "<path" in document.svg
    assert "QPU 0" in document.svg


def test_plot_partition_flow_rejects_removed_legacy_kwargs() -> None:
    with pytest.raises(TypeError, match="unexpected keyword argument 'show'"):
        plot_partition_flow(_sample_schedule(), show=True)


def test_plot_operation_gantt_renders_operation_bars(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    circuit = Circuit(program)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo_kwargs={"window_length": 3},
    )
    partitioner.run()
    assert partitioner.schedule is not None
    assert partitioner.windows is not None

    document = plot_operation_gantt(
        circuit,
        schedule=partitioner.schedule,
        windows=partitioner.windows,
    )

    assert isinstance(document, SvgDocument)
    assert "Operation Gantt" in document.svg
    assert "Time interval" in document.svg
    assert "W0" in document.svg
    assert "RCX" in document.svg


def test_plot_operation_gantt_limits_visible_ops(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    circuit = Circuit(program)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo_kwargs={"window_length": 3},
    )
    partitioner.run()
    assert partitioner.schedule is not None
    assert partitioner.windows is not None

    document = plot_operation_gantt(
        circuit,
        schedule=partitioner.schedule,
        windows=partitioner.windows,
        max_ops_per_window=1,
    )

    assert isinstance(document, SvgDocument)
    assert "+2 ops" in document.svg
    assert "first 1 ops per window" in document.svg


def test_plot_operation_gantt_validates_schedule_and_windows(
    bell_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(bell_circuit_path))
    circuit = Circuit(program)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo_kwargs={"window_length": 1},
    )
    partitioner.run()
    assert partitioner.schedule is not None
    assert partitioner.windows is not None

    with pytest.raises(ValueError, match="same length"):
        plot_operation_gantt(
            circuit,
            schedule=partitioner.schedule[:-1],
            windows=partitioner.windows,
        )


def test_plot_operation_gantt_stacks_parallel_ops_in_same_interval(
    tmp_path,
) -> None:
    qasm_path = tmp_path / "parallel.qasm"
    qasm_path.write_text(
        "\n".join(
            [
                "OPENQASM 3.0;",
                'include "stdgates.inc";',
                "",
                "qubit[2] q;",
                "",
                "h q[0];",
                "x q[1];",
            ]
        ),
        encoding="utf-8",
    )
    circuit = Circuit(str(qasm_path))

    document = plot_operation_gantt(circuit)

    assert isinstance(document, SvgDocument)
    assert "QPU 0" in document.svg
    assert "t0" in document.svg
    assert "t1" not in document.svg


def test_plot_operation_gantt_rejects_removed_legacy_kwargs(
    bell_circuit_path,
) -> None:
    circuit = Circuit(str(bell_circuit_path))

    with pytest.raises(TypeError, match="unexpected keyword argument 'show'"):
        plot_operation_gantt(circuit, show=True)


def test_plot_window_activity_returns_svg(
    simple1_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(simple1_circuit_path))
    circuit = Circuit(program)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo_kwargs={"window_length": 2},
    )
    partitioner.run()
    assert partitioner.schedule is not None
    assert partitioner.windows is not None

    document = plot_window_activity(
        circuit,
        partitioner.schedule,
        partitioner.windows,
    )

    assert isinstance(document, SvgDocument)
    assert "Single-qubit / measure" in document.svg
    assert "Moved qubits" in document.svg


def test_plot_window_activity_validates_schedule_and_windows(
    bell_circuit_path,
    three_comp_one_comm_x2_network_path,
) -> None:
    program = load_qasm_program(str(bell_circuit_path))
    circuit = Circuit(program)
    network = NetworkGraph(str(three_comp_one_comm_x2_network_path))
    partitioner = Partitioner(
        network,
        program,
        algo_kwargs={"window_length": 1},
    )
    partitioner.run()
    assert partitioner.schedule is not None
    assert partitioner.windows is not None

    with pytest.raises(ValueError, match="same length"):
        plot_window_activity(
            circuit,
            partitioner.schedule[:-1],
            partitioner.windows,
        )


def test_plot_window_activity_rejects_removed_legacy_kwargs(
    bell_circuit_path,
) -> None:
    circuit = Circuit(str(bell_circuit_path))

    with pytest.raises(TypeError, match="unexpected keyword argument 'show'"):
        plot_window_activity(circuit, _sample_schedule(), [[]], show=True)


def test_svg_document_writes_interactive_html(tmp_path) -> None:
    document = SvgDocument(
        width=24,
        height=24,
        svg='<svg xmlns="http://www.w3.org/2000/svg"></svg>',
    )

    output_path = document.write_html(
        tmp_path / "viewer.html",
        title="Viewer Smoke Test",
    )

    html = output_path.read_text(encoding="utf-8")
    assert "Viewer Smoke Test" in html
    assert 'data-action="fit"' in html
    assert 'class="viewer__svg"' in html


def test_build_svg_dashboard_html_renders_sections() -> None:
    document = SvgDocument(
        width=24,
        height=24,
        svg=(
            '<svg xmlns="http://www.w3.org/2000/svg" '
            'width="24" height="24"></svg>'
        ),
    )

    html = build_svg_dashboard_html(
        [
            SvgDashboardSection(
                title="Sample Case",
                description="Combined output for one partitioning run.",
                panels=[
                    SvgDashboardPanel(
                        title="Distributed circuit",
                        document=document,
                        description="Circuit-level view.",
                    )
                ],
            )
        ],
        title="Visualization Dashboard",
    )

    assert "Visualization Dashboard" in html
    assert "Sample Case" in html
    assert "Distributed circuit" in html
    assert "Combined output for one partitioning run." in html
    assert 'class="dashboard-card__svg"' in html
