"""
Benchmark Evaluation Suite for AegisSRE Root-Cause Diagnosis Accuracy.

Evaluates Root Cause Identification Precision, Category Classification Accuracy,
and Latency across 50 synthetic incident scenarios in 100% deterministic SIMULATION_MODE.
"""

import asyncio
from collections import defaultdict
import json
import os
import sys
import time
from typing import Any, Dict, List

# Ensure parent directory is on sys.path for direct CLI runs
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.simulation.incident_generator import SyntheticIncidentGenerator
from src.workflow import AegisWorkflow


async def run_benchmark(
    count: int = 50,
    start_seed: int = 100,
    output_file: str = "benchmarks/benchmark_results.json",
) -> Dict[str, Any]:
    """
    Execute 50-scenario accuracy evaluation against AegisSRE multi-agent workflow.
    """
    print(f"\n================================================================================")
    print(f" AegisSRE Autonomous Incident Diagnosis Engine - Benchmark Suite")
    print(f" Evaluating {count} synthetic scenarios (Simulation Mode: 100% deterministic)")
    print(f"================================================================================\n")

    generator = SyntheticIncidentGenerator()
    suite = generator.generate_suite(count=count, start_seed=start_seed)
    workflow = AegisWorkflow()

    total_scenarios = len(suite)
    correct_service_count = 0
    correct_category_count = 0
    latencies: List[float] = []

    per_scenario_stats: Dict[str, Dict[str, Any]] = defaultdict(
        lambda: {"total": 0, "correct_service": 0, "correct_category": 0, "latencies": []}
    )

    start_eval_time = time.perf_counter()

    for idx, (incident, ground_truth_service, ground_truth_cat) in enumerate(suite, start=1):
        t0 = time.perf_counter()
        report = await workflow.run(incident)
        duration_ms = (time.perf_counter() - t0) * 1000
        latencies.append(duration_ms)

        pred_service = report.root_cause.root_cause_service
        pred_category = report.root_cause.incident_category

        is_service_correct = pred_service == ground_truth_service
        is_category_correct = pred_category == ground_truth_cat

        if is_service_correct:
            correct_service_count += 1
        if is_category_correct:
            correct_category_count += 1

        scenario_name = incident.metadata.get("scenario", "unknown")
        stats = per_scenario_stats[scenario_name]
        stats["total"] += 1
        if is_service_correct:
            stats["correct_service"] += 1
        if is_category_correct:
            stats["correct_category"] += 1
        stats["latencies"].append(duration_ms)

        status_sym = "[OK]" if (is_service_correct and is_category_correct) else "[WARN]"
        print(
            f" Scenario {idx:02d}/{total_scenarios:02d} {status_sym} "
            f"Scenario: {scenario_name:<22} | "
            f"Truth: {ground_truth_service:<18} | Pred: {pred_service:<18} | "
            f"Latency: {duration_ms:5.1f}ms"
        )

    total_eval_duration = time.perf_counter() - start_eval_time
    service_accuracy = (correct_service_count / total_scenarios) * 100
    category_accuracy = (correct_category_count / total_scenarios) * 100
    mean_latency = sum(latencies) / len(latencies) if latencies else 0.0
    sorted_latencies = sorted(latencies)
    p95_latency = sorted_latencies[int(len(sorted_latencies) * 0.95)] if sorted_latencies else 0.0

    print("\n--------------------------------------------------------------------------------")
    print(f" Summary by Incident Scenario Type:")
    print("--------------------------------------------------------------------------------")
    print(f" {'Scenario':<25} | {'Count':<5} | {'Service Acc':<11} | {'Category Acc':<12} | {'Avg Latency'}")
    print("--------------------------------------------------------------------------------")
    for s_name, s_data in per_scenario_stats.items():
        s_tot = s_data["total"]
        s_acc = (s_data["correct_service"] / s_tot) * 100 if s_tot else 0
        c_acc = (s_data["correct_category"] / s_tot) * 100 if s_tot else 0
        avg_lat = sum(s_data["latencies"]) / len(s_data["latencies"]) if s_data["latencies"] else 0
        print(f" {s_name:<25} | {s_tot:<5} | {s_acc:9.1f}% | {c_acc:10.1f}% | {avg_lat:6.1f} ms")

    print("================================================================================")
    print(f" OVERALL BENCHMARK RESULTS:")
    print(f"  - Total Scenarios Evaluated  : {total_scenarios}")
    print(f"  - Root Cause Service Accuracy: {service_accuracy:.1f}% ({correct_service_count}/{total_scenarios})")
    print(f"  - Incident Category Accuracy : {category_accuracy:.1f}% ({correct_category_count}/{total_scenarios})")
    print(f"  - Mean Diagnosis Latency     : {mean_latency:.1f} ms")
    print(f"  - P95 Diagnosis Latency      : {p95_latency:.1f} ms")
    print(f"  - Total Benchmark Wall Time  : {total_eval_duration:.2f} s")
    print("================================================================================\n")

    results_data = {
        "timestamp": time.time(),
        "total_scenarios": total_scenarios,
        "service_accuracy_percent": round(service_accuracy, 2),
        "category_accuracy_percent": round(category_accuracy, 2),
        "mean_latency_ms": round(mean_latency, 2),
        "p95_latency_ms": round(p95_latency, 2),
        "total_wall_time_s": round(total_eval_duration, 2),
        "per_scenario_breakdown": {
            k: {
                "total": v["total"],
                "service_accuracy_percent": round((v["correct_service"] / v["total"]) * 100, 2),
                "category_accuracy_percent": round((v["correct_category"] / v["total"]) * 100, 2),
                "avg_latency_ms": round(sum(v["latencies"]) / len(v["latencies"]), 2),
            }
            for k, v in per_scenario_stats.items()
        },
    }

    try:
        os.makedirs(os.path.dirname(output_file), exist_ok=True)
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results_data, f, indent=2)
        print(f" Benchmark results successfully saved to: {output_file}")
    except Exception as e:
        print(f" Warning: Failed to write {output_file}: {e}")

    return results_data


def main():
    results = asyncio.run(run_benchmark(count=50, start_seed=100))
    # Threshold check for benchmark suite passing
    if results["service_accuracy_percent"] < 90.0:
        print(f"ERROR: Service accuracy {results['service_accuracy_percent']}% fell below 90% threshold.")
        sys.exit(1)
    sys.exit(0)


if __name__ == "__main__":
    main()
