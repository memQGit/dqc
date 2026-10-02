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

import importlib.util

import pytest

from memq_dqc.mcp_server import cli


def test_missing_fastmcp_prints_install_hint(monkeypatch, capsys):
    real_find_spec = importlib.util.find_spec
    monkeypatch.setattr(
        importlib.util,
        "find_spec",
        lambda name: None if name == "fastmcp" else real_find_spec(name),
    )

    assert cli.main([]) == 1
    assert "memq-dqc[mcp]" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        ([], {"transport": "stdio", "show_banner": False}),
        (
            ["--transport", "http", "--port", "9999"],
            {"transport": "http", "host": cli.DEFAULT_HOST, "port": 9999},
        ),
    ],
)
def test_main_runs_server_on_requested_transport(monkeypatch, argv, expected):
    pytest.importorskip("fastmcp")
    from memq_dqc.mcp_server import server

    calls = []

    class FakeServer:
        def run(self, **kwargs):
            calls.append(kwargs)

    monkeypatch.setattr(server, "create_server", FakeServer)

    assert cli.main(argv) == 0
    assert calls == [expected]
