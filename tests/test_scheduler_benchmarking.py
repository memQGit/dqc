from __future__ import annotations

import importlib.util
import logging
import sys
from pathlib import Path

import pytest

import memq_dqc.scheduler.schedule as schedule_module
from memq_dqc.scheduler.schedule import (
    SchedulerHardwareProfile,
    SchedulerTimingModel,
)


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


def _patch_scheduler_timing_model(monkeypatch: pytest.MonkeyPatch) -> None:
    def _load_timing_model(
        hardware_profile: SchedulerHardwareProfile,
    ) -> SchedulerTimingModel:
        return SchedulerTimingModel(
            hardware_profile=hardware_profile,
            local_one_qubit_gate_time=1.0,
            local_two_qubit_gate_time=5.0,
            entanglement_generation_rate=100.0,
            des_entanglement_time_step=1.0,
            epr_lifetime=50.0,
        )

    monkeypatch.setattr(
        schedule_module,
        "_load_scheduler_timing_model",
        _load_timing_model,
    )


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


def test_synthetic_initial_contention_case_changes_first_remote_start(
    monkeypatch: pytest.MonkeyPatch,
):
    _patch_scheduler_timing_model(monkeypatch)
    module = _load_benchmark_module()
    case = module.resolve_cases(["synthetic_initial_link_policy_contention"])[
        0
    ]
    distributed_circuit = module.build_case_distributed_circuit(case)

    first_remote_starts = {}
    for algorithm in module.DEFAULT_DES_ALGORITHMS:
        scheduler = module.Scheduler(
            distributed_circuit,
            algo=algorithm,
            profile=SchedulerHardwareProfile(),
            algo_kwargs={"seed": 0},
        )
        scheduler.run()
        assert scheduler.schedule is not None
        first_remote_starts[algorithm] = next(
            event.op_id
            for event in scheduler.schedule.operations
            if hasattr(event, "op_id") and event.op_id in {0, 1, 2}
        )

    assert first_remote_starts == {
        "des_link_fifo": 0,
        "des_link_shortest_duration": 0,
        "des_link_critical_path": 2,
    }


def test_qv_line_topology_tie_has_no_non_fifo_policy_choices():
    module = _load_benchmark_module()
    case = module.resolve_cases(["qv_12_line_topology"])[0]
    distributed_circuit = module.build_case_distributed_circuit(case)

    results = module.benchmark_des_algorithms(
        distributed_circuit=distributed_circuit,
        algorithms=module.DEFAULT_DES_ALGORITHMS,
        seed=0,
    )

    assert len({result.makespan for result in results}) == 1
    arbitration_stats = [result.arbitration for result in results]
    assert all(stats is not None for stats in arbitration_stats)
    assert {
        stats.multi_candidate_decisions
        for stats in arbitration_stats
        if stats is not None
    } == {0}
    assert {
        stats.non_fifo_selections
        for stats in arbitration_stats
        if stats is not None
    } == {0}


def test_log_benchmark_results_prints_makespan_units(caplog):
    module = _load_benchmark_module()
    results = [
        module.SchedulerBenchmarkResult(
            algorithm="des_link_fifo",
            makespan=12.5,
            operation_count=3,
        )
    ]

    with caplog.at_level(logging.INFO):
        module.log_benchmark_results(results)

    assert "makespan=    12.500 us" in caplog.text
    assert "Best makespan: des_link_fifo (12.500 us)" in caplog.text
