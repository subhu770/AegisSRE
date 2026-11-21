"""
Remediation Agent for generating actionable markdown post-mortems and rollback/patch commands.
"""

from datetime import datetime
from typing import Any, Dict, List

from src.agents.state import IncidentState
from src.api.schemas import RemediationPlan


class RemediationAgent:
    """
    Synthesizes the diagnostic hypothesis and git correlation into actionable
    production remediation commands, rollback scripts, and SRE post-mortem markdown.
    """

    def __init__(self) -> None:
        pass

    def _generate_rollback_commands(
        self,
        service: str,
        commit_hash: str | None,
    ) -> str:
        """Generate precise CLI commands to revert the regressive change."""
        lines = []
        if commit_hash:
            lines.append(f"# 1. Git revert the suspect commit on main")
            lines.append(f"git fetch origin && git checkout main")
            lines.append(f"git revert --no-edit {commit_hash}")
            lines.append(f"git push origin main\n")
            lines.append(f"# 2. Fast-track emergency rollout deployment")
            lines.append(f"kubectl rollout restart deployment/{service} -n production")
        else:
            lines.append(f"# Emergency rollback to previous stable ReplicaSet")
            lines.append(f"kubectl rollout undo deployment/{service} -n production")
            lines.append(f"kubectl rollout status deployment/{service} -n production --timeout=120s")
        return "\n".join(lines)

    def _generate_hotfix(
        self,
        category: str,
        service: str,
    ) -> str:
        """Generate sample hotfix configuration snippet."""
        if category == "DATABASE_POOL_EXHAUSTION":
            return (
                f"# Hotfix for {service} datasource configuration:\n"
                "datasource:\n"
                "  maximum-pool-size: 100  # Restored from 5\n"
                "  connection-timeout: 30000\n"
                "  leak-detection-threshold: 2000\n"
            )
        elif category == "MEMORY_LEAK_OOM":
            return (
                f"# Hotfix for {service} memory leak buffer:\n"
                "from cachetools import TTLCache\n"
                "_AUDIT_CACHE = TTLCache(maxsize=10000, ttl=300) # Enforce bounded TTL eviction\n"
            )
        elif category == "CASCADING_503_CIRCUIT_BREAKER_TRIP":
            return (
                f"# Hotfix for {service} auth caching:\n"
                "resilience4j.circuitbreaker:\n"
                "  instances:\n"
                "    auth-service:\n"
                "      failure-rate-threshold: 50\n"
                "      wait-duration-in-open-state: 10s\n"
                "// Cache remote JWKS keys with 24h TTL instead of per-request remote fetch\n"
            )
        elif category == "CONFIG_REGRESSION":
            return (
                f"# Hotfix for {service} environment port:\n"
                "env:\n"
                "  - name: DB_PORT\n"
                "    value: '5432' # Restored correct PostgreSQL port\n"
            )
        elif category == "CACHE_STAMPEDE":
            return (
                f"# Hotfix for {service} caching policy:\n"
                "CACHE_EXPIRATION_SECONDS = 3600 # Restored 1 hour TTL with random jitter\n"
                "CACHE_JITTER_SECONDS = 300\n"
            )
        return f"# Verify configuration for {service}"

    def _generate_preventative_actions(self, category: str) -> List[str]:
        base_actions = [
            "Add automated canary deployment analysis with automated rollback on 5xx elevation.",
            "Establish automated alerting on p99 latency threshold deviations > 20%.",
        ]
        if category == "DATABASE_POOL_EXHAUSTION":
            return [
                "Implement HikariCP connection pool saturation alerting at 80% utilization.",
                "Enforce mandatory load test in CI/CD pipeline prior to pool configuration adjustments.",
                "Deploy PgBouncer / RDS Proxy connection pooling layer.",
            ] + base_actions
        elif category == "MEMORY_LEAK_OOM":
            return [
                "Add static analysis rule forbidding unbounded global collections / maps in service codebase.",
                "Configure cgroup memory high-watermark alert at 80% before OOMKiller triggers.",
                "Add automated soak test in staging running 24h heap profiling.",
            ] + base_actions
        elif category == "CASCADING_503_CIRCUIT_BREAKER_TRIP":
            return [
                "Mandate circuit breaker and fallback policies for all synchronous inter-service RPC calls.",
                "Enforce local in-memory caching for cryptographic key validation endpoints (JWKS).",
                "Audit gRPC / HTTP client timeout configurations across all microservices.",
            ] + base_actions
        elif category == "CONFIG_REGRESSION":
            return [
                "Implement strict schema validation for Kubernetes Helm / Kustomize values files.",
                "Add pre-flight healthcheck probe verifying TCP port connectivity during deployment.",
            ] + base_actions
        elif category == "CACHE_STAMPEDE":
            return [
                "Implement single-flight / mutex request coalescing pattern for cache misses.",
                "Add randomized jitter to cache TTLs to avoid simultaneous expiration waves.",
            ] + base_actions
        return base_actions

    def _generate_post_mortem(
        self,
        state: IncidentState,
        root_cause: Dict[str, Any],
        blast_radius: Dict[str, Any],
        rollback_cmd: str,
        preventative_actions: List[str],
    ) -> str:
        """Generate production-grade markdown SRE post-mortem."""
        inc_id = state.get("incident_id", "INC-UNKNOWN")
        title = state.get("title", "Distributed System Outage")
        srv = root_cause.get("root_cause_service", "unknown")
        cat = root_cause.get("incident_category", "UNKNOWN")
        confidence = float(root_cause.get("confidence_score", 0.0)) * 100
        impacted_srvs = ", ".join(blast_radius.get("impacted_services", []))
        risk = blast_radius.get("risk_level", "HIGH")
        failure_chain = "\n".join([f"{i+1}. {step}" for i, step in enumerate(root_cause.get("failure_chain", []))])
        action_items = "\n".join([f"- [ ] {action}" for action in preventative_actions])

        return f"""# SRE Incident Post-Mortem: {inc_id}

## Executive Summary
- **Incident Title**: {title}
- **Root Cause Microservice**: `{srv}`
- **Incident Category**: `{cat}`
- **Diagnosis Confidence**: {confidence:.1f}%
- **Blast Radius Severity**: **{risk}** (Affected Services: {impacted_srvs})
- **Engine**: AegisSRE Autonomous Diagnosis Pipeline

---

## Failure Propagation Chain
{failure_chain}

---

## Blast Radius & Impact Assessment
- **Total Services In Architecture**: {blast_radius.get('total_services')}
- **Impact Ratio**: {blast_radius.get('impact_ratio', 0) * 100:.1f}% of total architecture
- **Weighted Blast Score**: {blast_radius.get('weighted_blast_radius_score', 0):.2f}
- **Tier 0 Services Impacted**: {', '.join(blast_radius.get('tier_breakdown', {}).get('TIER_0', [])) or 'None'}

---

## Immediate Remediation & Rollback Commands
Execute the following commands in the operational environment:

```bash
{rollback_cmd}
```

---

## Action Items & Preventative SRE Recommendations
{action_items}

---
*Report generated autonomously by AegisSRE at {datetime.utcnow().isoformat()}Z.*
"""

    async def run(self, state: IncidentState) -> Dict[str, Any]:
        """Execute remediation plan generation."""
        root_cause = state.get("root_cause_result") or {}
        blast_radius = state.get("blast_radius_result") or {}
        git = state.get("git_result") or {}

        service = root_cause.get("root_cause_service", "unknown")
        category = root_cause.get("incident_category", "UNKNOWN")
        top_commit = git.get("top_suspect_commit")

        rollback_cmd = self._generate_rollback_commands(service, top_commit)
        hotfix = self._generate_hotfix(category, service)
        preventative_actions = self._generate_preventative_actions(category)

        post_mortem = self._generate_post_mortem(
            state, root_cause, blast_radius, rollback_cmd, preventative_actions
        )

        plan = RemediationPlan(
            immediate_mitigation=f"Revert commit '{top_commit}' and rollout restart deployment/{service}.",
            rollback_command=rollback_cmd,
            hotfix_patch=hotfix,
            long_term_prevention=preventative_actions,
            post_mortem_markdown=post_mortem,
        )
        return plan.model_dump()
