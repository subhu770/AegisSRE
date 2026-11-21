"""
Multi-Agent DAG Workflow Orchestrator for AegisSRE.

Orchestrates the StateGraph execution pipeline:
[START]
   ├──> TelemetryAgent   (Parses metric spikes and anomalous log traces)
   └──> GitAgent         (Analyzes recent commit diffs for config/code regressions)
         │
         ▼
DiagnosticAgent          (Synthesizes graph traversal + logs to identify root cause)
         │
         ▼
RemediationAgent         (Generates actionable markdown post-mortem & rollback/patch command)
         │
         ▼
   [END / DiagnosticReport]
"""

import asyncio
from datetime import datetime
import time
from typing import Any, Dict, List, Optional

from src.agents.diagnostic_agent import DiagnosticAgent
from src.agents.git_agent import GitAgent
from src.agents.remediation_agent import RemediationAgent
from src.agents.state import IncidentState
from src.agents.telemetry_agent import TelemetryAgent
from src.api.schemas import (
    BlastRadiusReportSchema,
    DiagnosticReport,
    GitAnalysisResult,
    Incident,
    IncidentCategory,
    RemediationPlan,
    RootCauseHypothesis,
    TelemetryAnalysisResult,
)
from src.graph.dependency_graph import DependencyGraph, create_default_topology


class AegisWorkflow:
    """
    StateGraph / Multi-Agent DAG workflow orchestrator for autonomous incident root-cause diagnosis.
    Executes in SIMULATION_MODE with 100% deterministic runs and zero external API dependencies.
    """

    def __init__(self, dependency_graph: Optional[DependencyGraph] = None) -> None:
        self.dependency_graph = dependency_graph or create_default_topology()
        self.telemetry_agent = TelemetryAgent()
        self.git_agent = GitAgent()
        self.diagnostic_agent = DiagnosticAgent()
        self.remediation_agent = RemediationAgent()

    async def run(self, incident: Incident) -> DiagnosticReport:
        """
        Execute the full multi-agent diagnostic DAG.
        """
        start_time = time.perf_counter()

        # Initialize State
        state: IncidentState = {
            "incident_id": incident.incident_id,
            "title": incident.title,
            "description": incident.description,
            "environment": incident.environment,
            "started_at": incident.started_at.isoformat(),
            "metrics": [m.model_dump() for m in incident.metrics],
            "traces": [t.model_dump() for t in incident.traces],
            "commits": [c.model_dump() for c in incident.commits],
            "dependency_graph": self.dependency_graph.to_dict(),
            "telemetry_result": None,
            "git_result": None,
            "root_cause_result": None,
            "blast_radius_result": None,
            "remediation_result": None,
            "diagnostic_report": None,
            "workflow_trace": [],
            "errors": [],
        }

        # -------------------------------------------------------------
        # Phase 1: Parallel Ingestion (Telemetry Agent + Git Agent)
        # -------------------------------------------------------------
        t0_p1 = time.perf_counter()
        telemetry_task = asyncio.create_task(self._safe_run_telemetry(state))
        git_task = asyncio.create_task(self._safe_run_git(state))

        telemetry_res, git_res = await asyncio.gather(telemetry_task, git_task)
        state["telemetry_result"] = telemetry_res
        state["git_result"] = git_res

        duration_p1_ms = round((time.perf_counter() - t0_p1) * 1000, 2)
        state["workflow_trace"].append({
            "step": "Phase1_Telemetry_And_Git_Analysis",
            "agents": ["TelemetryAgent", "GitAgent"],
            "status": "COMPLETED",
            "duration_ms": duration_p1_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # -------------------------------------------------------------
        # Phase 2: Diagnostic Synthesis (Diagnostic Agent)
        # -------------------------------------------------------------
        t0_p2 = time.perf_counter()
        try:
            diag_output = await self.diagnostic_agent.run(state)
            state["root_cause_result"] = diag_output.get("root_cause")
            state["blast_radius_result"] = diag_output.get("blast_radius")
            diag_status = "COMPLETED"
        except Exception as e:
            diag_status = "FAILED"
            state["errors"].append(f"DiagnosticAgent error: {str(e)}")
            state["root_cause_result"] = {
                "root_cause_service": "unknown",
                "incident_category": IncidentCategory.UNKNOWN.value,
                "confidence_score": 0.1,
                "failure_chain": [f"Analysis failed: {str(e)}"],
                "summary": "Root cause identification failed.",
            }
            state["blast_radius_result"] = {
                "root_service": "unknown",
                "impacted_services": [],
                "total_services": 0,
                "impact_ratio": 0.0,
                "weighted_blast_radius_score": 0.0,
                "risk_level": "LOW",
                "critical_paths": [],
                "tier_breakdown": {},
            }

        duration_p2_ms = round((time.perf_counter() - t0_p2) * 1000, 2)
        state["workflow_trace"].append({
            "step": "Phase2_RootCause_Diagnosis",
            "agents": ["DiagnosticAgent"],
            "status": diag_status,
            "duration_ms": duration_p2_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # -------------------------------------------------------------
        # Phase 3: Remediation & Post-Mortem (Remediation Agent)
        # -------------------------------------------------------------
        t0_p3 = time.perf_counter()
        try:
            remediation_res = await self.remediation_agent.run(state)
            state["remediation_result"] = remediation_res
            rem_status = "COMPLETED"
        except Exception as e:
            rem_status = "FAILED"
            state["errors"].append(f"RemediationAgent error: {str(e)}")
            state["remediation_result"] = {
                "immediate_mitigation": "Manual intervention required.",
                "rollback_command": "# Check git log and deployment status",
                "hotfix_patch": None,
                "long_term_prevention": [],
                "post_mortem_markdown": f"# Incident Analysis Failed\nError: {str(e)}",
            }

        duration_p3_ms = round((time.perf_counter() - t0_p3) * 1000, 2)
        state["workflow_trace"].append({
            "step": "Phase3_Remediation_Generation",
            "agents": ["RemediationAgent"],
            "status": rem_status,
            "duration_ms": duration_p3_ms,
            "timestamp": datetime.utcnow().isoformat(),
        })

        # -------------------------------------------------------------
        # Phase 4: Assembly into DiagnosticReport
        # -------------------------------------------------------------
        total_duration_ms = round((time.perf_counter() - start_time) * 1000, 2)

        report = DiagnosticReport(
            incident_id=incident.incident_id,
            status="RESOLVED" if not state["errors"] else "DEGRADED",
            root_cause=RootCauseHypothesis(**state["root_cause_result"]),
            blast_radius=BlastRadiusReportSchema(**state["blast_radius_result"]),
            telemetry_analysis=TelemetryAnalysisResult(**state["telemetry_result"]),
            git_analysis=GitAnalysisResult(**state["git_result"]),
            remediation=RemediationPlan(**state["remediation_result"]),
            duration_ms=total_duration_ms,
            workflow_trace=state["workflow_trace"],
        )

        state["diagnostic_report"] = report.model_dump()
        return report

    async def _safe_run_telemetry(self, state: IncidentState) -> Dict[str, Any]:
        try:
            return await self.telemetry_agent.run(state)
        except Exception as e:
            state.setdefault("errors", []).append(f"TelemetryAgent error: {str(e)}")
            return {
                "anomalous_services": [],
                "epicenter_service": "unknown",
                "anomaly_confidence": 0.0,
                "primary_metric_spike": None,
                "earliest_error_timestamp": None,
                "error_signatures": [],
                "evidence_summary": f"Telemetry processing error: {str(e)}",
            }

    async def _safe_run_git(self, state: IncidentState) -> Dict[str, Any]:
        try:
            return await self.git_agent.run(state)
        except Exception as e:
            state.setdefault("errors", []).append(f"GitAgent error: {str(e)}")
            return {
                "suspicious_commits": [],
                "top_suspect_commit": None,
                "culprit_file": None,
                "culprit_service": None,
                "regression_type": None,
                "correlation_confidence": 0.0,
                "evidence_summary": f"Git processing error: {str(e)}",
            }
