# xDQC Demos

Runnable notebooks covering the library. Launch them from the repository root
so the kernel starts in this directory:

```bash
uv sync
uv run jupyter lab demo/
```

Every path inside the notebooks is relative to `demo/`. Inputs live in
`inputs/`; each notebook writes its artifacts to `outputs/`.

## Recommended order

| Notebook | What it covers |
| --- | --- |
| [`demo.ipynb`](demo.ipynb) | **Start here.** The whole pipeline end to end: compile, verify, schedule. |
| [`networks.ipynb`](networks.ipynb) | The topology file format, building networks programmatically, routing and e-bit cost. |
| [`comparing_partitioners.ipynb`](comparing_partitioners.ipynb) | Benchmarking all five partitioning algorithms across two topologies. |
| [`scheduling_and_hardware.ipynb`](scheduling_and_hardware.ipynb) | Scheduling strategies, hardware modalities, entanglement profiles, and parameter overrides. |
| [`visualization.ipynb`](visualization.ipynb) | Every renderer: circuit DAGs, partition views, Gantt charts, dashboards, and animated playback. |

## Inputs

| File | What it is |
| --- | --- |
| `inputs/qft_n4.qasm` | 4-qubit Quantum Fourier Transform |
| `inputs/qft_12.qasm` | 12-qubit Quantum Fourier Transform |
| `inputs/demo_network.json` | 2 QPUs, 2 computation + 2 communication qubits each |
| `inputs/chain_3qpu.json` | 3 QPUs in a line |
| `inputs/ring_4qpu.json` | 4 QPUs in a ring |
