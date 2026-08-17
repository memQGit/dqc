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

"""Flask application backing the network builder.

The app serves the builder's static frontend and exposes a single endpoint,
``POST /generate_graph``, which validates a posted network through
:class:`xdqc.network.NetworkGraph` and returns a rendered preview image.
Parsing and validation are delegated entirely to ``NetworkGraph`` so the
builder cannot accept a network the library would reject.

Frontend and API are served from the same origin, so no CORS handling is
required.
"""

import base64
import json
import tempfile
from pathlib import Path
from typing import Any

from flask import Flask, Response, jsonify, request

from ..network import NetworkGraph, PhysicalQubit
from .render import render_png

STATIC_DIR = Path(__file__).parent / "static"


def _load_network(payload: dict[str, Any]) -> NetworkGraph:
    """Build a network graph from a posted network specification.

    ``NetworkGraph`` reads from a file, so the payload is staged in a
    temporary file rather than duplicating its parsing logic here.

    Args:
        payload: The network specification posted by the frontend.

    Returns:
        The parsed and validated network.
    """
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "network.json"
        path.write_text(json.dumps(payload))
        return NetworkGraph(str(path))


def _qubit_index(payload: dict[str, Any]) -> dict[str, PhysicalQubit]:
    """Map the payload's qubit IDs onto their graph nodes.

    Args:
        payload: The network specification posted by the frontend.

    Returns:
        A mapping from each raw qubit ID to its structured identifier.
    """
    index: dict[str, PhysicalQubit] = {}
    for raw_id, data in payload.get("qubits", {}).items():
        index[str(raw_id)] = PhysicalQubit(
            qpu_id=int(data["processorId"]),
            qubit_id=int(data["localIndex"]),
            qubit_type=data["type"],
        )
    return index


def _apply_link_fidelities(
    network: NetworkGraph, payload: dict[str, Any]
) -> None:
    """Copy remote-link fidelities from the payload onto the graph edges.

    ``NetworkGraph`` reads connectivity from each qubit's connection lists
    and ignores the payload's top-level ``connections`` array, so per-link
    fidelity has to be reattached here for the preview to display it.

    Fidelity is metadata only: no partitioning or scheduling algorithm in
    xdqc consumes it today. It is carried through for future
    fidelity-aware algorithms.

    Args:
        network: The parsed network whose edges should be annotated.
        payload: The network specification posted by the frontend.
    """
    index = _qubit_index(payload)
    graph = network.graph
    for connection in payload.get("connections", []):
        if connection.get("type") != "remote":
            continue
        source = index.get(str(connection.get("qubit1")))
        target = index.get(str(connection.get("qubit2")))
        if source is None or target is None:
            continue
        if graph.has_edge(source, target):
            graph.edges[source, target]["fidelity"] = float(
                connection.get("fidelity", 1.0)
            )


def create_app() -> Flask:
    """Build the network builder's Flask application.

    Returns:
        The configured application, serving the frontend at ``/``.
    """
    app = Flask(
        __name__,
        static_folder=str(STATIC_DIR),
        static_url_path="",
    )

    @app.get("/")
    def index() -> Response:
        """Serve the builder frontend."""
        return app.send_static_file("index.html")

    @app.post("/generate_graph")
    def generate_graph() -> tuple[Response, int]:
        """Render a posted network to a base64-encoded PNG preview."""
        payload = request.get_json(silent=True)
        if not isinstance(payload, dict):
            return jsonify(
                success=False, error="Expected a JSON network object."
            ), 400

        try:
            network = _load_network(payload)
            _apply_link_fidelities(network, payload)
            image = render_png(network)
        except (KeyError, ValueError) as exc:
            app.logger.warning("Rejected network: %s", exc)
            return jsonify(success=False, error=str(exc)), 400

        return jsonify(
            success=True,
            graph_image=base64.b64encode(image).decode(),
        ), 200

    return app
