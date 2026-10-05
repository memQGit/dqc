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

import asyncio

import pytest

pytest.importorskip("fastmcp")

from fastmcp import Client  # noqa: E402
from fastmcp.exceptions import ToolError  # noqa: E402

from memq_dqc.assets import circuit_path  # noqa: E402
from memq_dqc.mcp_server import prompts  # noqa: E402
from memq_dqc.mcp_server.server import create_server  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


async def _list_tools():
    async with Client(create_server()) as client:
        return await client.list_tools()


async def _call(name, arguments):
    async with Client(create_server()) as client:
        return await client.call_tool(name, arguments)


async def _list_prompts():
    async with Client(create_server()) as client:
        return await client.list_prompts()


async def _get_prompt(name, arguments):
    async with Client(create_server()) as client:
        return await client.get_prompt(name, arguments)


async def _read(uri):
    async with Client(create_server()) as client:
        return await client.read_resource(uri)


def test_server_registers_every_tool():
    names = {tool.name for tool in _run(_list_tools())}

    assert names == {
        "list_algorithms",
        "list_bundled_assets",
        "describe_network",
        "build_network",
        "compile_circuit",
        "verify_compilation",
        "schedule_circuit",
        "compare_partitioners",
    }


def test_option_arguments_are_published_as_enums():
    tools = {tool.name: tool for tool in _run(_list_tools())}

    properties = tools["schedule_circuit"].input_schema["properties"]

    assert "interaction" in properties["partitioner"]["enum"]
    assert "fifo" in properties["scheduler"]["enum"]
    assert "trapped_ion.ba" in properties["modality"]["enum"]


def test_compile_tool_round_trips_over_mcp():
    result = _run(
        _call(
            "compile_circuit",
            {"circuit": "qft_n4", "network": "10_qubits/n2_pair_nn"},
        )
    )

    assert result.data["num_qpus"] == 2
    assert result.data["distributed_qasm"].startswith("OPENQASM 3")


def test_invalid_option_is_rejected_before_compiling():
    with pytest.raises(ToolError, match="partitioner"):
        _run(
            _call(
                "compile_circuit",
                {
                    "circuit": "qft_n4",
                    "network": "10_qubits/n2_pair_nn",
                    "partitioner": "not-a-partitioner",
                },
            )
        )


def test_bundled_circuit_resource_returns_source():
    contents = _run(_read("memq://circuits/qft_n4"))

    assert contents[0].text == circuit_path("qft_n4").read_text()


def test_bundled_network_resources_return_json_and_doc():
    network = _run(_read("memq://networks/10_qubits/n2_pair_nn"))
    doc = _run(_read("memq://networks/10_qubits/n2_pair_nn/doc"))

    assert network[0].text.lstrip().startswith("{")
    assert doc[0].text.startswith("# n2_pair_nn")


def test_network_format_resource_returns_reference():
    contents = _run(_read("memq://network-format"))

    assert contents[0].text == prompts.network_format()


def test_design_network_prompt_is_registered_with_optional_arguments():
    (prompt,) = _run(_list_prompts())

    assert prompt.name == "design_network"
    assert {arg.name: arg.required for arg in prompt.arguments} == {
        "requirements": False,
        "output_path": False,
    }


def test_design_network_prompt_renders_over_mcp():
    result = _run(
        _get_prompt("design_network", {"requirements": "3 QPUs in a chain"})
    )

    text = result.messages[0].content.text
    assert text == prompts.design_network(requirements="3 QPUs in a chain")
