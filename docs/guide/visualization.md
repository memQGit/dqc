# Visualization

`memq_dqc.visualization` provides SVG- and matplotlib-based views of the
compilation output — useful for inspecting how a circuit was partitioned and
scheduled.

```python
from memq_dqc.visualization import (
    plot_distributed_circuit,   # gate layout across QPUs
    plot_partition_flow,        # qubit migration across QPUs
    plot_partition_heatmap,     # QPU assignment heatmap per window
    plot_migration_timeline,    # qubit movement timeline with EPR cost
    plot_circuit_dag,           # circuit DAG
    plot_operation_gantt,       # operation Gantt chart
    plot_schedule_gantt,        # schedule Gantt chart
    write_svg_dashboard_html,   # bundle panels into an HTML viewer
)
```

## Schedule Gantt charts

The `Scheduler` exposes a convenience method that renders the execution
schedule directly:

```python
scheduler.plot_gantt(
    title="Execution schedule",
    save_path="schedule_gantt.png",
)
```

Each row is a physical qubit: communication qubits (`c…`) generate
entanglement and run the cat-entanglement halves of each remote gate, while
data qubits (`q…`) carry the local gates and measurements.

## Dashboards

`write_svg_dashboard_html` bundles multiple panels into a single standalone
HTML viewer — a convenient artifact to share a full compilation result without
running any code. See the
[`memq_dqc.visualization` API reference](../reference/memq_dqc/visualization/index.md) for the
full list of plotting functions and the `SvgDocument` primitives.
