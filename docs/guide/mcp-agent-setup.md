# MCP Setup via an AI Agent

Copy everything below the line into an AI agent that can run shell commands
on your machine (Claude Code, Cursor, Codex, and similar). The agent checks
what you already have, installs what is missing, and connects the memq-dqc
MCP server to your MCP client. It asks before doing anything you might not
want.

---

## Task: install and connect the memq-dqc MCP server

You are setting up the memq-dqc MCP server for the user. memq-dqc is a
Python library for distributed quantum compilation (PyPI package
`memq-dqc`). Its MCP server ships as the optional `mcp` extra and runs
locally over stdio via the `memq-dqc-mcp` command.

Work through the steps in order. Run the commands yourself; do not ask the
user to run them.

### Rules

- Never use `sudo`, and never install into the system Python.
- Ask the user before installing `uv` or any other tool.
- When editing a client config file, back it up first and merge the new
  entry into it. Never remove or overwrite other entries.
- If a step fails in a way this file does not cover, stop and tell the user
  what failed, including the command and its output.
- Use the paths and shell for the user's OS. On Windows, executables live in
  `Scripts\` with an `.exe` suffix rather than in `bin/`.

### Step 1: Choose the MCP client

Find out which MCP client the user wants the server in: Claude Code, Claude
Desktop, Cursor, or another. If you are running inside one of them and the
user has not said otherwise, use that one. If it is unclear, ask.

### Step 2: Check for an existing memq-dqc install

Ask the user whether they already use memq-dqc in a particular Python
environment (a virtualenv, a conda env, or a uv project). If they do,
locate that environment's Python interpreter and confirm the package is in
it:

```bash
<python> -c "import importlib.metadata as m; print(m.version('memq-dqc'))"
```

- If it prints a version, follow **Path A**.
- If the user has no install, or the package is not found, follow
  **Path B**.

memq-dqc needs Python 3.11 or newer. Check with `<python> --version` before
installing into an environment.

### Path A: memq-dqc is already installed

Install the extra into that same environment. `--upgrade` matters: older
releases do not have the `mcp` extra, and without it pip reports the
requirement as already satisfied and installs nothing.

```bash
<python> -m pip install --upgrade "memq-dqc[mcp]"
```

For a uv-managed project, run `uv add "memq-dqc[mcp]"` in the project
directory instead.

Find the absolute path of the server executable. Clients launch it without
activating the environment, so the bare command name is not enough:

```bash
<python> -c "import sysconfig; print(sysconfig.get_path('scripts'))"
```

The server is `<that directory>/memq-dqc-mcp`. Confirm it starts:

```bash
<absolute path>/memq-dqc-mcp --help
```

The client command is that absolute path, with no arguments. Go to Step 3.

### Path B: memq-dqc is not installed

Check for uv with `uv --version`.

**If uv is available**, use `uvx`, which needs no install into the user's
Python. Run this once to download and cache everything; it can take a
minute or two, and doing it now keeps the client from timing out on first
launch:

```bash
uvx --from "memq-dqc[mcp]" memq-dqc-mcp --help
```

The client command is `uvx` with the arguments
`--from memq-dqc[mcp] memq-dqc-mcp`. Go to Step 3.

**If uv is not available**, ask the user which they prefer:

1. Install uv (see https://docs.astral.sh/uv/getting-started/installation/),
   then follow the uv instructions above.
2. Use a dedicated virtualenv instead. With a Python 3.11+ interpreter:

    ```bash
    python3 -m venv ~/.memq-dqc
    ~/.memq-dqc/bin/python -m pip install "memq-dqc[mcp]"
    ~/.memq-dqc/bin/memq-dqc-mcp --help
    ```

    The client command is the absolute path of
    `~/.memq-dqc/bin/memq-dqc-mcp` with `~` expanded, and no arguments.

### Step 3: Register the server with the client

Use the server name `memq-dqc` and the command and arguments from Path A or
Path B.

**Claude Code.** Register it at user scope so it works in every project:

```bash
claude mcp add --scope user memq-dqc -- <command> <args...>
```

**Claude Desktop.** Edit the config file, creating it if it does not exist:

- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

**Cursor.** Edit `~/.cursor/mcp.json`, creating it if it does not exist.

For Claude Desktop and Cursor, add this entry under the top-level
`mcpServers` object. Omit `args` when there are none:

```json
{
  "mcpServers": {
    "memq-dqc": {
      "command": "<command>",
      "args": ["<arg>", "..."]
    }
  }
}
```

`command` should be an absolute path unless it is `uvx`. If the client
reports that it cannot find `uvx`, replace it with the output of
`which uvx` (`where uvx` on Windows).

**Other clients.** Register a stdio server with the same command and
arguments, following that client's documentation.

### Step 4: Verify

- **Claude Code:** run `claude mcp list` and confirm `memq-dqc` is
  connected.
- **Claude Desktop or Cursor:** tell the user to fully quit and reopen the
  app, then check that the memq-dqc tools appear.

Then tell the user what you did:

- whether memq-dqc was already installed, and which environment the server
  uses;
- the exact command registered, and which config file you changed;
- a prompt to try, such as *"Use memq-dqc to compile qft_n10 on the network
  10_qubits/n2_pair_nn and report the e-bit cost."*

### Troubleshooting

| Symptom | Fix |
|---|---|
| `memq-dqc ... does not provide the extra 'mcp'` | The installed release predates the MCP server. Re-run the install with `--upgrade`. |
| `Requires-Python >=3.11` or a resolver error naming Python | The environment's Python is too old. Use a 3.11+ interpreter. |
| The client times out the first time it starts the server | Run the `--help` command from Path A or B once, then restart the client. |
| The `hypergraph` partitioner fails on Windows | Expected. KaHyPar has no Windows build; every other partitioner works. |
