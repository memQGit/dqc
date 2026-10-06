# MCP Server

DQC ships a [Model Context Protocol](https://modelcontextprotocol.io) (MCP)
server that exposes the compile → verify → schedule workflow as tools. Any
MCP client (Claude Desktop, Claude Code, Cursor, and others) can then drive
the compiler from a plain-language request, such as *"compare every
partitioner on `qft_n10` over a 3-QPU ring and tell me which has the
shortest makespan"*.

Like the [network builder](network-builder.md), it is a convenience layer,
not part of the compiler: it calls the same public API you would call from
Python, and nothing in the compilation pipeline imports it.

## Setting it up

!!! tip "Let an agent do it"
    [MCP Setup via an AI Agent](mcp-agent-setup.md) is a page you can paste
    into Claude Code, Cursor, or a similar agent. It checks what you already
    have, installs what is missing, and registers the server with your
    client.

The server is built on [FastMCP](https://gofastmcp.com), which ships as the
optional `mcp` extra. It runs locally over stdio: the client launches it as
a subprocess and talks to it over stdin/stdout, so nothing leaves your
machine except what the client itself sends to its model provider.

### If memq-dqc is already installed

Add the extra to the same environment. Keep `--upgrade`: releases before the
MCP server have no `mcp` extra, and pip would otherwise report the
requirement as satisfied and install nothing.

```bash
pip install --upgrade "memq-dqc[mcp]"
```

Clients launch the server without activating your environment, so register
it by absolute path (find it with `which memq-dqc-mcp`):

=== "Claude Code"

    ```bash
    claude mcp add --scope user memq-dqc -- /path/to/.venv/bin/memq-dqc-mcp
    ```

=== "Claude Desktop"

    Add this to `claude_desktop_config.json`, then restart the app:

    ```json
    {
      "mcpServers": {
        "memq-dqc": {
          "command": "/path/to/.venv/bin/memq-dqc-mcp"
        }
      }
    }
    ```

The server then uses your existing install, including any local changes.

### If memq-dqc is not installed

With [uv](https://docs.astral.sh/uv/), `uvx` fetches memq-dqc and its
dependencies into a cached environment, with nothing installed into your
Python. Run it once first so the client does not time out while the first
download completes:

```bash
uvx --from "memq-dqc[mcp]" memq-dqc-mcp --help
```

=== "Claude Code"

    ```bash
    claude mcp add --scope user memq-dqc -- uvx --from "memq-dqc[mcp]" memq-dqc-mcp
    ```

=== "Claude Desktop"

    Add this to `claude_desktop_config.json`, then restart the app:

    ```json
    {
      "mcpServers": {
        "memq-dqc": {
          "command": "uvx",
          "args": ["--from", "memq-dqc[mcp]", "memq-dqc-mcp"]
        }
      }
    }
    ```

To pick up a new release later, run the `--help` command again with
`--refresh` added after `uvx`.

### From a clone

`uv sync` already installs the extra. Register
`uv --directory /path/to/dqc run memq-dqc-mcp` as the command.

## Tools

| Tool | What it does |
|---|---|
| `list_algorithms` | Lists partitioner, scheduler, modality, and entanglement-profile names. |
| `list_bundled_assets` | Lists the [bundled circuits and networks](bundled-assets.md). |
| `describe_network` | Validates a network and summarizes it: QPU ids and per-QPU qubit counts. |
| `build_network` | Generates a network from a QPU count, qubits per QPU, and an arrangement. |
| `compile_circuit` | Partitions a circuit and returns its e-bit cost and distributed OpenQASM. |
| `verify_compilation` | Compiles, then checks the distributed circuit against the original. |
| `schedule_circuit` | Compiles, schedules, and returns the makespan and operation counts. |
| `compare_partitioners` | Compiles one circuit with several partitioners and ranks them. |

Circuit and network arguments are strings, and each accepts any of:

- a bundled asset name, such as `qft_n10` or `10_qubits/n2_pair_nn`;
- inline source: OpenQASM 3 text for a circuit, or network JSON text;
- a path to a `.qasm` or `.json` file.

Large outputs can go to disk instead of the conversation: `compile_circuit`
and `schedule_circuit` take an optional `output_path`, and
`compile_circuit(include_qasm=False)` omits the OpenQASM from the response.

`verify_compilation` defaults to the exact `statevector` method, capped at
20 qubits. Pass `method="sampling"` for wider circuits.

## Designing a network

To compile on a topology that isn't bundled, ask for one directly, such as
"build a 4-QPU ring with 5 qubits per QPU": the model calls `build_network`,
which wraps [`generate_network`](networks.md#generating-networks). For a
guided version, use the `design_network` prompt. In Claude Code it appears as a slash command
(`/mcp__memq-dqc__design_network`); in Claude Desktop, under the **+** menu.
The model then:

1. suggests a bundled network if one already fits;
2. asks only for what you haven't said: QPU count, qubits per QPU, how the
   QPUs are linked, connectivity inside each QPU, and links per QPU pair,
   each with a default you can accept;
3. confirms the design and builds it with `build_network`, writing the JSON
   by hand only for designs that tool can't express, such as QPUs of
   different sizes;
4. saves it and offers to compile a circuit on it.

Both arguments are optional. `requirements` passes along anything you have
already decided, such as "4 QPUs in a ring, 5 qubits each". `output_path`
sets where the file is saved; without it, the model asks.

The prompt includes the JSON format reference, which is also available on
its own as the `memq://network-format` resource. Clients that don't support
prompts can still read that resource, since the server's instructions
point the model to it.

`describe_network` runs [`validate_network`](networks.md#validating-a-network)
on whatever it is given, so a hand-written network with a broken link is
rejected with a list of every problem.

## Resources

| URI | Contents |
|---|---|
| `memq://network-format` | The network JSON format reference, written for a model. |
| `memq://circuits/{name}` | OpenQASM source of a bundled circuit. |
| `memq://networks/{size}/{name}` | JSON of a bundled network. |
| `memq://networks/{size}/{name}/doc` | Description of a bundled network. |

## Running over HTTP

The same server can be served over HTTP, for clients that connect to a URL
rather than launching a subprocess:

```bash
uv run memq-dqc-mcp --transport http --port 8020
```

It then listens at `http://127.0.0.1:8020/mcp`. The HTTP transport has no
authentication, and its tools read and write paths on the serving machine,
so keep it bound to localhost. Hosting it for other users would need
authentication and restrictions on file paths first.

## Using the tools from Python

The tool logic lives in `memq_dqc.mcp_server.tools` as plain functions that
return dictionaries, so they work without an MCP client:

```python
from memq_dqc.mcp_server import tools

tools.compare_partitioners("qft_n10", "10_qubits/n3_ring_nn", scheduler="fifo")
```
