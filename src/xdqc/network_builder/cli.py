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

"""Console entry point that launches the network builder in a browser."""

import argparse
import importlib.util
import socket
import sys
import threading
import webbrowser

DEFAULT_HOST = "127.0.0.1"
#: Deliberately not 8000, which is where ``mkdocs serve`` lives, so the
#: docs preview and the builder can run side by side.
DEFAULT_PORT = 8010

_MISSING_FLASK = (
    "The network builder needs Flask, which is an optional dependency.\n"
    'Install it with:  pip install "xdqc[builder]"'
)


def _parse_args(argv: list[str] | None) -> argparse.Namespace:
    """Parse command line arguments.

    Args:
        argv: Argument list, or None to read from ``sys.argv``.

    Returns:
        The parsed arguments.
    """
    parser = argparse.ArgumentParser(
        prog="network-builder",
        description=(
            "Launch the xdqc network builder, a local browser tool for "
            "designing quantum networks and exporting them as JSON."
        ),
        epilog=(
            f"By default the builder serves on http://{DEFAULT_HOST}:"
            f"{DEFAULT_PORT}. Port {DEFAULT_PORT} avoids colliding with "
            "`mkdocs serve` on 8000; pass --port to serve elsewhere, for "
            "example: network-builder --port 8020"
        ),
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "--host",
        default=DEFAULT_HOST,
        help=(
            "Interface to bind. Defaults to localhost; binding to a "
            "public interface exposes the builder to your network."
        ),
    )
    parser.add_argument(
        "--port",
        type=int,
        default=DEFAULT_PORT,
        help="Port to serve on.",
    )
    parser.add_argument(
        "--no-browser",
        action="store_true",
        help="Do not open a browser window on startup.",
    )
    return parser.parse_args(argv)


def _port_is_free(host: str, port: int) -> bool:
    """Check whether the server would be able to bind a port.

    Werkzeug's own in-use message does not mention this command's
    ``--port`` flag, so the check runs up front to give a fix the caller
    can copy.

    Args:
        host: Interface the server would bind.
        port: Port the server would bind.

    Returns:
        True if the port is currently bindable.
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
        except OSError:
            return False
    return True


def main(argv: list[str] | None = None) -> int:
    """Start the network builder and open it in the default browser.

    Args:
        argv: Argument list, or None to read from ``sys.argv``.

    Returns:
        A process exit status.
    """
    args = _parse_args(argv)

    # Probe Flask itself rather than wrapping the server import, so a real
    # ImportError inside server.py is not misreported as a missing extra.
    if importlib.util.find_spec("flask") is None:
        print(_MISSING_FLASK, file=sys.stderr)
        return 1

    from .server import create_app

    if not _port_is_free(args.host, args.port):
        print(
            f"Port {args.port} on {args.host} is already in use.\n"
            "Serve on a different port with --port, for example:\n"
            f"    network-builder --port {args.port + 10}",
            file=sys.stderr,
        )
        return 1

    url = f"http://{args.host}:{args.port}"
    print(f"xdqc network builder running at {url}")
    print("Press Ctrl+C to stop.")

    if not args.no_browser:
        threading.Timer(1.0, webbrowser.open, args=(url,)).start()

    app = create_app()
    app.run(host=args.host, port=args.port, debug=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
