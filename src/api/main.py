"""
FastAPI Application for AegisSRE.

Endpoints:
- POST /diagnose: Ingests an incident and runs multi-agent diagnosis DAG.
- POST /simulate-incident: Generates deterministic synthetic incident signals.
- POST /diagnose/scenario/{scenario_type}: End-to-end simulate and diagnose in a single call.
- GET  /graph/topology: Returns current microservice topology.
- POST /graph/blast-radius: Computes blast radius for a given microservice.
"""

from contextlib import asynccontextmanager
from typing import Any, Dict
from fastapi import FastAPI, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware

from src.api.schemas import (
    BlastRadiusReportSchema,
    BlastRadiusRequest,
    DiagnosticReport,
    Incident,
    SimulateIncidentRequest,
    SimulateIncidentResponse,
)
from src.graph.dependency_graph import DependencyGraph, create_default_topology
from src.simulation.incident_generator import (
    IncidentScenario,
    SyntheticIncidentGenerator,
)
from src.workflow import AegisWorkflow

# Global shared instances
service_graph: DependencyGraph = create_default_topology()
workflow_engine: AegisWorkflow = AegisWorkflow(dependency_graph=service_graph)
incident_generator: SyntheticIncidentGenerator = SyntheticIncidentGenerator()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: ensure service graph and agents are initialized
    global service_graph, workflow_engine, incident_generator
    service_graph = create_default_topology()
    workflow_engine = AegisWorkflow(dependency_graph=service_graph)
    incident_generator = SyntheticIncidentGenerator()
    yield
    # Shutdown logic (if any)


app = FastAPI(
    title="AegisSRE Autonomous Incident Diagnosis Engine",
    description="Multi-agent DAG workflow engine for autonomous root-cause diagnosis in distributed systems.",
    version="1.0.0",
    lifespan=lifespan,
)

# Enable permissive CORS for web dashboards
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/", tags=["Health"])
async def root() -> Dict[str, Any]:
    """Engine metadata and operational status."""
    return {
        "engine": "AegisSRE",
        "version": "1.0.0",
        "status": "OPERATIONAL",
        "mode": "SIMULATION_MODE",
        "description": "Multi-Agent Root-Cause Diagnosis Engine",
    }


@app.get("/health", tags=["Health"])
async def health_check() -> Dict[str, str]:
    """Health check endpoint for Kubernetes liveness/readiness probes."""
    return {"status": "healthy"}


@app.get("/graph/topology", tags=["Dependency Graph"])
async def get_topology() -> Dict[str, Any]:
    """Retrieve the full microservice dependency graph representation."""
    return service_graph.to_dict()


@app.post(
    "/graph/blast-radius",
    response_model=BlastRadiusReportSchema,
    tags=["Dependency Graph"],
)
async def calculate_blast_radius(request: BlastRadiusRequest) -> BlastRadiusReportSchema:
    """Calculate the blast radius and impacted services for a given microservice."""
    if request.service_name not in service_graph.graph.nodes:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Service '{request.service_name}' not found in dependency graph.",
        )
    report = service_graph.calculate_blast_radius(request.service_name)
    return BlastRadiusReportSchema(**report.to_dict())


@app.post(
    "/simulate-incident",
    response_model=SimulateIncidentResponse,
    tags=["Simulation Layer"],
)
async def simulate_incident(req: SimulateIncidentRequest) -> SimulateIncidentResponse:
    """
    Generate deterministic synthetic microservice trace logs, Prometheus metric alerts,
    and Git commit regressions.
    """
    try:
        incident, ground_truth, _ = incident_generator.generate(
            scenario=req.scenario, seed=req.seed
        )
        return SimulateIncidentResponse(
            incident=incident,
            ground_truth_root_cause=ground_truth,
            scenario=req.scenario,
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to generate synthetic incident: {str(e)}",
        )


@app.post("/diagnose", response_model=DiagnosticReport, tags=["Agent Diagnosis"])
async def diagnose_incident(incident: Incident) -> DiagnosticReport:
    """
    Execute the multi-agent StateGraph pipeline on an ingested incident:
    TelemetryAgent -> GitAgent -> DiagnosticAgent -> RemediationAgent.
    """
    try:
        report = await workflow_engine.run(incident)
        return report
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Multi-agent diagnosis failed: {str(e)}",
        )


@app.post(
    "/diagnose/scenario/{scenario_type}",
    response_model=DiagnosticReport,
    tags=["Agent Diagnosis"],
)
async def diagnose_scenario(
    scenario_type: str,
    seed: int = Query(default=42, description="Random seed for simulation"),
) -> DiagnosticReport:
    """
    Convenience endpoint: Simulates an incident and runs the full multi-agent diagnosis pipeline.
    """
    try:
        incident, _, _ = incident_generator.generate(scenario=scenario_type, seed=seed)
        report = await workflow_engine.run(incident)
        return report
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Failed to diagnose scenario '{scenario_type}': {str(e)}",
        )
