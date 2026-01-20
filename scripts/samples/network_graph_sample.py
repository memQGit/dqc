# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

from memq_dqc.graph import build_network_graph, display_network_graph

repo_root = Path(__file__).resolve().parents[2]
sample_json = (
    repo_root
    / "src"
    / "memq_dqc"
    / "graph"
    / "sample_networks"
    / "simple1.json"
)

graph, qubit_type_map = build_network_graph(str(sample_json))
display_network_graph(graph)
