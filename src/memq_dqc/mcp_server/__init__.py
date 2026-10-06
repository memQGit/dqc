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

"""Model Context Protocol (MCP) server for the distributed compiler.

This subpackage exposes the compile -> verify -> schedule workflow as MCP
tools, so an MCP client (Claude Desktop, Claude Code, Cursor, ...) can drive
the compiler from natural language. It is a convenience layer over the
public API, not part of the compiler: nothing here is imported by the
compilation pipeline.

The tool logic lives in ``memq_dqc.mcp_server.tools`` as plain functions
that return JSON-serializable dictionaries, so it can be tested and reused
without an MCP runtime. ``memq_dqc.mcp_server.server`` registers those
functions with FastMCP.

Launch it with the ``memq-dqc-mcp`` console script:

```bash
uv run memq-dqc-mcp  # stdio, for local MCP clients
uv run memq-dqc-mcp --transport http --port 8020
```

The module deliberately exports nothing at import time so that
``import memq_dqc`` never requires the optional FastMCP dependency.
"""
