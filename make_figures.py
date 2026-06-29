"""Generate publication figures from the compiler benchmark CSV.

Produces high-DPI PNGs comparing the proposed partitioning algorithms
(interaction, hypergraph) against the static/random baselines across
EPR-pair cost, network topology, and circuit-size scaling.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
from matplotlib.ticker import FuncFormatter

CSV = Path(
    "benchmarking/compiler_benchmarking/results/benchmark_20260616_112145.csv"
)
OUT = Path("benchmarking/compiler_benchmarking/results/figures")
OUT.mkdir(parents=True, exist_ok=True)

# ── Style ────────────────────────────────────────────────────────────────
plt.rcParams.update(
    {
        "font.family": "serif",
        "font.size": 11,
        "axes.titlesize": 12,
        "axes.titleweight": "bold",
        "axes.labelsize": 11,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "grid.linewidth": 0.6,
        "axes.axisbelow": True,
        "figure.dpi": 300,
        "savefig.dpi": 300,
        "savefig.bbox": "tight",
        "legend.frameon": False,
    }
)

# Algorithm display names + colours (colourblind-safe; proposed = bold hues)
ALGOS = ["interaction", "hypergraph", "benchmark_static", "benchmark_random"]
LABELS = {
    "interaction": "Interaction (ours)",
    "hypergraph": "Hypergraph (ours)",
    "benchmark_static": "Static (baseline)",
    "benchmark_random": "Random (baseline)",
}
COLORS = {
    "interaction": "#0072B2",
    "hypergraph": "#009E73",
    "benchmark_static": "#999999",
    "benchmark_random": "#D55E00",
}
HATCH = {
    "interaction": "",
    "hypergraph": "",
    "benchmark_static": "//",
    "benchmark_random": "..",
}

TOPO_ORDER = [
    "fully_connected_2qpu",
    "nearest_neighbor_2qpu",
    "ring_3qpu",
    "grid_4qpu",
]
TOPO_LABELS = {
    "fully_connected_2qpu": "Full\n(2 QPU)",
    "nearest_neighbor_2qpu": "Near-neigh.\n(2 QPU)",
    "ring_3qpu": "Ring\n(3 QPU)",
    "grid_4qpu": "Grid\n(4 QPU)",
}

# Circuit display order by qubit count
CIRC_ORDER = [
    "multiply_n13_transpiled",
    "qft_n18_transpiled",
    "adder_n28_transpiled",
    "qft_n29_transpiled",
    "adder_n64_transpiled",
    "multiplier_n75_transpiled",
    "qv_100",
]
CIRC_LABELS = {
    "multiply_n13_transpiled": "mult\nn13",
    "qft_n18_transpiled": "qft\nn18",
    "adder_n28_transpiled": "adder\nn28",
    "qft_n29_transpiled": "qft\nn29",
    "adder_n64_transpiled": "adder\nn64",
    "multiplier_n75_transpiled": "mult\nn75",
    "qv_100": "qv\nn100",
}

df = pd.read_csv(CSV)


def _save(fig: plt.Figure, name: str) -> None:
    path = OUT / name
    fig.savefig(path)
    plt.close(fig)
    print("wrote", path)


# ── Figure 1: Algorithm vs baselines ──────────────────────────────────────
def fig_algo_vs_baseline() -> None:
    """Plot entanglement cost and overhead per algorithm vs baselines."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.6))

    # (a) Geometric-mean EPR per algorithm (geo-mean handles wide range).
    geo = {}
    for a in ALGOS:
        vals = df[df.algorithm == a]["epr_pairs"].to_numpy()
        vals = vals[vals > 0]
        geo[a] = np.exp(np.mean(np.log(vals)))
    x = np.arange(len(ALGOS))
    bars = ax1.bar(
        x,
        [geo[a] for a in ALGOS],
        color=[COLORS[a] for a in ALGOS],
        edgecolor="black",
        linewidth=0.7,
        hatch=[HATCH[a] for a in ALGOS],
    )
    ax1.set_xticks(x)
    ax1.set_xticklabels(
        [LABELS[a].replace(" (", "\n(") for a in ALGOS], fontsize=9.5
    )
    ax1.set_ylabel("EPR pairs (geometric mean)")
    ax1.set_title("(a) Entanglement cost across all cases")
    for b, a in zip(bars, ALGOS, strict=True):
        ax1.text(
            b.get_x() + b.get_width() / 2,
            b.get_height(),
            f"{geo[a]:.0f}",
            ha="center",
            va="bottom",
            fontsize=9,
        )
    ax1.margins(y=0.15)

    # (b) Per-case EPR reduction of best-proposed vs best-baseline.
    base = (
        df[df.algorithm.isin(["benchmark_static", "benchmark_random"])]
        .groupby(["circuit_name", "network_topology"])["epr_pairs"]
        .min()
    )
    prop = (
        df[df.algorithm.isin(["interaction", "hypergraph"])]
        .groupby(["circuit_name", "network_topology"])["epr_pairs"]
        .min()
    )
    red = ((1 - prop / base) * 100).reset_index()
    red["circuit_name"] = pd.Categorical(
        red["circuit_name"], CIRC_ORDER, ordered=True
    )
    piv = red.pivot_table(
        index="network_topology",
        columns="circuit_name",
        values="epr_pairs",
        observed=False,
    ).reindex(TOPO_ORDER)

    n_circ = len(CIRC_ORDER)
    width = 0.8 / n_circ
    xt = np.arange(len(TOPO_ORDER))
    cmap = plt.get_cmap("viridis")
    for i, c in enumerate(CIRC_ORDER):
        ax2.bar(
            xt + i * width,
            piv[c].to_numpy(),
            width,
            label=CIRC_LABELS[c].replace("\n", " "),
            color=cmap(i / (n_circ - 1)),
            edgecolor="black",
            linewidth=0.4,
        )
    ax2.axhline(0, color="black", linewidth=0.8)
    ax2.set_xticks(xt + 0.4 - width / 2)
    ax2.set_xticklabels([TOPO_LABELS[t] for t in TOPO_ORDER], fontsize=9)
    ax2.set_ylabel("EPR reduction vs best baseline (%)")
    ax2.set_title("(b) Improvement by circuit and topology")
    ax2.legend(fontsize=7.5, ncol=2, loc="upper right", title="circuit")

    fig.suptitle(
        "Proposed partitioners vs baselines: entanglement cost",
        fontsize=13,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    _save(fig, "fig1_algorithm_vs_baseline.png")


# ── Figure 2: Topology effects ────────────────────────────────────────────
def fig_topology() -> None:
    """Plot EPR cost broken down by network topology."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.6))

    # (a) geo-mean EPR per topology grouped by algorithm
    width = 0.2
    xt = np.arange(len(TOPO_ORDER))
    for i, a in enumerate(ALGOS):
        vals = []
        for t in TOPO_ORDER:
            v = df[(df.algorithm == a) & (df.network_topology == t)][
                "epr_pairs"
            ].to_numpy()
            v = v[v > 0]
            vals.append(np.exp(np.mean(np.log(v))) if len(v) else np.nan)
        ax1.bar(
            xt + i * width,
            vals,
            width,
            label=LABELS[a],
            color=COLORS[a],
            edgecolor="black",
            linewidth=0.5,
            hatch=HATCH[a],
        )
    ax1.set_xticks(xt + 1.5 * width)
    ax1.set_xticklabels([TOPO_LABELS[t] for t in TOPO_ORDER], fontsize=9)
    ax1.set_ylabel("EPR pairs (geometric mean)")
    ax1.set_yscale("log")
    ax1.set_title("(a) Entanglement cost by topology")
    ax1.legend(fontsize=8)

    # (b) remote gates vs local swaps for the interaction method
    sub = (
        df[df.algorithm == "interaction"]
        .groupby("network_topology")[["remote_gates", "local_swaps_added"]]
        .mean()
        .reindex(TOPO_ORDER)
    )
    width = 0.38
    ax2.bar(
        xt,
        sub["remote_gates"],
        width,
        label="Remote gates",
        color="#0072B2",
        edgecolor="black",
        linewidth=0.5,
    )
    ax2.bar(
        xt + width,
        sub["local_swaps_added"],
        width,
        label="Local SWAPs added",
        color="#E69F00",
        edgecolor="black",
        linewidth=0.5,
    )
    ax2.set_xticks(xt + width / 2)
    ax2.set_xticklabels([TOPO_LABELS[t] for t in TOPO_ORDER], fontsize=9)
    ax2.set_ylabel("Mean operation count")
    ax2.set_title("(b) Routing cost breakdown (interaction)")
    ax2.legend(fontsize=8)

    fig.suptitle(
        "Network topology drives entanglement and routing cost",
        fontsize=13,
        fontweight="bold",
    )
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    _save(fig, "fig2_topology_effects.png")


# ── Figure 3: Scaling ─────────────────────────────────────────────────────
def fig_scaling() -> None:
    """Plot EPR cost scaling with circuit size."""
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(12, 4.6))

    # (a) EPR vs two-qubit gate count (the true cost driver), log-log.
    # Average over topologies per circuit; x = original 2q gate count.
    for a in ALGOS:
        g = (
            df[df.algorithm == a]
            .groupby(["original_2q_gates"])["epr_pairs"]
            .mean()
            .sort_index()
        )
        ax1.plot(
            g.index,
            g.values,
            marker="o",
            markersize=5,
            color=COLORS[a],
            label=LABELS[a],
            linewidth=1.8,
        )
    # Linear-scaling reference line through the cloud.
    ref_x = np.array([df.original_2q_gates.min(), df.original_2q_gates.max()])
    ax1.plot(
        ref_x,
        ref_x * 0.5,
        ls="--",
        color="black",
        linewidth=1.0,
        alpha=0.6,
        label="linear reference",
    )
    ax1.set_xscale("log")
    ax1.set_yscale("log")
    ax1.set_xlabel("Two-qubit gates in input circuit")
    ax1.set_ylabel("EPR pairs (mean over topologies)")
    ax1.set_title("(a) Entanglement cost vs circuit complexity")
    ax1.legend(fontsize=8)
    ax1.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))

    # (b) runtime vs qubit count, log-log
    for a in ALGOS:
        g = (
            df[df.algorithm == a]
            .groupby("circuit_num_qubits")["runtime_seconds"]
            .mean()
            .sort_index()
        )
        ax2.plot(
            g.index,
            g.values,
            marker="s",
            markersize=5,
            color=COLORS[a],
            label=LABELS[a],
            linewidth=1.8,
        )
    ax2.set_xscale("log")
    ax2.set_yscale("log")
    ax2.set_xlabel("Circuit size (qubits)")
    ax2.set_ylabel("Runtime (s, mean over topologies)")
    ax2.set_title("(b) Compile-time scaling")
    ax2.legend(fontsize=8)
    ax2.xaxis.set_major_formatter(FuncFormatter(lambda v, _: f"{v:g}"))

    fig.suptitle("Scaling with circuit size", fontsize=13, fontweight="bold")
    fig.tight_layout(rect=(0, 0, 1, 0.95))
    _save(fig, "fig3_scaling.png")


if __name__ == "__main__":
    fig_algo_vs_baseline()
    fig_topology()
    fig_scaling()
