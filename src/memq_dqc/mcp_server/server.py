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

"""FastMCP server exposing the distributed-compiler tools.

``create_server`` registers every
function in ``memq_dqc.mcp_server.tools`` as an MCP tool, and the bundled
circuits and networks as MCP resources. The returned server is
transport-agnostic: the console script runs it over stdio or HTTP.
"""

from __future__ import annotations

from fastmcp import FastMCP

from memq_dqc.assets import circuit_path, network_doc_path, network_path

from . import tools

_INSTRUCTIONS = """\
Tools for memq_dqc, a distributed quantum compiler. The workflow is: take a
circuit and a network of QPUs, partition the circuit across the QPUs, build
the distributed circuit (OpenQASM 3), optionally verify it, and build a
time-execution schedule.

Circuits and networks are strings: a bundled asset name (call
list_bundled_assets), inline OpenQASM 3 / network JSON, or a file path.
A network under "N_qubits/" fits circuits of at most N qubits. Lower
ebit_cost means fewer remote entangled pairs; lower makespan means faster
execution. Call list_algorithms for valid partitioner and scheduler names.
"""


def create_server() -> FastMCP:
    """Build the memq_dqc MCP server.

    Returns:
        A FastMCP server with the compiler tools and bundled-asset resources
        registered, ready to run on any transport.
    """
    server = FastMCP("memq-dqc", instructions=_INSTRUCTIONS)

    read_only = {"readOnlyHint": True, "openWorldHint": False}
    for fn in (tools.list_algorithms, tools.list_bundled_assets):
        server.tool(fn, annotations=read_only)
    for fn in (
        tools.describe_network,
        tools.compile_circuit,
        tools.verify_compilation,
        tools.schedule_circuit,
        tools.compare_partitioners,
    ):
        # Compiling tools only write files when given an ``output_path``.
        server.tool(fn, annotations={"openWorldHint": False})

    @server.resource(
        "memq://circuits/{name}",
        mime_type="text/plain",
        description="OpenQASM 3 source of a bundled circuit.",
    )
    def bundled_circuit(name: str) -> str:
        """Return the OpenQASM source of a bundled circuit.

        Args:
            name: Bundled circuit name, such as ``qft_n10``.

        Returns:
            The OpenQASM 3 source text.
        """
        return circuit_path(name).read_text()

    @server.resource(
        "memq://networks/{size}/{name}",
        mime_type="application/json",
        description="JSON description of a bundled network topology.",
    )
    def bundled_network(size: str, name: str) -> str:
        """Return the JSON description of a bundled network.

        Args:
            size: Capacity directory, such as ``10_qubits``.
            name: Network name within that directory, such as ``n2_pair_nn``.

        Returns:
            The network JSON text.
        """
        return network_path(f"{size}/{name}").read_text()

    @server.resource(
        "memq://networks/{size}/{name}/doc",
        mime_type="text/markdown",
        description="Human-readable description of a bundled network.",
    )
    def bundled_network_doc(size: str, name: str) -> str:
        """Return the Markdown description of a bundled network.

        Args:
            size: Capacity directory, such as ``10_qubits``.
            name: Network name within that directory, such as ``n2_pair_nn``.

        Returns:
            The network's Markdown description.
        """
        return network_doc_path(f"{size}/{name}").read_text()

    return server
