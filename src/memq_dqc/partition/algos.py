# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Partitioning algorithms for mapping logical qubits to network resources.

This module takes a graph representation of the quantum circuit and a graph
representation of the quantum network and applies partitioning algorithms to
map logical qubits to physical qubits in an optimized manner.
"""

import random

import networkx as nx

from memq_dqc.circuit import CircuitDAG
from memq_dqc.graph import InteractionGraph, NetworkGraph
from memq_dqc.utils import (
    create_initial_subcircuit_graph,
    generate_equal_partitions,
    get_edge_weight,
    get_windows,
    load_qasm_program,
    movement_cost,
    partition_cost,
    qubit_partition_set_to_map,
    verify_partition_sizes,
)
from memq_dqc.utils.circuit_utils import build_window_interaction_graph


def cisco_algo(
    circuit_filename: str,
    network: NetworkGraph,
    window_length: int = 2,
    # TODO: add input for state / gate costs
    # TODO: determine optimal window default
) -> tuple[float, list[list[set[int]]]]:
    """Partition qubits using the Cisco (TODO: cite) algorithm.

    Args:
        circuit_filename: QASM file that defines the circuit.
        network: Network graph describing available resources.
        window_length: Number of two-qubit gates per window.

    Returns:
        Total entanglement cost and the selected partition for each window.
    """
    # Load circuit and build interaction graph
    program = load_qasm_program(circuit_filename)
    interaction_graph = InteractionGraph(circuit_filename)
    circuit_graph = interaction_graph.graph.copy()

    num_qubits = interaction_graph.num_qubits
    # Compute logical qubits per QPU
    partition_sizes = network.comp_qubits_per_qpu()
    # Generate DAG from program
    dag = CircuitDAG(program)
    # Divide circuit into windows of given length
    windows = get_windows(dag, window_length)

    # Create initial partition using first subcircuit
    initial_subcircuit = create_initial_subcircuit_graph(
        num_qubits, windows[0]
    )
    # Partition the first subcircuit graph; use partitioning for rest
    partition_result = kl_partition(
        initial_subcircuit, partitions=partition_sizes
    )

    # Track selected partition and total entanglement cost for each window
    total_entanglement_cost = partition_cost(
        initial_subcircuit, partition_result
    )
    window_partitions = [partition_result]

    # Iterate through remaining windows to refine partitioning
    for i, ops in enumerate(windows[1:], start=1):
        p_old = window_partitions[i - 1]
        partition_map = qubit_partition_set_to_map(p_old)
        g, active_qubits = build_window_interaction_graph(ops, partition_map)
        # No active qubits in the window, continue
        if not active_qubits:
            window_partitions.append(p_old)
            #  layer = end_layer
            continue

        # Ignore unused qubits from previous partition, only consider active
        new_partition_sizes = [len(p & active_qubits) for p in p_old]
        # Create partition of active qubits for this window
        p_new_active = kl_partition(g, partitions=new_partition_sizes)
        # Fill back in the inactive qubits to get full partition at this window
        p_new = _merge_partitions_with_active(
            p_old, p_new_active, active_qubits
        )

        # Select partition with lower entanglement cost, add to schedule
        old_cost = partition_cost(g, p_old)
        new_cost = partition_cost(g, p_new) + movement_cost(p_new, p_old)
        if new_cost <= old_cost:
            window_partitions.append(p_new)
            total_entanglement_cost += new_cost
        else:
            window_partitions.append(p_old)
            total_entanglement_cost += old_cost

    return total_entanglement_cost, window_partitions


def _merge_partitions_with_active(
    p_old: list[set[int]],
    p_new_active: list[set[int]],
    active_qubits: set[int],
) -> list[set[int]]:
    """Merge active-qubit partitions into the previous full partition."""
    p_new = [set(p) for p in p_old]
    for idx in range(len(p_new)):
        p_new[idx] -= active_qubits
    for idx, part in enumerate(p_new_active):
        p_new[idx].update(part)
    return p_new


# TODO: how to implement these algorithms in a plug-and-play way?
def kl_partition(
    graph: nx.Graph,
    # TODO: re-implement support for # partitions for uniform partitions
    partitions: int | list[int],
    n_iter: int = 100,
    seed: int | None = 42,
) -> list[set[int]]:
    # TODO: generalize for non-uniform partitions
    # TODO: determine optimal number of iterations
    """Generic graph partitioning using the Kernighan-Lin (KL) algorithm.

    Args:
        graph: Graph to partition.
        partitions: Either the number of equal-sized partitions to create or
            explicit sizes for each partition group.
        n_iter: Number of refinement iterations.
        seed: Optional RNG seed for randomizing initial partitions.

    Returns:
        Partition groups where each group contains node IDs.
    """
    nodes = [int(n) for n in graph.nodes()]

    if isinstance(partitions, int):
        # Generate equal partitions if only number specified
        partitions = generate_equal_partitions(partitions, len(nodes))
    verify_partition_sizes(graph, partitions)

    num_partitions = len(partitions)

    # Initial partitioning
    rng = random.Random(seed)
    rng.shuffle(nodes)
    partition_result: list[set[int]] = []
    start = 0
    for size in partitions:
        chunk = nodes[start : start + size]
        partition_result.append(set(chunk))
        start += size

    for _ in range(n_iter):
        cost_reduced = False
        # Consider swaps between each pair of partition groups
        for a in range(num_partitions):
            for b in range(a + 1, num_partitions):
                group_a = partition_result[a]
                group_b = partition_result[b]
                new_a, new_b, gain = two_way_refine(graph, group_a, group_b)
                if gain > 0:
                    partition_result[a] = new_a
                    partition_result[b] = new_b
                    cost_reduced = True
        # Stop iterating if no cost reduction achieved
        if not cost_reduced:
            break

    return partition_result


def two_way_refine(
    graph: nx.Graph, group_a: set[int], group_b: set[int]
) -> tuple[set[int], set[int], float]:
    """Perform a two-way refinement between two groups using KL algorithm.

    Args:
        graph: Graph whose cut is being refined.
        group_a: First group of nodes.
        group_b: Second group of nodes.

    Returns:
        The updated groups and the achieved gain.
    """
    # Make copies to avoid modifying original sets
    group_a = set(group_a)
    group_b = set(group_b)
    D = compute_move_gains_for_pair(graph, group_a, group_b)

    locked: set[int] = set()  # Nodes that have been swapped already
    swaps: list[tuple[int, int]] = []  # Sequence of swaps
    gains: list[float] = []  # Cumulative gains after each swap

    num_swaps = min(len(group_a), len(group_b))
    for _ in range(num_swaps):
        best_pair = None
        best_gain = float("-inf")

        # Choose the best currently unlocked pair to swap
        for a in group_a:
            if a in locked:
                continue
            for b in group_b:
                if b in locked:
                    continue
                # pair gain = individual gains - edge weight (* 2 for double count)
                pair_gain = D[a] + D[b] - 2 * get_edge_weight(graph, a, b)
                if pair_gain > best_gain:
                    best_gain = pair_gain
                    best_pair = (a, b)

        # No valid swaps left to consider in this pass
        if best_pair is None:
            break

        # Add best candidate swap to sequence, lock nodes and mark gain
        a, b = best_pair
        swaps.append((a, b))
        gains.append(best_gain)
        locked.add(a)
        locked.add(b)

        # Recompute post-swap gain values for unlocked nodes in both groups
        for node in group_a:
            if node in locked:
                continue
            D[node] = (
                D[node]
                + 2 * get_edge_weight(graph, node, a)
                - 2 * get_edge_weight(graph, node, b)
            )
        for node in group_b:
            if node in locked:
                continue
            D[node] = (
                D[node]
                + 2 * get_edge_weight(graph, node, b)
                - 2 * get_edge_weight(graph, node, a)
            )

    # Determine best prefix of swaps to apply (how many of these swaps to do)
    best_prefix_gain = 0.0
    best_prefix_length = 0  # number of swaps to apply
    current_gain = 0.0

    for i, gain in enumerate(gains):
        current_gain += gain
        if current_gain > best_prefix_gain:
            best_prefix_gain = current_gain
            best_prefix_length = i + 1

    if best_prefix_gain <= 0:
        # No improvement found - return the original partition
        return group_a, group_b, 0.0

    # Apply the best number of swaps
    for i in range(best_prefix_length):
        # Perform swap
        a, b = swaps[i]
        group_a.remove(a)
        group_b.remove(b)
        group_a.add(b)
        group_b.add(a)

    return group_a, group_b, best_prefix_gain


def compute_move_gains_for_pair(
    graph: nx.Graph, group_a: set[int], group_b: set[int]
) -> dict[int, float]:
    """Compute KL move gains for nodes in group_a ∪ group_b.

    For each node x in group_a ∪ group_b, computes:
        gain[x] = (sum of weights to opposite group)
                - (sum of weights to same group)

    Positive gain means moving x to the other group reduces cut weight.

    Args:
        graph: Graph whose cut is being evaluated.
        group_a: First group of nodes.
        group_b: Second group of nodes.

    Returns:
        Mapping from node to move gain.
    """
    gains: dict[int, float] = {}
    combined = group_a | group_b

    for node in combined:
        same_group = group_a if node in group_a else group_b
        internal = 0.0
        external = 0.0
        for neighbor in graph.neighbors(node):
            if neighbor not in combined:
                continue  # edges to other partitions are constant
            weight = graph[node][neighbor].get("weight", 1.0)
            if neighbor in same_group:
                internal += weight
            else:
                external += weight
        gains[node] = external - internal

    return gains
