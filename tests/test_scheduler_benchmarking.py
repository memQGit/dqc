from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


def _load_benchmark_module():
    repo_root = Path(__file__).resolve().parents[1]
    module_path = (
        repo_root
        / "benchmarking"
        / "scheduler_benchmarking"
        / "run_des_scheduler_benchmark.py"
    )
    spec = importlib.util.spec_from_file_location(
        "run_des_scheduler_benchmark",
        module_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_qv_12_line_topology_case_resolves_to_existing_assets():
    module = _load_benchmark_module()

    resolved_cases = module.resolve_cases(["qv_12_line_topology"])

    assert len(resolved_cases) == 1
    case = resolved_cases[0]
    assert case.name == "qv_12_line_topology"
    assert case.circuit_path is not None
    assert case.network_path is not None
    assert case.circuit_path.exists()
    assert case.network_path.exists()


def test_synthetic_divergence_cases_produce_distinct_makespans():
    module = _load_benchmark_module()

    for case_name in (
        "synthetic_shortest_vs_tail_contention",
        "synthetic_critical_path_fanout_contention",
        "synthetic_deferred_two_lane_mixed_contention",
    ):
        case = module.resolve_cases([case_name])[0]
        distributed_circuit = module.build_case_distributed_circuit(case)
        results = module.benchmark_des_algorithms(
            distributed_circuit=distributed_circuit,
            algorithms=module.DEFAULT_DES_ALGORITHMS,
            seed=0,
        )

        assert len({result.makespan for result in results}) > 1
