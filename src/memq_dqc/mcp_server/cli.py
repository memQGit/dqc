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

"""Console entry point that runs the memq_dqc MCP server."""

import argparse
import importlib.util
import sys

DEFAULT_HOST = "127.0.0.1"
#: Clear of ``mkdocs serve`` (8000) and the network builder (8010).
DEFAULT_PORT = 8020

_MISSING_FASTMCP = (
    "The MCP server needs FastMCP, which is an optional dependency.\n"
    'Install it with:  pip install "memq-dqc[mcp]"'
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Argument list, or None to read from ``sys.argv``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="memq-dqc-mcp",
        description=(
            "Run the memq_dqc MCP server, which exposes the distributed "
            "compiler as tools for MCP clients such as Claude."
        ),
        epilog=(
            "stdio is for local clients that launch the server themselves. "
            "http serves at http://HOST:PORT/mcp and has no authentication, "
            "so keep it on localhost."
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--transport",
        choices=("stdio", "http"),
        default="stdio",
        help="How clients connect to the server.",
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help="Interface to bind for the http transport.",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port to serve on for the http transport.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    """Start the MCP server on the requested transport.

    Args:
        argv: Argument list, or None to read from ``sys.argv``.

    Returns:
        A process exit status.
    """
    args = _parse_args(argv)

    # Probe FastMCP itself rather than wrapping the server import, so a real
    # ImportError inside server.py is not misreported as a missing extra.
    if importlib.util.find_spec("fastmcp") is None:
        print(_MISSING_FASTMCP, file=sys.stderr)
        return 1

    from .server import create_server

    server = create_server()
    if args.transport == "stdio":
        # stdout carries the protocol, so the startup banner must stay off it.
        server.run(transport="stdio", show_banner=False)
    else:
        server.run(transport="http", host=args.host, port=args.port)
    return 0
