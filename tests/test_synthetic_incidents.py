"""
Tests for Synthetic Incident Generation and 100% Determinism.
"""

import pytest
from src.api.schemas import IncidentCategory
from src.simulation.incident_generator import (
    IncidentScenario,
    SyntheticIncidentGenerator,
    generate_synthetic_incident,
)


def test_incident_generator_determinism():
    """Verify identical seed + scenario produces identical incident structures."""
    gen = SyntheticIncidentGenerator()

    inc1, root1, cat1 = gen.generate(scenario=IncidentScenario.DB_POOL_EXHAUSTION, seed=42)
    inc2, root2, cat2 = gen.generate(scenario=IncidentScenario.DB_POOL_EXHAUSTION, seed=42)

    assert root1 == root2 == "order-service"
    assert cat1 == cat2 == IncidentCategory.DATABASE_POOL_EXHAUSTION
    assert inc1.incident_id == inc2.incident_id
    assert len(inc1.metrics) == len(inc2.metrics)
    assert len(inc1.traces) == len(inc2.traces)
    assert len(inc1.commits) == len(inc2.commits)
    assert inc1.commits[0].commit_hash == inc2.commits[0].commit_hash
    assert inc1.metrics[0].value == inc2.metrics[0].value


def test_all_scenarios_generation():
    """Verify every scenario generates valid incident payloads and correct metadata."""
    gen = SyntheticIncidentGenerator()

    scenarios = [
        (IncidentScenario.DB_POOL_EXHAUSTION, "order-service", IncidentCategory.DATABASE_POOL_EXHAUSTION),
        (IncidentScenario.MEMORY_LEAK, "payment-service", IncidentCategory.MEMORY_LEAK_OOM),
        (IncidentScenario.CASCADING_503, "auth-service", IncidentCategory.CASCADING_503_CIRCUIT_BREAKER_TRIP),
        (IncidentScenario.CONFIG_REGRESSION, "inventory-service", IncidentCategory.CONFIG_REGRESSION),
        (IncidentScenario.CACHE_STAMPEDE, "catalog-service", IncidentCategory.CACHE_STAMPEDE),
    ]

    for scenario, expected_root, expected_cat in scenarios:
        inc, root, cat = gen.generate(scenario=scenario, seed=99)
        assert root == expected_root, f"Failed for {scenario}"
        assert cat == expected_cat, f"Failed for {scenario}"
        assert inc.incident_id is not None
        assert len(inc.metrics) > 0
        assert len(inc.traces) > 0
        assert len(inc.commits) > 0


def test_convenience_generator_helper():
    inc = generate_synthetic_incident("memory_leak", seed=77)
    assert "payment-service" in inc.title.lower() or "oom" in inc.title.lower()
    assert len(inc.traces) > 0


def test_benchmark_suite_generation():
    gen = SyntheticIncidentGenerator()
    suite = gen.generate_suite(count=15, start_seed=200)

    assert len(suite) == 15
    # Verify cycling through diverse scenarios
    categories = {cat for _, _, cat in suite}
    assert len(categories) == 5
