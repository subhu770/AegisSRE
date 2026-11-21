"""
Pydantic schemas for AegisSRE incidents, telemetry, commits, and diagnostic reports.
"""

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class IncidentCategory(str, Enum):
    DATABASE_POOL_EXHAUSTION = "DATABASE_POOL_EXHAUSTION"
    MEMORY_LEAK_OOM = "MEMORY_LEAK_OOM"
    CASCADING_503_CIRCUIT_BREAKER_TRIP = "CASCADING_503_CIRCUIT_BREAKER_TRIP"
    CONFIG_REGRESSION = "CONFIG_REGRESSION"
    CACHE_STAMPEDE = "CACHE_STAMPEDE"
    UNKNOWN = "UNKNOWN"


class MetricAlert(BaseModel):
    """Prometheus-style metric anomaly alert."""
    service: str = Field(..., description="Target microservice name")
    metric_name: str = Field(..., description="Prometheus metric key (e.g. http_requests_5xx_rate)")
    value: float = Field(..., description="Recorded anomalous metric value")
    threshold: float = Field(..., description="Alerting threshold")
    unit: str = Field(default="", description="Unit of measurement (%, ms, bytes, count)")
    severity: AlertSeverity = Field(default=AlertSeverity.CRITICAL)
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class Trace(BaseModel):
    """Distributed tracing span with status, latency, and exception details."""
    trace_id: str
    span_id: str
    parent_span_id: Optional[str] = None
    service: str
    endpoint: str
    status_code: int = Field(default=200)
    latency_ms: float = Field(default=10.0)
    error_message: Optional[str] = None
    stack_trace: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


class GitCommit(BaseModel):
    """Recent git commit potentially introducing regressive changes."""
    commit_hash: str
    author: str
    timestamp: datetime
    message: str
    changed_files: List[str] = Field(default_factory=list)
    diff: str = Field(default="")


class Incident(BaseModel):
    """Encapsulates all distributed system signals during an outage event."""
    incident_id: str
    title: str
    description: str
    started_at: datetime = Field(default_factory=datetime.utcnow)
    metrics: List[MetricAlert] = Field(default_factory=list)
    traces: List[Trace] = Field(default_factory=list)
    commits: List[GitCommit] = Field(default_factory=list)
    environment: str = Field(default="production")
    metadata: Dict[str, Any] = Field(default_factory=dict)


class BlastRadiusReportSchema(BaseModel):
    """Quantified blast radius and impact surface."""
    root_service: str
    impacted_services: List[str]
    total_services: int
    impact_ratio: float
    weighted_blast_radius_score: float
    risk_level: str
    critical_paths: List[List[str]] = Field(default_factory=list)
    tier_breakdown: Dict[str, List[str]] = Field(default_factory=dict)


class TelemetryAnalysisResult(BaseModel):
    """Telemetry Agent synthesis output."""
    anomalous_services: List[str] = Field(default_factory=list)
    epicenter_service: str
    anomaly_confidence: float = Field(ge=0.0, le=1.0)
    primary_metric_spike: Optional[str] = None
    earliest_error_timestamp: Optional[datetime] = None
    error_signatures: List[str] = Field(default_factory=list)
    evidence_summary: str


class GitAnalysisResult(BaseModel):
    """Git Investigator Agent synthesis output."""
    suspicious_commits: List[Dict[str, Any]] = Field(default_factory=list)
    top_suspect_commit: Optional[str] = None
    culprit_file: Optional[str] = None
    culprit_service: Optional[str] = None
    regression_type: Optional[str] = None
    correlation_confidence: float = Field(ge=0.0, le=1.0)
    evidence_summary: str


class RootCauseHypothesis(BaseModel):
    """Root-Cause Analyzer diagnosis hypothesis."""
    root_cause_service: str
    incident_category: IncidentCategory
    confidence_score: float = Field(ge=0.0, le=1.0)
    failure_chain: List[str] = Field(default_factory=list)
    summary: str


class RemediationPlan(BaseModel):
    """Patch Proposer / Remediation Agent actionable post-mortem and mitigation."""
    immediate_mitigation: str
    rollback_command: str
    hotfix_patch: Optional[str] = None
    long_term_prevention: List[str] = Field(default_factory=list)
    post_mortem_markdown: str


class DiagnosticReport(BaseModel):
    """Full end-to-end diagnostic report produced by AegisSRE multi-agent workflow."""
    incident_id: str
    status: str = "RESOLVED"
    root_cause: RootCauseHypothesis
    blast_radius: BlastRadiusReportSchema
    telemetry_analysis: TelemetryAnalysisResult
    git_analysis: GitAnalysisResult
    remediation: RemediationPlan
    duration_ms: float
    workflow_trace: List[Dict[str, Any]] = Field(default_factory=list)


class SimulateIncidentRequest(BaseModel):
    scenario: str = Field(
        default="db_pool_exhaustion",
        description="Scenario type: db_pool_exhaustion, memory_leak, cascading_503, config_regression, cache_stampede",
    )
    seed: int = Field(default=42, description="Random seed for deterministic generation")


class SimulateIncidentResponse(BaseModel):
    incident: Incident
    ground_truth_root_cause: str
    scenario: str


class BlastRadiusRequest(BaseModel):
    service_name: str
