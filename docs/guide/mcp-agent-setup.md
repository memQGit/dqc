# MCP Setup via an AI Agent

Connect DQC to Codex, Claude Code, Cursor, or another MCP client by pasting
one prompt into your agent.

<div class="mcp-setup-card">
  <span class="mcp-setup-card__eyebrow">LOCAL MCP SERVER</span>
  <h2>Let your agent handle setup</h2>
  <p>It checks your Python environment, installs missing dependencies,
  connects DQC, and verifies the tools are ready.</p>
  <label class="mcp-setup-agent-label" for="mcp-setup-agent">Your agent</label>
  <select id="mcp-setup-agent" class="mcp-setup-agent">
    <option value="codex">Codex</option>
    <option value="claude-code">Claude Code</option>
    <option value="cursor">Cursor</option>
    <option value="other">Other</option>
  </select>
  <button type="button" class="md-button md-button--primary mcp-setup-copy"
    data-copy-target="mcp-setup-prompt" aria-label="Copy Codex prompt">
    <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true">
      <path fill="currentColor" d="M16 1H4a2 2 0 0 0-2 2v14h2V3h12V1zm3 4H8a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h11a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2zm0 16H8V7h11v14z"/>
    </svg>
    <span class="mcp-setup-copy__label">Copy Codex prompt</span>
  </button>
  <p class="mcp-setup-status" role="status" aria-live="polite">Copy, paste into your agent, and send.</p>
</div>

Your agent checks for an existing DQC installation automatically.

<details class="mcp-setup-preview">
  <summary>View the full setup prompt</summary>
  <pre><code id="mcp-setup-prompt">## Task: install and connect the memq-dqc MCP server

You are setting up the memq-dqc MCP server for the user. memq-dqc is a
Python library for distributed quantum compilation (PyPI package
&#96;memq-dqc&#96;). Its MCP server ships as the optional &#96;mcp&#96; extra and runs
locally over stdio via the &#96;memq-dqc-mcp&#96; command.

Work through the steps in order. Run the commands yourself; do not ask the
user to run them. Keep narration brief: one short progress sentence, then a
short final summary of the environment, server command, and verification.
Do not print full config files, dependency logs, or documentation. Show the
relevant command and error if something fails. Tool output may still be
visible in the client&#x27;s interface; do not repeat it in your prose.

### Rules

- Web browsing is not required. For Codex, Claude Code, and Cursor, use the
  client-specific instructions below and local CLI &#96;--help&#96; if needed.
  Do not browse the web or fetch external documentation for this setup.
  Package managers may download the required packages and dependencies.
- Never use &#96;sudo&#96;, and never install into the system Python.
- Ask the user before installing &#96;uv&#96; or any other tool.
- When editing a client config file, back it up first and merge the new
  entry into it. Never remove or overwrite other entries.
- If a step fails in a way this file does not cover, stop and tell the user
  what failed, including the command and its output.
- Use the paths and shell for the user&#x27;s OS. On Windows, executables live in
  &#96;Scripts\&#96; with an &#96;.exe&#96; suffix rather than in &#96;bin/&#96;.

### Step 1: MCP client

The user selected Codex. Set up this client only.

### Step 2: Detect an existing installation

Check for an existing installation yourself; do not first ask the user
whether memq-dqc is installed.

1. If memq-dqc tools are already available, call &#96;list_algorithms&#96;. If it
   succeeds, report that DQC is connected and stop without changing config.
2. Inspect only the selected client&#x27;s memq-dqc configuration entry. If
   present, test its configured command and arguments with &#96;--help&#96;. Reuse
   a working server, including a development installation or uvx command.
3. If the user supplied an environment or executable path, check that first.
   Otherwise check the current project&#x27;s &#96;.venv&#96;, the active Python
   environment, &#96;python&#96;/&#96;python3&#96; on PATH, and an existing &#96;~/.memq-dqc&#96;
   virtualenv. Do not scan unrelated directories or print environment
   variables or credentials. For each available interpreter, run:

&#96;&#96;&#96;bash
&lt;python&gt; -c &quot;import sys, importlib.metadata as m; print(sys.executable); print(m.version(&#x27;memq-dqc&#x27;))&quot;
&#96;&#96;&#96;

If a single suitable installation is found, follow Path A. Prefer the
configured server or user-specified environment over other candidates.
Ask which environment to use only if multiple candidates remain ambiguous.
If none is found, follow Path B.

memq-dqc needs Python 3.11 or newer. Check &#96;&lt;python&gt; --version&#96; before
installing into an environment.

### Path A: memq-dqc is already installed

Find the absolute path of the server executable:

&#96;&#96;&#96;bash
&lt;python&gt; -c &quot;import sysconfig; print(sysconfig.get_path(&#x27;scripts&#x27;))&quot;
&#96;&#96;&#96;

The server is &#96;&lt;that directory&gt;/memq-dqc-mcp&#96;. Test it:

&#96;&#96;&#96;bash
&lt;absolute path&gt;/memq-dqc-mcp --help
&#96;&#96;&#96;

If this works, reuse it without installing or upgrading anything. Clients
launch the absolute command without activating the environment.

If the server or MCP dependency is missing, add the extra to that same
virtualenv. For a PyPI installation:

&#96;&#96;&#96;bash
&lt;python&gt; -m pip install --upgrade &quot;memq-dqc[mcp]&quot;
&#96;&#96;&#96;

For a uv-managed project, use &#96;uv add &quot;memq-dqc[mcp]&quot;&#96;. For an editable
local checkout, preserve the development installation and add the MCP
extra from that checkout rather than replacing it with a PyPI release.
Never install into system Python; use Path B&#x27;s isolated environment instead.
Re-test the server&#x27;s &#96;--help&#96; after any install.

The client command is the absolute server path, with no arguments.
Go to Step 3.

### Path B: memq-dqc is not installed

Check for uv with &#96;uv --version&#96;.

**If uv is available**, use &#96;uvx&#96;, which needs no install into the user&#x27;s
Python. Run this once to download and cache everything; it can take a
minute or two, and doing it now keeps the client from timing out on first
launch:

&#96;&#96;&#96;bash
uvx --from &quot;memq-dqc[mcp]&quot; memq-dqc-mcp --help
&#96;&#96;&#96;

The client command is &#96;uvx&#96; with the arguments
&#96;--from memq-dqc[mcp] memq-dqc-mcp&#96;. Go to Step 3.

**If uv is not available**, ask the user which they prefer:

1. Install uv (see https://docs.astral.sh/uv/getting-started/installation/),
   then follow the uv instructions above.
2. Use a dedicated virtualenv instead. With a Python 3.11+ interpreter:

    &#96;&#96;&#96;bash
    python3 -m venv ~/.memq-dqc
    ~/.memq-dqc/bin/python -m pip install &quot;memq-dqc[mcp]&quot;
    ~/.memq-dqc/bin/memq-dqc-mcp --help
    &#96;&#96;&#96;

    The client command is the absolute path of
    &#96;~/.memq-dqc/bin/memq-dqc-mcp&#96; with &#96;~&#96; expanded, and no arguments.

### Step 3: Register the server in Codex

Use the server name &#96;memq-dqc&#96; and the command and arguments from Path A or
Path B. Back up the existing Codex config (normally &#96;~/.codex/config.toml&#96;,
or &#96;config.toml&#96; in the configured CODEX_HOME directory) before registration.
Check &#96;codex mcp list&#96; first. If an entry named memq-dqc already exists,
inspect it and reuse it if correct; ask before replacing a different entry.
Preserve every other configured server.

&#96;&#96;&#96;bash
codex mcp add memq-dqc -- &lt;command&gt; &lt;args...&gt;
&#96;&#96;&#96;

### Step 4: Verify in Codex

Run &#96;codex mcp list&#96; and &#96;codex mcp get memq-dqc&#96; to confirm the registered
stdio command. Restart the Codex session to load the server, then check
&#96;/mcp&#96; and call the memq-dqc &#96;list_algorithms&#96; tool to verify it responds.
If a new session is required, explain that handoff rather than claiming
that the current session already has the tools.

### Present setup and results

Once installation and registration have succeeded, print this banner once
in the user-facing terminal. Color only the three small memQ lines purple
with ANSI &#96;\033[35m&#96;, then reset with &#96;\033[0m&#96; before DQC.
Use the already available Python interpreter to print it; do not install
figlet or another dependency. Keep ANSI codes out of MCP server stdout.
If terminal output is unavailable or does not support color, show the
plain banner once in your final response as a fenced text block instead.

&#96;&#96;&#96;text
        ▄ ▄ ▄  ▄▄▄  ▄ ▄ ▄  ▄▄▄
        █▀█▀█  █▄   █▀█▀█  █ █
        █ █ █  █▄▄  █ █ █  ▀▀█▄

██████╗    ██████╗   ██████╗
██╔══██╗  ██╔═══██╗ ██╔════╝
██║  ██║  ██║   ██║ ██║
██║  ██║  ██║▄▄ ██║ ██║
██████╔╝  ╚██████╔╝ ╚██████╗
╚═════╝    ╚══▀▀═╝   ╚═════╝
&#96;&#96;&#96;

Follow it with a compact Markdown table showing the Python environment,
server executable, and verified status. Distinguish &quot;Registered; restart
required&quot; from &quot;Connected; tool call verified&quot;. Do not claim connectivity
until an actual MCP tool call succeeds. If setup fails, show the error
instead of the success banner. End with the next step and one prompt:
&quot;Use memq-dqc to compile qft_n10 on 10_qubits/n2_pair_nn and report the
e-bit cost.&quot;

For subsequent DQC requests, keep results easy to scan:

- Use a short summary table for compilation, verification, and scheduling.
  Include only returned values: partitioner, e-bit cost, verification
  method/result, makespan with documented units, and saved files as relevant.
- Use one row per partitioner in comparisons, showing e-bit cost,
  makespan, and status. Retain failed rows with their error rather than
  inventing results. Note that randomized methods can vary.
- Save circuit and schedule outputs to files instead of dumping long QASM
  or JSON into the conversation, unless the user asks to see them.
- Keep explanations to one or two sentences. Describe statevector
  verification as an ideal measured-output distribution check and
  schedules as timing estimates.

### Troubleshooting

| Symptom | Fix |
|---|---|
| &#96;memq-dqc ... does not provide the extra &#x27;mcp&#x27;&#96; | The installed release predates the MCP server. Re-run the install with &#96;--upgrade&#96;. |
| &#96;Requires-Python &gt;=3.11&#96; or a resolver error naming Python | The environment&#x27;s Python is too old. Use a 3.11+ interpreter. |
| The client times out the first time it starts the server | Run the &#96;--help&#96; command from Path A or B once, then restart the client. |
| The &#96;hypergraph&#96; partitioner fails on Windows | Expected. KaHyPar has no Windows build; every other partitioner works. |</code></pre>
</details>

<div hidden>
<template id="mcp-setup-common">## Task: install and connect the memq-dqc MCP server

You are setting up the memq-dqc MCP server for the user. memq-dqc is a
Python library for distributed quantum compilation (PyPI package
&#96;memq-dqc&#96;). Its MCP server ships as the optional &#96;mcp&#96; extra and runs
locally over stdio via the &#96;memq-dqc-mcp&#96; command.

Work through the steps in order. Run the commands yourself; do not ask the
user to run them. Keep narration brief: one short progress sentence, then a
short final summary of the environment, server command, and verification.
Do not print full config files, dependency logs, or documentation. Show the
relevant command and error if something fails. Tool output may still be
visible in the client&#x27;s interface; do not repeat it in your prose.

### Rules

- Web browsing is not required. For Codex, Claude Code, and Cursor, use the
  client-specific instructions below and local CLI &#96;--help&#96; if needed.
  Do not browse the web or fetch external documentation for this setup.
  Package managers may download the required packages and dependencies.
- Never use &#96;sudo&#96;, and never install into the system Python.
- Ask the user before installing &#96;uv&#96; or any other tool.
- When editing a client config file, back it up first and merge the new
  entry into it. Never remove or overwrite other entries.
- If a step fails in a way this file does not cover, stop and tell the user
  what failed, including the command and its output.
- Use the paths and shell for the user&#x27;s OS. On Windows, executables live in
  &#96;Scripts\&#96; with an &#96;.exe&#96; suffix rather than in &#96;bin/&#96;.

### Step 1: MCP client

The user selected {{CLIENT}}. Set up this client only.

### Step 2: Detect an existing installation

Check for an existing installation yourself; do not first ask the user
whether memq-dqc is installed.

1. If memq-dqc tools are already available, call &#96;list_algorithms&#96;. If it
   succeeds, report that DQC is connected and stop without changing config.
2. Inspect only the selected client&#x27;s memq-dqc configuration entry. If
   present, test its configured command and arguments with &#96;--help&#96;. Reuse
   a working server, including a development installation or uvx command.
3. If the user supplied an environment or executable path, check that first.
   Otherwise check the current project&#x27;s &#96;.venv&#96;, the active Python
   environment, &#96;python&#96;/&#96;python3&#96; on PATH, and an existing &#96;~/.memq-dqc&#96;
   virtualenv. Do not scan unrelated directories or print environment
   variables or credentials. For each available interpreter, run:

&#96;&#96;&#96;bash
&lt;python&gt; -c &quot;import sys, importlib.metadata as m; print(sys.executable); print(m.version(&#x27;memq-dqc&#x27;))&quot;
&#96;&#96;&#96;

If a single suitable installation is found, follow Path A. Prefer the
configured server or user-specified environment over other candidates.
Ask which environment to use only if multiple candidates remain ambiguous.
If none is found, follow Path B.

memq-dqc needs Python 3.11 or newer. Check &#96;&lt;python&gt; --version&#96; before
installing into an environment.

### Path A: memq-dqc is already installed

Find the absolute path of the server executable:

&#96;&#96;&#96;bash
&lt;python&gt; -c &quot;import sysconfig; print(sysconfig.get_path(&#x27;scripts&#x27;))&quot;
&#96;&#96;&#96;

The server is &#96;&lt;that directory&gt;/memq-dqc-mcp&#96;. Test it:

&#96;&#96;&#96;bash
&lt;absolute path&gt;/memq-dqc-mcp --help
&#96;&#96;&#96;

If this works, reuse it without installing or upgrading anything. Clients
launch the absolute command without activating the environment.

If the server or MCP dependency is missing, add the extra to that same
virtualenv. For a PyPI installation:

&#96;&#96;&#96;bash
&lt;python&gt; -m pip install --upgrade &quot;memq-dqc[mcp]&quot;
&#96;&#96;&#96;

For a uv-managed project, use &#96;uv add &quot;memq-dqc[mcp]&quot;&#96;. For an editable
local checkout, preserve the development installation and add the MCP
extra from that checkout rather than replacing it with a PyPI release.
Never install into system Python; use Path B&#x27;s isolated environment instead.
Re-test the server&#x27;s &#96;--help&#96; after any install.

The client command is the absolute server path, with no arguments.
Go to Step 3.

### Path B: memq-dqc is not installed

Check for uv with &#96;uv --version&#96;.

**If uv is available**, use &#96;uvx&#96;, which needs no install into the user&#x27;s
Python. Run this once to download and cache everything; it can take a
minute or two, and doing it now keeps the client from timing out on first
launch:

&#96;&#96;&#96;bash
uvx --from &quot;memq-dqc[mcp]&quot; memq-dqc-mcp --help
&#96;&#96;&#96;

The client command is &#96;uvx&#96; with the arguments
&#96;--from memq-dqc[mcp] memq-dqc-mcp&#96;. Go to Step 3.

**If uv is not available**, ask the user which they prefer:

1. Install uv (see https://docs.astral.sh/uv/getting-started/installation/),
   then follow the uv instructions above.
2. Use a dedicated virtualenv instead. With a Python 3.11+ interpreter:

    &#96;&#96;&#96;bash
    python3 -m venv ~/.memq-dqc
    ~/.memq-dqc/bin/python -m pip install &quot;memq-dqc[mcp]&quot;
    ~/.memq-dqc/bin/memq-dqc-mcp --help
    &#96;&#96;&#96;

    The client command is the absolute path of
    &#96;~/.memq-dqc/bin/memq-dqc-mcp&#96; with &#96;~&#96; expanded, and no arguments.

{{CLIENT_STEPS}}

### Present setup and results

Once installation and registration have succeeded, print this banner once
in the user-facing terminal. Color only the three small memQ lines purple
with ANSI &#96;\033[35m&#96;, then reset with &#96;\033[0m&#96; before DQC.
Use the already available Python interpreter to print it; do not install
figlet or another dependency. Keep ANSI codes out of MCP server stdout.
If terminal output is unavailable or does not support color, show the
plain banner once in your final response as a fenced text block instead.

&#96;&#96;&#96;text
        ▄ ▄ ▄  ▄▄▄  ▄ ▄ ▄  ▄▄▄
        █▀█▀█  █▄   █▀█▀█  █ █
        █ █ █  █▄▄  █ █ █  ▀▀█▄

██████╗    ██████╗   ██████╗
██╔══██╗  ██╔═══██╗ ██╔════╝
██║  ██║  ██║   ██║ ██║
██║  ██║  ██║▄▄ ██║ ██║
██████╔╝  ╚██████╔╝ ╚██████╗
╚═════╝    ╚══▀▀═╝   ╚═════╝
&#96;&#96;&#96;

Follow it with a compact Markdown table showing the Python environment,
server executable, and verified status. Distinguish &quot;Registered; restart
required&quot; from &quot;Connected; tool call verified&quot;. Do not claim connectivity
until an actual MCP tool call succeeds. If setup fails, show the error
instead of the success banner. End with the next step and one prompt:
&quot;Use memq-dqc to compile qft_n10 on 10_qubits/n2_pair_nn and report the
e-bit cost.&quot;

For subsequent DQC requests, keep results easy to scan:

- Use a short summary table for compilation, verification, and scheduling.
  Include only returned values: partitioner, e-bit cost, verification
  method/result, makespan with documented units, and saved files as relevant.
- Use one row per partitioner in comparisons, showing e-bit cost,
  makespan, and status. Retain failed rows with their error rather than
  inventing results. Note that randomized methods can vary.
- Save circuit and schedule outputs to files instead of dumping long QASM
  or JSON into the conversation, unless the user asks to see them.
- Keep explanations to one or two sentences. Describe statevector
  verification as an ideal measured-output distribution check and
  schedules as timing estimates.

### Troubleshooting

| Symptom | Fix |
|---|---|
| &#96;memq-dqc ... does not provide the extra &#x27;mcp&#x27;&#96; | The installed release predates the MCP server. Re-run the install with &#96;--upgrade&#96;. |
| &#96;Requires-Python &gt;=3.11&#96; or a resolver error naming Python | The environment&#x27;s Python is too old. Use a 3.11+ interpreter. |
| The client times out the first time it starts the server | Run the &#96;--help&#96; command from Path A or B once, then restart the client. |
| The &#96;hypergraph&#96; partitioner fails on Windows | Expected. KaHyPar has no Windows build; every other partitioner works. |</template>
<template id="mcp-setup-codex">### Step 3: Register the server in Codex

Use the server name &#96;memq-dqc&#96; and the command and arguments from Path A or
Path B. Back up the existing Codex config (normally &#96;~/.codex/config.toml&#96;,
or &#96;config.toml&#96; in the configured CODEX_HOME directory) before registration.
Check &#96;codex mcp list&#96; first. If an entry named memq-dqc already exists,
inspect it and reuse it if correct; ask before replacing a different entry.
Preserve every other configured server.

&#96;&#96;&#96;bash
codex mcp add memq-dqc -- &lt;command&gt; &lt;args...&gt;
&#96;&#96;&#96;

### Step 4: Verify in Codex

Run &#96;codex mcp list&#96; and &#96;codex mcp get memq-dqc&#96; to confirm the registered
stdio command. Restart the Codex session to load the server, then check
&#96;/mcp&#96; and call the memq-dqc &#96;list_algorithms&#96; tool to verify it responds.
If a new session is required, explain that handoff rather than claiming
that the current session already has the tools.</template>
<template id="mcp-setup-claude-code">### Step 3: Register the server in Claude Code

Use the server name &#96;memq-dqc&#96; and the command and arguments from Path A or
Path B. Back up &#96;~/.claude.json&#96; (or &#96;.claude.json&#96; in the configured
CLAUDE_CONFIG_DIR directory) before registration. Check &#96;claude mcp list&#96;
first. Reuse an existing correct entry; ask before replacing a different
entry named memq-dqc. Preserve every other configured server.
Register at user scope so it works in every project:

&#96;&#96;&#96;bash
claude mcp add --scope user memq-dqc -- &lt;command&gt; &lt;args...&gt;
&#96;&#96;&#96;

### Step 4: Verify in Claude Code

Run &#96;claude mcp list&#96; and confirm memq-dqc is connected. If necessary,
restart the session and check &#96;/mcp&#96;. Call the memq-dqc &#96;list_algorithms&#96;
tool to verify it responds.</template>
<template id="mcp-setup-cursor">### Step 3: Register the server in Cursor

Use the server name &#96;memq-dqc&#96; and the command and arguments from Path A or
Path B. Back up &#96;~/.cursor/mcp.json&#96; if it exists, then merge this entry
under its top-level &#96;mcpServers&#96; object. Create the file if absent.
Reuse an existing correct entry; ask before replacing a different entry
named memq-dqc. Preserve every other configured server.
Omit &#96;args&#96; when there are none:

&#96;&#96;&#96;json
{
  &quot;mcpServers&quot;: {
    &quot;memq-dqc&quot;: {
      &quot;command&quot;: &quot;&lt;command&gt;&quot;,
      &quot;args&quot;: [&quot;&lt;arg&gt;&quot;, &quot;...&quot;]
    }
  }
}
&#96;&#96;&#96;

Use an absolute command path. If using uvx, resolve it with &#96;which uvx&#96;
(&#96;where uvx&#96; on Windows) so Cursor can find it without an activated shell.

### Step 4: Verify in Cursor

Check Cursor&#x27;s MCP settings to confirm memq-dqc is enabled and its tools
are available. Reload Cursor if necessary, then call the memq-dqc
&#96;list_algorithms&#96; tool in Agent mode to verify it responds.</template>
<template id="mcp-setup-other">### Step 3: Register the server in your MCP client

Ask which MCP client the user wants to configure. Use its local CLI help,
built-in setup instructions, or documentation supplied by the user.
If the registration method is still unknown, ask for those instructions;
do not require browsing or guess. Register a local stdio server named
memq-dqc with the command and arguments from Path A or Path B. Back up its config
before editing, preserve other entries, and reuse an existing correct
entry. Ask before replacing a different entry named memq-dqc.
Do not guess the config path or use another client&#x27;s config format.

### Step 4: Verify in your MCP client

Follow the client&#x27;s documented reload and connection checks. Confirm
memq-dqc&#x27;s tools appear and call &#96;list_algorithms&#96; to verify it responds.
Report any remaining connection problem without claiming success.</template>
</div>
