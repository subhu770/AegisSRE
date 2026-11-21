"""
Synthetic Incident Generator for Distributed Cloud Architectures.

Provides 100% deterministic synthetic incident generation for:
- Database Pool Exhaustion
- Memory Leak & Pod OOMKilled
- Cascading 503 & Circuit Breaker Trip
- Configuration / Port Regression
- Cache Stampede & Database Dogpiling

Runs in SIMULATION_MODE without any external telemetry or LLM dependencies.
"""

from datetime import datetime, timedelta
from enum import Enum
import hashlib
import random
from typing import Any, Dict, List, Optional, Tuple

from src.api.schemas import (
    AlertSeverity,
    GitCommit,
    Incident,
    IncidentCategory,
    MetricAlert,
    Trace,
)


class IncidentScenario(str, Enum):
    DB_POOL_EXHAUSTION = "db_pool_exhaustion"
    MEMORY_LEAK = "memory_leak"
    CASCADING_503 = "cascading_503"
    CONFIG_REGRESSION = "config_regression"
    CACHE_STAMPEDE = "cache_stampede"


class SyntheticIncidentGenerator:
    """
    Deterministic generation of multi-signal incident payloads.
    Guarantees that identical seed + scenario produces identical incident structures.
    """

    def __init__(self, base_time: Optional[datetime] = None) -> None:
        self.base_time = base_time or datetime(2026, 11, 20, 14, 30, 0)

    def _hash_seed(self, seed: int, suffix: str) -> int:
        h = hashlib.sha256(f"{seed}_{suffix}".encode()).hexdigest()
        return int(h[:8], 16)

    def generate(
        self,
        scenario: IncidentScenario | str = IncidentScenario.DB_POOL_EXHAUSTION,
        seed: int = 42,
    ) -> Tuple[Incident, str, IncidentCategory]:
        """
        Generate a complete synthetic incident.
        Returns: (Incident, ground_truth_root_cause_service, ground_truth_category)
        """
        if isinstance(scenario, str):
            try:
                scenario = IncidentScenario(scenario.lower())
            except ValueError:
                scenario = IncidentScenario.DB_POOL_EXHAUSTION

        rng = random.Random(seed)

        if scenario == IncidentScenario.DB_POOL_EXHAUSTION:
            return self._gen_db_pool_exhaustion(seed, rng)
        elif scenario == IncidentScenario.MEMORY_LEAK:
            return self._gen_memory_leak(seed, rng)
        elif scenario == IncidentScenario.CASCADING_503:
            return self._gen_cascading_503(seed, rng)
        elif scenario == IncidentScenario.CONFIG_REGRESSION:
            return self._gen_config_regression(seed, rng)
        elif scenario == IncidentScenario.CACHE_STAMPEDE:
            return self._gen_cache_stampede(seed, rng)
        else:
            return self._gen_db_pool_exhaustion(seed, rng)

    def _gen_db_pool_exhaustion(
        self, seed: int, rng: random.Random
    ) -> Tuple[Incident, str, IncidentCategory]:
        t0 = self.base_time + timedelta(minutes=seed % 60)
        commit_hash = hashlib.sha1(f"db_commit_{seed}".encode()).hexdigest()[:8]

        commit = GitCommit(
            commit_hash=commit_hash,
            author="dev-infra@company.internal",
            timestamp=t0 - timedelta(minutes=14),
            message="perf(orders): tune hikari db pool size to reduce idle memory",
            changed_files=["services/order-service/src/main/resources/application.yml"],
            diff=(
                "--- a/services/order-service/src/main/resources/application.yml\n"
                "+++ b/services/order-service/src/main/resources/application.yml\n"
                "@@ -18,4 +18,4 @@ datasource:\n"
                "-    maximum-pool-size: 100\n"
                "-    connection-timeout: 30000\n"
                "+    maximum-pool-size: 5\n"
                "+    connection-timeout: 30000\n"
            ),
        )

        metrics = [
            MetricAlert(
                service="postgres-orders",
                metric_name="db_pool_active_connections_ratio",
                value=1.0,
                threshold=0.85,
                unit="ratio",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=10),
            ),
            MetricAlert(
                service="order-service",
                metric_name="db_pool_pending_connection_requests",
                value=342.0 + (seed % 50),
                threshold=20.0,
                unit="count",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=8),
            ),
            MetricAlert(
                service="order-service",
                metric_name="http_requests_5xx_rate",
                value=0.89 + (seed % 10) * 0.01,
                threshold=0.05,
                unit="ratio",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=6),
            ),
            MetricAlert(
                service="edge-gateway",
                metric_name="http_requests_5xx_rate",
                value=0.74,
                threshold=0.05,
                unit="ratio",
                severity=AlertSeverity.WARNING,
                timestamp=t0 - timedelta(minutes=4),
            ),
        ]

        traces = [
            Trace(
                trace_id=f"tr-db-{seed}-1",
                span_id=f"sp-db-{seed}-1",
                service="postgres-orders",
                endpoint="SQL:SELECT * FROM orders WHERE user_id = $1",
                status_code=500,
                latency_ms=30001.0,
                error_message="ConnectionTimeout: HikariPool-1 - Connection is not available, request timed out after 30000ms.",
                stack_trace="com.zaxxer.hikari.pool.HikariPool.getConnection(HikariPool.java:182)\n\tat org.jooq.impl.DataSourceConnectionProvider.acquire",
                timestamp=t0 - timedelta(minutes=9),
            ),
            Trace(
                trace_id=f"tr-db-{seed}-2",
                span_id=f"sp-db-{seed}-2",
                service="order-service",
                endpoint="POST /api/v1/orders/checkout",
                status_code=500,
                latency_ms=30120.0,
                error_message="DatabasePoolExhausted: Unable to checkout order due to connection pool starvation",
                stack_trace="services.orders.CheckoutHandler.handle(CheckoutHandler.java:78)",
                timestamp=t0 - timedelta(minutes=7),
            ),
            Trace(
                trace_id=f"tr-db-{seed}-3",
                span_id=f"sp-db-{seed}-3",
                service="edge-gateway",
                endpoint="POST /checkout",
                status_code=504,
                latency_ms=30500.0,
                error_message="Gateway Timeout: Upstream order-service exceeded 30s deadline",
                stack_trace="gateway.proxy.HttpReverseProxy.handleTimeout(Proxy.kt:142)",
                timestamp=t0 - timedelta(minutes=5),
            ),
        ]

        incident = Incident(
            incident_id=f"INC-DB-POOL-{seed}",
            title="CRITICAL: order-service connection pool starvation causing checkout 504 timeouts",
            description="Elevated 504 gateway timeouts observed at edge-gateway. order-service hikari connection pool has 0 available connections.",
            started_at=t0,
            metrics=metrics,
            traces=traces,
            commits=[commit],
            environment="production",
            metadata={
                "scenario": IncidentScenario.DB_POOL_EXHAUSTION.value,
                "ground_truth_root_cause": "order-service",
                "ground_truth_category": IncidentCategory.DATABASE_POOL_EXHAUSTION.value,
            },
        )
        return incident, "order-service", IncidentCategory.DATABASE_POOL_EXHAUSTION

    def _gen_memory_leak(
        self, seed: int, rng: random.Random
    ) -> Tuple[Incident, str, IncidentCategory]:
        t0 = self.base_time + timedelta(minutes=seed % 60)
        commit_hash = hashlib.sha1(f"mem_commit_{seed}".encode()).hexdigest()[:8]

        commit = GitCommit(
            commit_hash=commit_hash,
            author="backend-lead@company.internal",
            timestamp=t0 - timedelta(minutes=25),
            message="feat(payments): add in-memory telemetry buffer for card audit metrics",
            changed_files=["services/payment-service/src/audit/buffer.py"],
            diff=(
                "--- a/services/payment-service/src/audit/buffer.py\n"
                "+++ b/services/payment-service/src/audit/buffer.py\n"
                "@@ -10,3 +10,6 @@ class AuditBuffer:\n"
                "+_GLOBAL_AUDIT_LOGS = [] # Unbounded static memory structure\n"
                "+def record_audit_event(event: dict):\n"
                "+    _GLOBAL_AUDIT_LOGS.append(event) # Never evicted or bounded by TTL\n"
            ),
        )

        metrics = [
            MetricAlert(
                service="payment-service",
                metric_name="container_memory_usage_ratio",
                value=0.985,
                threshold=0.85,
                unit="ratio",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=15),
            ),
            MetricAlert(
                service="payment-service",
                metric_name="k8s_container_oom_killed_total",
                value=5.0,
                threshold=1.0,
                unit="count",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=10),
            ),
            MetricAlert(
                service="payment-service",
                metric_name="http_requests_5xx_rate",
                value=0.82,
                threshold=0.05,
                unit="ratio",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=8),
            ),
            MetricAlert(
                service="order-service",
                metric_name="http_requests_5xx_rate",
                value=0.64,
                threshold=0.05,
                unit="ratio",
                severity=AlertSeverity.WARNING,
                timestamp=t0 - timedelta(minutes=6),
            ),
        ]

        traces = [
            Trace(
                trace_id=f"tr-mem-{seed}-1",
                span_id=f"sp-mem-{seed}-1",
                service="payment-service",
                endpoint="POST /v1/charge",
                status_code=502,
                latency_ms=1850.0,
                error_message="Process terminated by OOM killer (cgroup memory limit reached 1024MiB)",
                stack_trace="Kernel: Memory cgroup out of memory: Killed process 4118 (uvicorn)",
                timestamp=t0 - timedelta(minutes=12),
            ),
            Trace(
                trace_id=f"tr-mem-{seed}-2",
                span_id=f"sp-mem-{seed}-2",
                service="order-service",
                endpoint="POST /internal/payments/authorize",
                status_code=502,
                latency_ms=1900.0,
                error_message="Bad Gateway: payment-service connection reset by peer during pod restart",
                stack_trace="httpx.RemoteProtocolError: Server disconnected without sending a response.",
                timestamp=t0 - timedelta(minutes=9),
            ),
        ]

        incident = Incident(
            incident_id=f"INC-OOM-LEAK-{seed}",
            title="CRITICAL: payment-service crash-looping under OOMKilled events",
            description="payment-service pods continuously killed by Kubernetes OOMKiller. Upstream order-service experiencing 502 Bad Gateway errors.",
            started_at=t0,
            metrics=metrics,
            traces=traces,
            commits=[commit],
            environment="production",
            metadata={
                "scenario": IncidentScenario.MEMORY_LEAK.value,
                "ground_truth_root_cause": "payment-service",
                "ground_truth_category": IncidentCategory.MEMORY_LEAK_OOM.value,
            },
        )
        return incident, "payment-service", IncidentCategory.MEMORY_LEAK_OOM

    def _gen_cascading_503(
        self, seed: int, rng: random.Random
    ) -> Tuple[Incident, str, IncidentCategory]:
        t0 = self.base_time + timedelta(minutes=seed % 60)
        commit_hash = hashlib.sha1(f"503_commit_{seed}".encode()).hexdigest()[:8]

        commit = GitCommit(
            commit_hash=commit_hash,
            author="secops@company.internal",
            timestamp=t0 - timedelta(minutes=18),
            message="refactor(auth): enforce immediate remote jwks key validation on every request",
            changed_files=["services/auth-service/internal/middleware/jwt.go"],
            diff=(
                "--- a/services/auth-service/internal/middleware/jwt.go\n"
                "+++ b/services/auth-service/internal/middleware/jwt.go\n"
                "@@ -45,3 +45,4 @@ func ValidateToken(ctx context.Context, token string) error {\n"
                "-    key := localKeyCache.Get(keyID)\n"
                "+    // Fetch fresh JWKS on every request directly from external IdP\n"
                "+    key, err := http.Get('https://idp.internal.auth/oauth2/jwks')\n"
            ),
        )

        metrics = [
            MetricAlert(
                service="auth-service",
                metric_name="p99_latency_ms",
                value=5200.0 + (seed % 100),
                threshold=250.0,
                unit="ms",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=14),
            ),
            MetricAlert(
                service="edge-gateway",
                metric_name="circuit_breaker_open_state",
                value=1.0,
                threshold=0.0,
                unit="boolean",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=11),
            ),
            MetricAlert(
                service="edge-gateway",
                metric_name="http_requests_5xx_rate",
                value=0.96,
                threshold=0.05,
                unit="ratio",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=10),
            ),
        ]

        traces = [
            Trace(
                trace_id=f"tr-503-{seed}-1",
                span_id=f"sp-503-{seed}-1",
                service="auth-service",
                endpoint="POST /oauth/verify",
                status_code=504,
                latency_ms=5002.0,
                error_message="ContextDeadlineExceeded: remote JWKS endpoint timed out after 5000ms",
                stack_trace="net/http.Client.Do: context deadline exceeded",
                timestamp=t0 - timedelta(minutes=13),
            ),
            Trace(
                trace_id=f"tr-503-{seed}-2",
                span_id=f"sp-503-{seed}-2",
                service="edge-gateway",
                endpoint="GET /api/v1/profile",
                status_code=503,
                latency_ms=1.8,
                error_message="CircuitBreakerOpen: auth-service circuit breaker tripped OPEN - failing fast",
                stack_trace="resilience4j.circuitbreaker.CallNotPermittedException: CircuitBreaker 'auth-service' is OPEN",
                timestamp=t0 - timedelta(minutes=10),
            ),
        ]

        incident = Incident(
            incident_id=f"INC-CIRCUIT-503-{seed}",
            title="CRITICAL: Cascading 503 outage at edge-gateway triggered by auth-service circuit breaker",
            description="edge-gateway circuit breaker for auth-service tripped to OPEN due to remote JWKS latency degradation.",
            started_at=t0,
            metrics=metrics,
            traces=traces,
            commits=[commit],
            environment="production",
            metadata={
                "scenario": IncidentScenario.CASCADING_503.value,
                "ground_truth_root_cause": "auth-service",
                "ground_truth_category": IncidentCategory.CASCADING_503_CIRCUIT_BREAKER_TRIP.value,
            },
        )
        return incident, "auth-service", IncidentCategory.CASCADING_503_CIRCUIT_BREAKER_TRIP

    def _gen_config_regression(
        self, seed: int, rng: random.Random
    ) -> Tuple[Incident, str, IncidentCategory]:
        t0 = self.base_time + timedelta(minutes=seed % 60)
        commit_hash = hashlib.sha1(f"cfg_commit_{seed}".encode()).hexdigest()[:8]

        commit = GitCommit(
            commit_hash=commit_hash,
            author="sre-infra@company.internal",
            timestamp=t0 - timedelta(minutes=12),
            message="chore(inventory): update postgres database port in deployment spec",
            changed_files=["k8s/inventory-service/deployment.yaml"],
            diff=(
                "--- a/k8s/inventory-service/deployment.yaml\n"
                "+++ b/k8s/inventory-service/deployment.yaml\n"
                "@@ -32,2 +32,2 @@ env:\n"
                "-  - name: DB_PORT\n"
                "-    value: '5432'\n"
                "+  - name: DB_PORT\n"
                "+    value: '5433' # Port typo: DB is listening on 5432\n"
            ),
        )

        metrics = [
            MetricAlert(
                service="inventory-service",
                metric_name="connection_refused_rate",
                value=1.0,
                threshold=0.01,
                unit="ratio",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=9),
            ),
            MetricAlert(
                service="inventory-service",
                metric_name="http_requests_5xx_rate",
                value=0.92,
                threshold=0.05,
                unit="ratio",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=8),
            ),
        ]

        traces = [
            Trace(
                trace_id=f"tr-cfg-{seed}-1",
                span_id=f"sp-cfg-{seed}-1",
                service="inventory-service",
                endpoint="GET /items/stock",
                status_code=500,
                latency_ms=12.0,
                error_message="ECONNREFUSED: connect ECONNREFUSED postgres-inventory:5433",
                stack_trace="pg_connect.c: connection refused on port 5433",
                timestamp=t0 - timedelta(minutes=8),
            )
        ]

        incident = Incident(
            incident_id=f"INC-CONFIG-ERR-{seed}",
            title="CRITICAL: inventory-service failing with connection refused to postgres-inventory",
            description="inventory-service cannot connect to backend database following k8s configuration deployment.",
            started_at=t0,
            metrics=metrics,
            traces=traces,
            commits=[commit],
            environment="production",
            metadata={
                "scenario": IncidentScenario.CONFIG_REGRESSION.value,
                "ground_truth_root_cause": "inventory-service",
                "ground_truth_category": IncidentCategory.CONFIG_REGRESSION.value,
            },
        )
        return incident, "inventory-service", IncidentCategory.CONFIG_REGRESSION

    def _gen_cache_stampede(
        self, seed: int, rng: random.Random
    ) -> Tuple[Incident, str, IncidentCategory]:
        t0 = self.base_time + timedelta(minutes=seed % 60)
        commit_hash = hashlib.sha1(f"cache_commit_{seed}".encode()).hexdigest()[:8]

        commit = GitCommit(
            commit_hash=commit_hash,
            author="catalog-team@company.internal",
            timestamp=t0 - timedelta(minutes=22),
            message="fix(catalog): disable cache retention to always show real-time discounts",
            changed_files=["services/catalog-service/src/cache/policy.py"],
            diff=(
                "--- a/services/catalog-service/src/cache/policy.py\n"
                "+++ b/services/catalog-service/src/cache/policy.py\n"
                "@@ -15,2 +15,2 @@\n"
                "-CACHE_EXPIRATION_SECONDS = 3600\n"
                "+CACHE_EXPIRATION_SECONDS = 0 # Instant eviction causes complete cache bypass\n"
            ),
        )

        metrics = [
            MetricAlert(
                service="redis-cache",
                metric_name="cache_hit_ratio",
                value=0.01,
                threshold=0.85,
                unit="ratio",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=15),
            ),
            MetricAlert(
                service="mongo-catalog",
                metric_name="active_database_connections",
                value=4800.0,
                threshold=1000.0,
                unit="count",
                severity=AlertSeverity.CRITICAL,
                timestamp=t0 - timedelta(minutes=12),
            ),
            MetricAlert(
                service="catalog-service",
                metric_name="http_requests_5xx_rate",
                value=0.78,
                threshold=0.05,
                unit="ratio",
                severity=AlertSeverity.WARNING,
                timestamp=t0 - timedelta(minutes=10),
            ),
        ]

        traces = [
            Trace(
                trace_id=f"tr-cache-{seed}-1",
                span_id=f"sp-cache-{seed}-1",
                service="catalog-service",
                endpoint="GET /catalog/products",
                status_code=504,
                latency_ms=4500.0,
                error_message="MongoPoolTimeout: Connection pool exhausted due to cache stampede dogpiling database",
                stack_trace="pymongo.errors.ConnectionFailure: Max pool size reached",
                timestamp=t0 - timedelta(minutes=11),
            )
        ]

        incident = Incident(
            incident_id=f"INC-STAMPEDE-{seed}",
            title="CRITICAL: catalog-service cache stampede overwhelming mongo-catalog database",
            description="redis-cache hit ratio dropped to 1%, causing thundering herd to saturate downstream mongo-catalog.",
            started_at=t0,
            metrics=metrics,
            traces=traces,
            commits=[commit],
            environment="production",
            metadata={
                "scenario": IncidentScenario.CACHE_STAMPEDE.value,
                "ground_truth_root_cause": "catalog-service",
                "ground_truth_category": IncidentCategory.CACHE_STAMPEDE.value,
            },
        )
        return incident, "catalog-service", IncidentCategory.CACHE_STAMPEDE

    def generate_suite(
        self, count: int = 50, start_seed: int = 100
    ) -> List[Tuple[Incident, str, IncidentCategory]]:
        """
        Generates a deterministic benchmark suite of diverse incidents.
        """
        scenarios = list(IncidentScenario)
        suite = []
        for i in range(count):
            seed = start_seed + i
            scenario = scenarios[i % len(scenarios)]
            incident_tuple = self.generate(scenario=scenario, seed=seed)
            suite.append(incident_tuple)
        return suite


def generate_synthetic_incident(
    scenario: str = "db_pool_exhaustion", seed: int = 42
) -> Incident:
    """Convenience helper function returning an Incident object."""
    gen = SyntheticIncidentGenerator()
    inc, _, _ = gen.generate(scenario=scenario, seed=seed)
    return inc
