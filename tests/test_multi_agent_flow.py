"""
End-to-End Multi-Agent DAG Workflow and API Integration Tests.
"""

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.api.schemas import IncidentCategory
from src.graph.dependency_graph import create_default_topology
from src.simulation.incident_generator import (
    IncidentScenario,
    SyntheticIncidentGenerator,
)
from src.workflow import AegisWorkflow

client = TestClient(app)


@pytest.mark.asyncio
async def test_workflow_db_pool_exhaustion():
    gen = SyntheticIncidentGenerator()
    incident, ground_truth_root, ground_truth_cat = gen.generate(
        scenario=IncidentScenario.DB_POOL_EXHAUSTION, seed=42
    )

    workflow = AegisWorkflow(dependency_graph=create_default_topology())
    report = await workflow.run(incident)

    # Validate Diagnosis
    assert report.incident_id == incident.incident_id
    assert report.status == "RESOLVED"
    assert report.root_cause.root_cause_service == ground_truth_root
    assert report.root_cause.incident_category == ground_truth_cat
    assert report.root_cause.confidence_score >= 0.70

    # Validate Blast Radius
    assert "order-service" in report.blast_radius.impacted_services
    assert "edge-gateway" in report.blast_radius.impacted_services
    assert report.blast_radius.risk_level in ["CRITICAL", "HIGH"]

    # Validate Remediation
    assert "revert" in report.remediation.rollback_command.lower()
    assert len(report.remediation.long_term_prevention) >= 2
    assert "SRE Incident Post-Mortem" in report.remediation.post_mortem_markdown

    # Validate Workflow Trace Audit Log
    steps = [step["step"] for step in report.workflow_trace]
    assert "Phase1_Telemetry_And_Git_Analysis" in steps
    assert "Phase2_RootCause_Diagnosis" in steps
    assert "Phase3_Remediation_Generation" in steps


@pytest.mark.asyncio
async def test_workflow_memory_leak():
    gen = SyntheticIncidentGenerator()
    incident, ground_truth_root, ground_truth_cat = gen.generate(
        scenario=IncidentScenario.MEMORY_LEAK, seed=55
    )

    workflow = AegisWorkflow()
    report = await workflow.run(incident)

    assert report.root_cause.root_cause_service == ground_truth_root
    assert report.root_cause.incident_category == ground_truth_cat
    assert "payment-service" in report.blast_radius.impacted_services


@pytest.mark.asyncio
async def test_workflow_cascading_503():
    gen = SyntheticIncidentGenerator()
    incident, ground_truth_root, ground_truth_cat = gen.generate(
        scenario=IncidentScenario.CASCADING_503, seed=88
    )

    workflow = AegisWorkflow()
    report = await workflow.run(incident)

    assert report.root_cause.root_cause_service == ground_truth_root
    assert report.root_cause.incident_category == ground_truth_cat
    assert "auth-service" in report.blast_radius.impacted_services


@pytest.mark.asyncio
async def test_workflow_config_regression():
    gen = SyntheticIncidentGenerator()
    incident, ground_truth_root, ground_truth_cat = gen.generate(
        scenario=IncidentScenario.CONFIG_REGRESSION, seed=12
    )

    workflow = AegisWorkflow()
    report = await workflow.run(incident)

    assert report.root_cause.root_cause_service == ground_truth_root
    assert report.root_cause.incident_category == ground_truth_cat


@pytest.mark.asyncio
async def test_workflow_cache_stampede():
    gen = SyntheticIncidentGenerator()
    incident, ground_truth_root, ground_truth_cat = gen.generate(
        scenario=IncidentScenario.CACHE_STAMPEDE, seed=33
    )

    workflow = AegisWorkflow()
    report = await workflow.run(incident)

    assert report.root_cause.root_cause_service == ground_truth_root
    assert report.root_cause.incident_category == ground_truth_cat


def test_api_health_and_root():
    res_root = client.get("/")
    assert res_root.status_code == 200
    assert res_root.json()["engine"] == "AegisSRE"

    res_health = client.get("/health")
    assert res_health.status_code == 200
    assert res_health.json()["status"] == "healthy"


def test_api_graph_endpoints():
    res_topo = client.get("/graph/topology")
    assert res_topo.status_code == 200
    data = res_topo.json()
    assert "nodes" in data
    assert "edges" in data

    res_blast = client.post("/graph/blast-radius", json={"service_name": "postgres-orders"})
    assert res_blast.status_code == 200
    blast_data = res_blast.json()
    assert blast_data["root_service"] == "postgres-orders"
    assert "order-service" in blast_data["impacted_services"]

    # Not found case
    res_not_found = client.post("/graph/blast-radius", json={"service_name": "ghost-service"})
    assert res_not_found.status_code == 404


def test_api_simulate_incident():
    res = client.post(
        "/simulate-incident",
        json={"scenario": "db_pool_exhaustion", "seed": 42},
    )
    assert res.status_code == 200
    data = res.json()
    assert data["ground_truth_root_cause"] == "order-service"
    assert "incident" in data
    assert len(data["incident"]["metrics"]) > 0


def test_api_diagnose_scenario_endpoint():
    res = client.post("/diagnose/scenario/memory_leak?seed=55")
    assert res.status_code == 200
    data = res.json()
    assert data["root_cause"]["root_cause_service"] == "payment-service"
    assert data["root_cause"]["incident_category"] == IncidentCategory.MEMORY_LEAK_OOM.value
    assert data["status"] == "RESOLVED"
    assert "remediation" in data
