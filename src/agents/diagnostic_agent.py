"""
Diagnostic Agent for synthesizing graph topology, telemetry, and git regressions.
"""

from typing import Any, Dict, List, Optional

from src.agents.state import IncidentState
from src.api.schemas import (
    BlastRadiusReportSchema,
    IncidentCategory,
    RootCauseHypothesis,
)
from src.graph.dependency_graph import DependencyGraph, create_default_topology


class DiagnosticAgent:
    """
    Synthesizes service dependency graph topology, telemetry failure epicenter,
    and git commit regressions to pinpoint the exact root cause microservice.
    Disambiguates symptom ingress services (e.g. edge-gateway 503s) from actual failure origins.
    """

    def __init__(self) -> None:
        pass

    def _infer_category(
        self,
        git_regression_type: Optional[str],
        telemetry_result: Dict[str, Any],
    ) -> IncidentCategory:
        """Disambiguate incident category using git diffs and telemetry signatures."""
        if git_regression_type:
            try:
                return IncidentCategory(git_regression_type)
            except ValueError:
                pass

        signatures = " ".join(telemetry_result.get("error_signatures", [])).lower()
        primary_metric = (telemetry_result.get("primary_metric_spike") or "").lower()
        combined = f"{signatures} {primary_metric}"

        if "hikaripool" in combined or "connectiontimeout" in combined or "db_pool" in combined:
            return IncidentCategory.DATABASE_POOL_EXHAUSTION
        elif "oom" in combined or "memory" in combined or "sigkill" in combined:
            return IncidentCategory.MEMORY_LEAK_OOM
        elif "circuitbreaker" in combined or "circuit_breaker" in combined or "jwks" in combined:
            return IncidentCategory.CASCADING_503_CIRCUIT_BREAKER_TRIP
        elif "econnrefused" in combined or "port" in combined or "connection refused" in combined:
            return IncidentCategory.CONFIG_REGRESSION
        elif "cache" in combined or "stampede" in combined:
            return IncidentCategory.CACHE_STAMPEDE

        return IncidentCategory.UNKNOWN

    def _construct_failure_chain(
        self,
        root_service: str,
        category: IncidentCategory,
        git_result: Dict[str, Any],
        telemetry_result: Dict[str, Any],
        dep_graph: DependencyGraph,
    ) -> List[str]:
        """Construct a step-by-step causal chain showing how the outage propagated."""
        chain: List[str] = []

        # Step 1: Trigger / Git
        top_commit = git_result.get("top_suspect_commit")
        culprit_file = git_result.get("culprit_file")
        if top_commit:
            chain.append(
                f"Regression introduced in commit {top_commit} affecting {culprit_file or root_service}"
            )
        else:
            chain.append(f"Anomalous event originated in service '{root_service}'")

        # Step 2: Internal failure mode
        if category == IncidentCategory.DATABASE_POOL_EXHAUSTION:
            chain.append(f"Connection pool for '{root_service}' reached 100% capacity; incoming requests queued")
            chain.append(f"Threads timed out waiting for DB connection; internal 500 / 504 errors triggered")
        elif category == IncidentCategory.MEMORY_LEAK_OOM:
            chain.append(f"Memory accumulation in '{root_service}' exceeded container cgroup limit (1024MiB)")
            chain.append(f"Linux kernel OOMKiller sent SIGKILL; pod entered CrashLoopBackOff")
        elif category == IncidentCategory.CASCADING_503_CIRCUIT_BREAKER_TRIP:
            chain.append(f"High latency in '{root_service}' RPC calls caused client timeout accumulation")
            chain.append(f"Upstream circuit breaker tripped OPEN; inbound traffic fast-failed with HTTP 503")
        elif category == IncidentCategory.CONFIG_REGRESSION:
            chain.append(f"Misconfigured connection endpoint / port in '{root_service}' deployment")
            chain.append(f"Socket connection refused (ECONNREFUSED) during initialization")
        elif category == IncidentCategory.CACHE_STAMPEDE:
            chain.append(f"Cache TTL set to 0 in '{root_service}', invalidating all read cache entries")
            chain.append(f"Thundering herd queries dogpiled backend database, saturating connections")
        else:
            chain.append(f"Service '{root_service}' experienced severe error rate spike")

        # Step 3: Upstream propagation along graph
        callers = dep_graph.get_direct_callers(root_service)
        if callers:
            caller_names = ", ".join(callers[:2])
            chain.append(f"Cascading failure propagated upstream to caller(s): {caller_names}")

        return chain

    async def run(self, state: IncidentState) -> Dict[str, Any]:
        """
        Synthesize graph topology, telemetry, and git signals to produce RootCauseHypothesis.
        """
        telemetry = state.get("telemetry_result") or {}
        git = state.get("git_result") or {}

        # Reconstruct Dependency Graph
        raw_graph = state.get("dependency_graph")
        if raw_graph and "nodes" in raw_graph and "edges" in raw_graph:
            dep_graph = DependencyGraph.from_dict(raw_graph)
        else:
            dep_graph = create_default_topology()

        epicenter = telemetry.get("epicenter_service", "unknown")
        culprit_service = git.get("culprit_service")

        # Disambiguate root cause candidate
        # If git specifically pinpointed a service that is in graph, strongly consider it
        # If epicenter is 'edge-gateway' (symptom proxy) but callers/callees show a deeper service failing, pick the deeper service
        root_service = epicenter
        if culprit_service and culprit_service in dep_graph.graph.nodes:
            # If epicenter is edge-gateway or a caller of culprit_service, the culprit service is true root
            if root_service == "edge-gateway" or culprit_service == root_service or dep_graph.graph.has_edge(root_service, culprit_service):
                root_service = culprit_service
            elif culprit_service in dep_graph.get_impacted_services(root_service) or root_service in dep_graph.get_impacted_services(culprit_service):
                root_service = culprit_service

        # If epicenter was a database node (e.g. postgres-orders) but git regression touched the calling service (e.g. order-service)
        if "postgres" in root_service and culprit_service and not culprit_service.startswith("postgres"):
            root_service = culprit_service

        # Calculate Blast Radius for the identified root cause
        blast_report = dep_graph.calculate_blast_radius(root_service)
        blast_schema = BlastRadiusReportSchema(
            root_service=blast_report.root_service,
            impacted_services=blast_report.impacted_services,
            total_services=blast_report.total_services,
            impact_ratio=blast_report.impact_ratio,
            weighted_blast_radius_score=blast_report.weighted_blast_radius_score,
            risk_level=blast_report.risk_level,
            critical_paths=blast_report.critical_paths,
            tier_breakdown=blast_report.tier_breakdown,
        )

        # Categorize incident
        category = self._infer_category(git.get("regression_type"), telemetry)

        # Confidence calculation
        tel_conf = float(telemetry.get("anomaly_confidence", 0.5))
        git_conf = float(git.get("correlation_confidence", 0.5))
        combined_confidence = min(round((tel_conf * 0.45) + (git_conf * 0.50) + 0.05, 2), 0.99)

        # Construct causal failure chain
        failure_chain = self._construct_failure_chain(
            root_service, category, git, telemetry, dep_graph
        )

        summary = (
            f"Diagnosed root cause service: '{root_service}' (Incident Category: {category.value}). "
            f"Failure initiated by regressive code/config change, propagating upstream to impact "
            f"{len(blast_schema.impacted_services)} services with {blast_schema.risk_level} risk."
        )

        hypothesis = RootCauseHypothesis(
            root_cause_service=root_service,
            incident_category=category,
            confidence_score=combined_confidence,
            failure_chain=failure_chain,
            summary=summary,
        )

        return {
            "root_cause": hypothesis.model_dump(),
            "blast_radius": blast_schema.model_dump(),
        }
