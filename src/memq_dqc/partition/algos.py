# ============================================================================
# Copyright (c) 2026 memQ Inc.
#
# This source code is licensed under the MIT License.
# See the LICENSE file in the project root for full license information.
# ============================================================================

"""Partitioning algorithms for mapping logical qubits to physical qubits.

This module takes a graph representation of the quantum circuit and a graph
representation of the quantum network and applies partitioning algorithms to
map logical qubits to physical qubits in an optimized manner.

Typical usage example:

  TODO: Add usage example here.
"""

import math
import random

import networkx as nx

from memq_dqc.circuit import CircuitDAG
from memq_dqc.graph import NetworkGraph, build_interaction_graph
from memq_dqc.utils import (
    count_two_qubit_pairs,
    create_initial_subcircuit_graph,
    create_subcircuit_graphs,
    distribute,
    generate_equal_partitions,
    get_edge_weight,
    load_qasm_program,
    movement_cost,
    partition_cost,
    qubit_partition_set_to_map,
    verify_partition_sizes,
)


def cisco_algo(
    circuit_filename: str, network: NetworkGraph, window_length=2
) -> dict:
    """Partition qubits using the Cisco (TODO: cite) algorithm.

    Args:
        circuit_filename (str): The filename of the quantum circuit in QASM format.
        network (NetworkGraph): The network graph representing the quantum network.
        window_size (int): The size of the window for subcircuit partitioning.
            # TODO: DETERMINE OPTIMAL DEFAULT WINDOW SIZE

    Returns:
        dict: A mapping from qubit indices to physical qubit indices.
    """
    # Load circuit and build interaction graph
    program = load_qasm_program(circuit_filename)
    interaction_graph = build_interaction_graph(circuit_filename)
    circuit_graph = interaction_graph.copy()
    # TODO: interaction graph needs to be object wiwth num_qubits attribute
    num_qubits = circuit_graph.number_of_nodes()
    # Compute logical qubits per QPU
    partition_sizes = network.comp_qubits_per_qpu()

    # Generate DAG from program
    dag = CircuitDAG(program)
    # TODO: cite this formula (cisco paper)
    num_subcircuits = math.ceil(dag.num_two_qubit_gates / window_length)
    # First, generate the initial subcircuit graph as standard interaction graph
    initial_subcircuit = create_initial_subcircuit_graph(
        dag, num_qubits, num_subcircuits
    )
    # Partition the first subcircuit graph; use partitioning for rest
    partition_result = kl_partition(
        initial_subcircuit, partitions=partition_sizes
    )

    # Create n subcircuit graphs using the initial partition
    subcircuit_graphs = create_subcircuit_graphs(
        dag, num_qubits, num_subcircuits, partition_result
    )

    # Track selected partition and total entanglement cost for each window
    total_entanglement_cost = partition_cost(
        initial_subcircuit, partition_result
    )
    print("initial partition", partition_result)
    print("\n")
    window_partitions = [partition_result]
    layer_sizes = distribute(dag.depth, num_subcircuits)

    layer = layer_sizes[0]
    for i, num_layers in enumerate(layer_sizes[1:], start=1):
        partition_map = qubit_partition_set_to_map(window_partitions[i - 1])
        end_layer = min(layer + num_layers, dag.depth)
        combined_layers = dag.layers[layer:end_layer]
        ops = [op for layer_ops in combined_layers for op in layer_ops]
        two_qubit_counts = count_two_qubit_pairs(
            op.qubits for op in ops if len(op.qubits) == 2
        )
        g = nx.Graph()
        for q in range(num_qubits):
            g.add_node(q)
        for (k, j), count in two_qubit_counts.items():
            weight = count
            part_i = partition_map.get(k)
            part_j = partition_map.get(j)
            if part_i == part_j:
                # Double weight to prefer non-remote gates
                g.add_edge(k, j, weight=(weight * 2))
            else:
                g.add_edge(k, j, weight=weight)
        # print edges and weights
        print(f"Subcircuit {i} edges and weights:")
        for u, v, data in g.edges(data=True):
            print(f"  ({u}, {v}): weight = {data.get('weight', 1)}")
        p_old = window_partitions[i - 1]
        p_new = kl_partition(g, partitions=partition_sizes)
        old_cost = partition_cost(g, p_old)
        new_cost = partition_cost(g, p_new) + movement_cost(p_new, p_old)
        print("old partition:", p_old, "cost:", old_cost)
        print(
            f"new partition: {p_new} cost: {new_cost} -> {partition_cost(g, p_new)} + {movement_cost(p_new, p_old)}"
        )
        print("=" * 100)
        print("\n")
        if new_cost < old_cost:
            window_partitions.append(p_new)
            total_entanglement_cost += new_cost
        else:
            window_partitions.append(p_old)
            total_entanglement_cost += old_cost
        layer = end_layer

    return total_entanglement_cost, window_partitions


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
        graph (nx.Graph): The network graph representing the quantum network.
        partitions (int | list[int]): Either the number of equal-sized partitions
            to create (e.g., 4 creates 4 equal partitions), or a list specifying
            the size of each partition (e.g., [3, 5, 7] creates 3 partitions of
            sizes 3, 5, and 7 respectively).
        n_iter (int): Number of iterations for the partitioning algorithm.
        seed (int | None): Optional RNG seed for randomizing initial partitions.

    Returns:
        A list of sets, where each set contains the node IDs in that partition.
        For example: [{2, 3, 4}, {0, 1, 5}] represents two partitions.
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
    # TODO: Docstring, determine where to keep / package this function
    """Perform a two-way refinement between two groups using KL algorithm."""
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
        graph: The input graph.
        group_a: The first group of nodes.
        group_b: The second group of nodes.

    Returns:
        Mapping from node to move gain. Positive values indicate that
        moving the node to the opposite group reduces the cut cost.
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


""" 
Algorithm 3

Inputs:
circuit, window length
Steps:
1. divide circuit into subcircuits (C_i's) of different window lengths
2. set entanglement cost to 0 (EC = 0)
3. FOR the FIRST subcircuit:
    a. Run algorithm 1:
        i. Construct interaction graph
        ii. Use KL algorithm to partition graph
        iii. Obtain partition P1
4. FOR remaining subcircuits:
    a. Construct a new graph Gi where nodes are qubits involved in the subcircuit
    b. FOR each pair of qubits (u, v) in Gi:
      i. IF nodes are in same subset of partition
          - THEN add edge with weight 2x number of 2-qubit gates between them
          - ELSE add edge with weight equal to the number of CNOT gates
    c. Apply partitioning algorithm to Gi to get new partition P_new
    d. Compute new and old entanglement costs
    e. IF new entanglement cost < old entanglement cost:
        i. THEN Update partition to P_new
        ii. ELSE keep old partition
    f. Update total entanglement cost with updated partition
5. Return total entanglement cost, final partition (for each window)


"""
