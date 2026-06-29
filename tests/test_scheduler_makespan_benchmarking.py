from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_benchmark_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = (
        repo_root
        / "benchmarking"
        / "scheduler_makespan_benchmarking"
        / "run_scheduler_makespan_benchmark.py"
    )
    spec = importlib.util.spec_from_file_location(
        "run_scheduler_makespan_benchmark",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_extract_qubit_count_handles_both_patterns():
    module = _load_benchmark_module()

    assert module._extract_qubit_count("qft_n18_transpiled") == 18
    assert module._extract_qubit_count("qv_100") == 100
    assert module._extract_qubit_count("no_count_here") is None


def test_discover_benchmark_cases_pairs_circuit_with_matching_networks(
    tmp_path: Path,
):
    module = _load_benchmark_module()

    # Arrange: one 4-qubit circuit and a matching 4_qubits network folder
    # with two topologies (plus an unrelated folder that must be ignored).
    circuits_dir = tmp_path / "circuits"
    networks_dir = tmp_path / "networks"
    circuits_dir.mkdir()
    (circuits_dir / "demo_n4_transpiled.qasm").write_text("// qasm")
    net_dir = networks_dir / "4_qubits"
    net_dir.mkdir(parents=True)
    (net_dir / "ring_2qpu.json").write_text("{}")
    (net_dir / "line_2qpu.json").write_text("{}")
    other_dir = networks_dir / "9_qubits"
    other_dir.mkdir()
    (other_dir / "grid_3qpu.json").write_text("{}")

    # Act
    cases = module.discover_benchmark_cases(circuits_dir, networks_dir)

    # Assert: exactly the two matching pairs, sorted by topology.
    assert [c.network_topology for c in cases] == ["line_2qpu", "ring_2qpu"]
    assert all(c.circuit_num_qubits == 4 for c in cases)
    assert cases[0].name == "demo_n4_transpiled__line_2qpu"


def test_discover_benchmark_cases_skips_circuit_without_network_folder(
    tmp_path: Path,
):
    module = _load_benchmark_module()

    circuits_dir = tmp_path / "circuits"
    networks_dir = tmp_path / "networks"
    circuits_dir.mkdir()
    networks_dir.mkdir()
    (circuits_dir / "lonely_n7_transpiled.qasm").write_text("// qasm")

    cases = module.discover_benchmark_cases(circuits_dir, networks_dir)

    assert cases == []


def test_aggregate_makespans_computes_mean_std_min_max():
    module = _load_benchmark_module()

    stats = module.aggregate_makespans([10.0, 20.0, 30.0, 40.0])

    assert stats.mean == 25.0
    assert stats.min == 10.0
    assert stats.max == 40.0
    # Sample standard deviation of [10, 20, 30, 40].
    assert abs(stats.std - 12.909944487358056) < 1e-9


def test_aggregate_makespans_single_sample_has_zero_std():
    module = _load_benchmark_module()

    stats = module.aggregate_makespans([42.0])

    assert stats.mean == 42.0
    assert stats.std == 0.0
    assert stats.min == 42.0
    assert stats.max == 42.0


def test_aggregate_makespans_rejects_empty_sequence():
    module = _load_benchmark_module()

    try:
        module.aggregate_makespans([])
    except ValueError:
        return
    raise AssertionError("expected ValueError for empty sequence")


def test_seed_sequence_is_deterministic():
    module = _load_benchmark_module()

    assert module._seed_sequence(4, 0) == [0, 1, 2, 3]
    assert module._seed_sequence(3, 5) == [5, 6, 7]


def test_wins_by_algorithm_counts_lowest_mean_and_ties():
    module = _load_benchmark_module()

    def _result(algorithm, mean_makespan):
        return module.MakespanBenchmarkResult(
            circuit_name="c",
            circuit_num_qubits=4,
            network_topology="ring",
            num_qpus=2,
            algorithm=algorithm,
            num_seeds=1,
            makespan_mean=mean_makespan,
            makespan_std=0.0,
            makespan_min=mean_makespan,
            makespan_max=mean_makespan,
            seed_makespans=((0, mean_makespan),),
        )

    results = [
        _result("des_link_fifo", 10.0),
        _result("des_link_shortest_duration", 10.0),
        _result("des_link_critical_path", 20.0),
    ]

    wins = module._wins_by_algorithm(results)

    assert wins["des_link_fifo"] == 1
    assert wins["des_link_shortest_duration"] == 1
    assert "des_link_critical_path" not in wins
