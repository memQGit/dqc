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

"""Transport-agnostic text for the MCP prompts and reference resources.

Like ``memq_dqc.mcp_server.tools``, nothing here imports FastMCP: these
functions only build strings, which the server registers as MCP prompts and
resources.
"""

from pathlib import Path

_NETWORK_FORMAT_PATH = Path(__file__).resolve().parent / "network_format.md"

_DESIGN_NETWORK_STEPS = """\
Work through these steps:

1. Call `list_bundled_assets`. If a bundled network already matches what I
   need, suggest it and ask whether to use it instead of building a new one.
2. Ask me for anything below that I have not already given you, in a single
   short message. Show the default in brackets so I can just accept it:
   - Number of QPUs.
   - Computation qubits per QPU, or the number of qubits in the circuits
     the network must run [that number divided across the QPUs, rounded up].
   - How the QPUs are linked: pair, chain, ring, hub, all-to-all, or a
     custom list of links [pair for 2 QPUs, chain otherwise].
   - Connectivity inside each QPU: nearest neighbour, all-to-all, or line
     [nearest neighbour].
   - Remote links per linked QPU pair [2]. Explain that with 1, QPUs that
     are not directly linked cannot interact.
3. Restate the design in a sentence or two, including the total
   computation and communication qubit counts, and wait for me to confirm.
4. Build the network JSON, following the format reference below exactly.
   If you can run code, generate it with a short script instead of writing
   it by hand: hand-written JSON gets error-prone past a few dozen qubits.
5. Validate it with `describe_network`. That tool rejects some mistakes,
   such as unknown qubit IDs or invalid qubit types, but not all of them,
   so also check that its QPU count and per-QPU qubit counts match the
   design, and recheck every rule in the reference. Fix and repeat until
   it is correct.
6. {save_step}
7. Report the `describe_network` summary, then offer to compile a circuit
   on the new network with `compile_circuit` or `compare_partitioners`.
"""


def network_format() -> str:
    """Return the network topology format reference.

    Returns:
        A Markdown reference to the network JSON format, written for a
        model that has to produce valid networks.
    """
    return _NETWORK_FORMAT_PATH.read_text(encoding="utf-8")


def design_network(
    requirements: str | None = None,
    output_path: str | None = None,
) -> str:
    """Return a prompt that walks the model through designing a network.

    The prompt has the model gather the topology requirements from the user,
    build the network JSON, validate it, and save it.

    Args:
        requirements: Anything the user has already said about the network,
            such as "4 QPUs in a ring, 5 qubits each". The model only asks
            for what is missing.
        output_path: Where to save the network JSON. When omitted, the model
            asks the user.

    Returns:
        The prompt text, including the full format reference.
    """
    if output_path:
        save_step = f"Save the network JSON to `{output_path}`."
    else:
        save_step = (
            "Ask me where to save the network JSON, suggesting "
            "`./network.json`. If you cannot write files, give me the JSON "
            "instead; every memq-dqc tool also accepts it inline."
        )

    parts = [
        "Help me design a quantum network topology for memq-dqc and save "
        "it as a network JSON file."
    ]
    if requirements:
        parts.append(f"What I have told you so far: {requirements}")
    parts.append(_DESIGN_NETWORK_STEPS.format(save_step=save_step))
    parts.append(f"Format reference:\n\n{network_format()}")
    return "\n\n".join(parts)
