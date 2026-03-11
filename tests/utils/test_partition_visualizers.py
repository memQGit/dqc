# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import pytest

from memq_dqc.partition.partitioner import QPU
from memq_dqc.visualization import SvgDocument
from memq_dqc.visualization.partition_visualizer import (
    plot_migration_timeline,
    plot_partition_heatmap,
)


def _sample_partition() -> list[dict[QPU, set[int]]]:
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    return [
        {qpu0: {0, 1}, qpu1: {2, 3}},
        {qpu0: {0, 2}, qpu1: {1, 3}},
        {qpu0: {0, 2}, qpu1: {1, 3}},
        {qpu0: {0, 1}, qpu1: {2, 3}},
    ]


def test_partition_heatmap_top_k() -> None:
    document = plot_partition_heatmap(
        _sample_partition(),
        title="Custom heatmap title",
        top_k_most_moved=2,
    )

    assert isinstance(document, SvgDocument)
    assert "Custom heatmap title" in document.svg
    assert document.svg.count("<rect") >= 8


def test_migration_timeline_entanglement_length_mismatch() -> None:
    with pytest.raises(ValueError, match="window_entanglement_cost"):
        plot_migration_timeline(
            _sample_partition(),
            window_entanglement_cost=[1.0],
        )
