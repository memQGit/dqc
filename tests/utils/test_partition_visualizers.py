# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import pytest

from memq_dqc.partition.types import QPU
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
    partition = _sample_partition()
    _, ax = plt.subplots()

    ax = plot_partition_heatmap(
        partition,
        top_k_most_moved=2,
        ax=ax,
        show=False,
    )

    assert ax.images
    array = ax.images[0].get_array()
    assert array.shape == (2, len(partition))


def test_migration_timeline_entanglement_length_mismatch() -> None:
    partition = _sample_partition()
    _, ax = plt.subplots()

    with pytest.raises(ValueError, match="window_entanglement_cost"):
        plot_migration_timeline(
            partition,
            window_entanglement_cost=[1.0],
            ax=ax,
            show=False,
        )
