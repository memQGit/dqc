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

"""Visualization helpers for xdqc."""

from xdqc.visualization.compiler_visualizer import (
    plot_distributed_circuit,
    plot_operation_gantt,
    plot_partition_flow,
    plot_window_activity,
)
from xdqc.visualization.dag_visualizer import (
    build_dag_networkx_graph,
    plot_circuit_dag,
    plot_dag,
    plot_distributed_dag,
)
from xdqc.visualization.execution_animator import (
    ExecutionFrame,
    NetworkExecutionAnimation,
    animate_circuit_execution,
    qpu_clustered_layout,
)
from xdqc.visualization.partition_visualizer import (
    plot_migration_timeline,
    plot_partition_heatmap,
)
from xdqc.visualization.svg_document import (
    SvgDashboardPanel,
    SvgDashboardSection,
    SvgDocument,
    build_svg_dashboard_html,
    write_svg_dashboard_html,
)

__all__ = [
    "ExecutionFrame",
    "NetworkExecutionAnimation",
    "SvgDashboardPanel",
    "SvgDashboardSection",
    "SvgDocument",
    "animate_circuit_execution",
    "build_svg_dashboard_html",
    "build_dag_networkx_graph",
    "plot_circuit_dag",
    "plot_dag",
    "plot_distributed_circuit",
    "plot_distributed_dag",
    "plot_migration_timeline",
    "plot_operation_gantt",
    "plot_partition_flow",
    "plot_partition_heatmap",
    "plot_window_activity",
    "qpu_clustered_layout",
    "write_svg_dashboard_html",
]
