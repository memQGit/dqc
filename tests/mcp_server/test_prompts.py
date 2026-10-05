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

import json
import re

from memq_dqc.mcp_server import prompts, tools

FOUR_QUBIT_CIRCUIT = """OPENQASM 3.0;
include "stdgates.inc";
qubit[4] q;
bit[4] c;
h q[0];
cx q[0], q[3];
cx q[1], q[2];
cx q[0], q[1];
c[0] = measure q[0];
c[1] = measure q[1];
c[2] = measure q[2];
c[3] = measure q[3];
"""


def _example_network() -> str:
    match = re.search(r"```json\n(.*?)```", prompts.network_format(), re.S)
    assert match is not None
    return match.group(1)


def test_format_reference_example_is_a_valid_network():
    example = _example_network()

    summary = tools.describe_network(example)

    assert json.loads(example)
    assert summary["num_qpus"] == 2
    assert summary["computation_qubits_per_qpu"] == [2, 2]
    assert summary["communication_qubits_per_qpu"] == [2, 2]


def test_format_reference_example_compiles_correctly():
    result = tools.verify_compilation(FOUR_QUBIT_CIRCUIT, _example_network())

    assert result["equivalent"] is True


def test_design_network_embeds_format_reference():
    text = prompts.design_network()

    assert prompts.network_format() in text
    assert "describe_network" in text


def test_design_network_includes_given_requirements():
    text = prompts.design_network(requirements="4 QPUs in a ring")

    assert "What I have told you so far: 4 QPUs in a ring" in text


def test_design_network_without_requirements_omits_them():
    text = prompts.design_network()

    assert "What I have told you so far" not in text


def test_design_network_uses_output_path_when_given():
    with_path = prompts.design_network(output_path="nets/ring.json")
    without_path = prompts.design_network()

    assert "Save the network JSON to `nets/ring.json`." in with_path
    assert "Ask me where to save" in without_path
