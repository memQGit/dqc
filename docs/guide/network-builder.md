# Network Builder

Writing a topology JSON file by hand gets tedious past a few QPUs. The
**network builder** is a small local web app, shipped with xDQC, for drawing
a network in the browser and exporting it as a topology file the compiler can
load directly.

It is a convenience tool, not part of the compiler: nothing in the
compilation pipeline imports it, and the file it produces is an ordinary
topology JSON of the kind described in
[Defining Networks](../demos/networks.ipynb).

## Launching it

The builder needs Flask, which ships as the optional `builder` extra:

```bash
pip install "xdqc[builder]"
```

From a clone, `uv sync` already installs it. Either way, one command starts
the server and opens the app in your default browser:

```bash
uv run network-builder
```

The app serves on `http://127.0.0.1:8010` — port 8010 rather than 8000 so it
does not collide with `mkdocs serve`. Press `Ctrl+C` to stop it.

If 8010 is taken, or you want several builders side by side, pass `--port`:

```bash
uv run network-builder --port 8020
```

| Flag | Effect |
| --- | --- |
| `--port PORT` | Serve on a different port. Default `8010`. |
| `--host HOST` | Bind a different interface. Default `127.0.0.1`. |
| `--no-browser` | Start the server without opening a browser. |

!!! warning "Localhost by default"
    The builder binds to `127.0.0.1` and runs Flask's development server.
    Passing `--host 0.0.0.0` exposes it to your whole network; there is no
    authentication, so only do that on a network you trust.

## Building a network

Two ways to produce a topology, both ending in a downloaded `.json` file:

**Draw one.** *Add Processor* creates a QPU, *Add Qubit* adds qubits to the
selected QPU, and *Local Connect* / *Remote Connect* link two qubits by
clicking each in turn. A qubit becomes a **communication** qubit as soon as it
gains a remote connection, and a **computation** qubit otherwise — you do not
set the type by hand. *Save As* downloads the result.

**Generate one.** The *Generator* panel builds a whole family at once from a
QPU count and per-QPU qubit counts: homogeneous line, ring, hub, all-to-all,
and grid topologies, each in large, small, and tiny variants. This is the
faster route for benchmarking sweeps, where you want the same circuit against
a dozen topologies.

*Generate Graph* renders a NetworkX preview of the current design. The preview
is validated by the same
[`NetworkGraph`][xdqc.network.NetworkGraph] the compiler uses, so if a network
renders here, it loads there — and if it is malformed, the error you see is
the one the library would raise.

## Using the result

The exported file drops straight into the standard workflow:

```python
from xdqc.compiler import Compiler
from xdqc.network import NetworkGraph

network = NetworkGraph("my_network.json")
compiler = Compiler("circuit.qasm", network)
```

See [Workflow & Architecture](workflow.md) for what happens next.

## Metadata reserved for future use

The builder writes two fields that no xDQC algorithm reads today:

- **`coherenceTime`** (per qubit, microseconds) — set with the *Qubit
  Coherence* sliders.
- **`fidelity`** (per remote link, 0 to 1) — set with the *Remote Link
  Fidelity* sliders.

Both are carried through the file format and shown in the preview, but no
current partitioner or scheduler consumes them. They are recorded now so that
networks built today remain useful to coherence- and fidelity-aware
algorithms later. Setting them changes nothing about compilation or scheduling
results in the meantime.
