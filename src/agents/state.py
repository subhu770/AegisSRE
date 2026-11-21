"""
State definitions for AegisSRE multi-agent workflow DAG.
"""

from typing import Any, Dict, List, Optional, TypedDict


class IncidentState(TypedDict, total=False):
    """
    Mutable state passed across nodes in the multi-agent DAG.
    
    Workflow Sequence:
    START
      ├──> TelemetryAgent (populates telemetry_result)
      └──> GitAgent       (populates git_result)
            │
            ▼
    DiagnosticAgent       (synthesizes telemetry + git + graph -> root_cause_result, blast_radius_result)
            │
            ▼
    RemediationAgent      (generates remediation_result, diagnostic_report)
            │
            ▼
    END
    """
    # Core Incident Metadata
    incident_id: str
    title: str
    description: str
    environment: str
    started_at: str

    # Raw Ingested Telemetry and Version Control Payloads
    metrics: List[Dict[str, Any]]
    traces: List[Dict[str, Any]]
    commits: List[Dict[str, Any]]
    dependency_graph: Dict[str, Any]

    # Agent Step Artifacts
    telemetry_result: Optional[Dict[str, Any]]
    git_result: Optional[Dict[str, Any]]
    root_cause_result: Optional[Dict[str, Any]]
    blast_radius_result: Optional[Dict[str, Any]]
    remediation_result: Optional[Dict[str, Any]]
    diagnostic_report: Optional[Dict[str, Any]]

    # SRE Audit & Execution Trace
    workflow_trace: List[Dict[str, Any]]
    errors: List[str]
