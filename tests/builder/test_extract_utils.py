# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

from memq_dqc.builder.extract_utils import synthesize_state_teleportation_swaps
from memq_dqc.partition.partitioner import QPU


def test_synthesize_swaps_emits_only_cross_qpu_swaps() -> None:
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    qpu2 = QPU(id=2)
    schedule = [
        {qpu0: {0, 1}, qpu1: {2, 3}, qpu2: {4, 5}},
        {qpu0: {0, 3}, qpu1: {1, 4}, qpu2: {2, 5}},
    ]

    swaps = synthesize_state_teleportation_swaps(schedule)

    assert len(swaps) == 1
    assert swaps[0]
    assert all(swap.pos0[0] != swap.pos1[0] for swap in swaps[0])


def test_synthesize_swaps_handles_three_qpu_cycle() -> None:
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    qpu2 = QPU(id=2)
    schedule = [
        {qpu0: {0, 1}, qpu1: {2, 3}, qpu2: {4, 5}},
        {qpu0: {1, 4}, qpu1: {0, 5}, qpu2: {2, 3}},
    ]

    swaps = synthesize_state_teleportation_swaps(schedule)

    assert len(swaps) == 1
    assert all(swap.pos0[0] != swap.pos1[0] for swap in swaps[0])


def test_synthesize_swaps_positions_remain_consistent_across_timesteps() -> (
    None
):
    qpu0 = QPU(id=0)
    qpu1 = QPU(id=1)
    schedule = [
        {qpu0: {0, 1}, qpu1: {2, 3}},
        {qpu0: {1, 2}, qpu1: {0, 3}},
        {qpu0: {0, 1}, qpu1: {2, 3}},
    ]

    swaps = synthesize_state_teleportation_swaps(schedule)

    assert len(swaps) == 2

    current_pos_by_qubit = {
        0: (0, 0),
        1: (0, 1),
        2: (1, 0),
        3: (1, 1),
    }
    for timestep_swaps in swaps:
        for swap in timestep_swaps:
            assert swap.pos0 == current_pos_by_qubit[swap.q0]
            assert swap.pos1 == current_pos_by_qubit[swap.q1]
            current_pos_by_qubit[swap.q0], current_pos_by_qubit[swap.q1] = (
                current_pos_by_qubit[swap.q1],
                current_pos_by_qubit[swap.q0],
            )
