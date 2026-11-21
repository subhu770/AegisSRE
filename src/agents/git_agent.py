"""
Git Investigator Agent for analyzing commit diffs and code regressions.
"""

from datetime import datetime
import re
from typing import Any, Dict, List, Optional, Tuple

from src.agents.state import IncidentState
from src.api.schemas import GitAnalysisResult


class GitAgent:
    """
    Analyzes recent git commits, file paths, and unified diffs.
    Detects risky configuration changes, resource leaks, connection pool tweaks,
    and timeout alterations that correlate with outage onset.
    """

    # Heuristic signature patterns for common SRE regressions
    PATTERNS: Dict[str, List[re.Pattern]] = {
        "DATABASE_POOL_EXHAUSTION": [
            re.compile(r"(max[-_]?pool[-_]?size|maximum-pool-size|max_connections|pool_timeout)[\s:=]+(\d+)", re.I),
            re.compile(r"(\+.*(pool|datasource|hikari).*(size|min|max|timeout))", re.I),
        ],
        "MEMORY_LEAK_OOM": [
            re.compile(r"(\+.*(append|push|put)\(.*\))", re.I),
            re.compile(r"(\+.*(_cache|_buffer|_queue|static|global).*(list|dict|map|array))", re.I),
            re.compile(r"(\+.*(unbounded|no.*ttl|no.*evict))", re.I),
        ],
        "CASCADING_503_CIRCUIT_BREAKER_TRIP": [
            re.compile(r"(\+.*(jwks|remote|http\.get|fetch).*(verify|token|auth))", re.I),
            re.compile(r"(\+.*(without.*cache|force.*refresh|on.*every.*call))", re.I),
            re.compile(r"(\+.*(timeout|deadline).*(=|:)\s*\d+)", re.I),
        ],
        "CONFIG_REGRESSION": [
            re.compile(r"(\+.*(DB_PORT|PORT|HOST|URL|ENDPOINT)[\s:=]+.*)", re.I),
            re.compile(r"(\+.*(localhost|127\.0\.0\.1|5433|invalid))", re.I),
        ],
        "CACHE_STAMPEDE": [
            re.compile(r"(\+.*(CACHE_EXPIRATION|TTL|cache_timeout)[\s:=]+0)", re.I),
            re.compile(r"(\+.*(bypass.*cache|skip.*cache|disable.*cache))", re.I),
        ],
    }

    def __init__(self) -> None:
        pass

    def _infer_service_from_files(self, changed_files: List[str]) -> Optional[str]:
        """Infer target microservice name from file path conventions."""
        for path in changed_files:
            # Pattern: services/<service-name>/... or k8s/<service-name>/...
            match = re.search(r"(?:services|k8s|apps|deploy)/([a-zA-Z0-9_-]+)/", path)
            if match:
                return match.group(1)
            # Direct service name in filename
            for candidate in [
                "order-service",
                "payment-service",
                "auth-service",
                "inventory-service",
                "catalog-service",
                "edge-gateway",
                "notification-service",
            ]:
                if candidate in path:
                    return candidate
        return None

    def _score_commit(
        self, commit: Dict[str, Any], incident_start: Optional[datetime] = None
    ) -> Tuple[float, Optional[str], List[str]]:
        diff = commit.get("diff", "")
        msg = commit.get("message", "")
        full_text = f"{msg}\n{diff}"

        score = 0.10
        matched_categories: List[str] = []
        flags: List[str] = []

        for category, patterns in self.PATTERNS.items():
            for p in patterns:
                m = p.search(full_text)
                if m:
                    score += 0.35
                    matched_categories.append(category)
                    flags.append(f"Matched pattern '{p.pattern[:35]}...'")

        # Cap base score from patterns
        score = min(score, 0.85)

        # Temporal proximity bonus
        ts_val = commit.get("timestamp")
        commit_dt = None
        if isinstance(ts_val, str):
            try:
                commit_dt = datetime.fromisoformat(ts_val.replace("Z", "+00:00"))
            except Exception:
                pass
        elif isinstance(ts_val, datetime):
            commit_dt = ts_val

        if commit_dt and incident_start:
            delta = abs((incident_start - commit_dt).total_seconds())
            if delta < 1800:  # within 30 mins
                score += 0.15
            elif delta < 3600:  # within 1 hour
                score += 0.08

        primary_category = matched_categories[0] if matched_categories else None
        return min(round(score, 3), 0.99), primary_category, flags

    async def run(self, state: IncidentState) -> Dict[str, Any]:
        """
        Execute git commit regression analysis.
        """
        commits = state.get("commits", [])
        if not commits:
            return GitAnalysisResult(
                suspicious_commits=[],
                top_suspect_commit=None,
                culprit_file=None,
                culprit_service=None,
                regression_type=None,
                correlation_confidence=0.0,
                evidence_summary="No recent git commits provided for regression inspection.",
            ).model_dump()

        scored_commits = []
        for c in commits:
            score, regression_type, flags = self._score_commit(c)
            changed_files = c.get("changed_files", [])
            inferred_service = self._infer_service_from_files(changed_files)
            culprit_file = changed_files[0] if changed_files else None

            scored_commits.append({
                "commit_hash": c.get("commit_hash"),
                "author": c.get("author"),
                "message": c.get("message"),
                "score": score,
                "regression_type": regression_type,
                "inferred_service": inferred_service,
                "culprit_file": culprit_file,
                "flags": flags,
            })

        scored_commits.sort(key=lambda x: x["score"], reverse=True)
        top = scored_commits[0]

        evidence = (
            f"Commit {top['commit_hash']} by {top['author']} is top regression suspect "
            f"(confidence={top['score']:.2f}). Message: '{top['message']}'. "
            f"Modified: {top['culprit_file'] or 'unknown'}. Regression type: {top['regression_type']}."
        )

        result = GitAnalysisResult(
            suspicious_commits=scored_commits,
            top_suspect_commit=top["commit_hash"],
            culprit_file=top["culprit_file"],
            culprit_service=top["inferred_service"],
            regression_type=top["regression_type"],
            correlation_confidence=top["score"],
            evidence_summary=evidence,
        )
        return result.model_dump()
