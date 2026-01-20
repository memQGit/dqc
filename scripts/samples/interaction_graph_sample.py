# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from pathlib import Path

from memq_dqc.graph import build_interaction_graph, display_interaction_graph

repo_root = Path(__file__).resolve().parents[2]
qasm_path_simple1 = (
    repo_root
    / "src"
    / "memq_dqc"
    / "graph"
    / "sample_circuits"
    / "simple1.qasm"
)

graph = build_interaction_graph(str(qasm_path_simple1))
display_interaction_graph(graph)
