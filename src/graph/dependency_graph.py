"""
Service Dependency Graph Engine using NetworkX.

Models distributed microservice architecture topologies, determines caller/callee
relationships, identifies critical paths, and computes quantitative blast radius
metrics when a service fails.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple
import networkx as nx


class ServiceTier(str, Enum):
    """Criticality tiers for microservices."""
    TIER_0 = "TIER_0"  # Mission-critical / Revenue-impacting (e.g., Gateway, Payments, Auth)
    TIER_1 = "TIER_1"  # Core Business Logic (e.g., Orders, Inventory)
    TIER_2 = "TIER_2"  # Auxiliary / Non-critical (e.g., Notifications, Analytics, Catalog)


# Criticality weight mapping for blast radius scoring
TIER_WEIGHTS = {
    ServiceTier.TIER_0: 1.0,
    ServiceTier.TIER_1: 0.6,
    ServiceTier.TIER_2: 0.3,
}


@dataclass
class ServiceNode:
    """Metadata describing a microservice node in the dependency graph."""
    name: str
    tier: ServiceTier
    team: str
    sla: float = 99.99
    description: str = ""
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class BlastRadiusReport:
    """Quantitative evaluation of failure propagation for a failed service."""
    root_service: str
    impacted_services: List[str]
    total_services: int
    impact_ratio: float
    weighted_blast_radius_score: float
    risk_level: str
    critical_paths: List[List[str]]
    tier_breakdown: Dict[str, List[str]]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "root_service": self.root_service,
            "impacted_services": self.impacted_services,
            "total_services": self.total_services,
            "impact_ratio": round(self.impact_ratio, 4),
            "weighted_blast_radius_score": round(self.weighted_blast_radius_score, 4),
            "risk_level": self.risk_level,
            "critical_paths": self.critical_paths,
            "tier_breakdown": self.tier_breakdown,
        }


class DependencyGraph:
    """
    Service Dependency Graph using NetworkX DiGraph.

    Graph Edge Convention:
        An edge `(u, v)` represents that service `u` CALLS / DEPENDS ON service `v`.
        Example: `edge-gateway` -> `order-service` -> `postgres-orders`.

    Failure Propagation Semantics:
        If service `v` degrades or crashes, service `u` (its caller) is directly impacted.
        Any service that has a directed path to `v` is transitively impacted (upstream callers).
    """

    def __init__(self) -> None:
        self.graph = nx.DiGraph()
        self.nodes_data: Dict[str, ServiceNode] = {}

    def add_service(
        self,
        name: str,
        tier: ServiceTier = ServiceTier.TIER_1,
        team: str = "platform",
        sla: float = 99.9,
        description: str = "",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Add a microservice node to the graph."""
        node = ServiceNode(
            name=name,
            tier=tier,
            team=team,
            sla=sla,
            description=description,
            metadata=metadata or {},
        )
        self.nodes_data[name] = node
        self.graph.add_node(
            name,
            tier=tier.value,
            team=team,
            sla=sla,
            description=description,
            **node.metadata,
        )

    def add_dependency(
        self,
        caller: str,
        callee: str,
        protocol: str = "http",
        timeout_ms: int = 1500,
        fallback_enabled: bool = False,
    ) -> None:
        """
        Record a dependency: `caller` -> `callee` (caller calls callee).
        """
        if caller not in self.graph:
            self.add_service(caller)
        if callee not in self.graph:
            self.add_service(callee)

        self.graph.add_edge(
            caller,
            callee,
            protocol=protocol,
            timeout_ms=timeout_ms,
            fallback_enabled=fallback_enabled,
        )

    def get_direct_callers(self, service: str) -> List[str]:
        """Services that directly call this service."""
        if service not in self.graph:
            return []
        return list(self.graph.predecessors(service))

    def get_direct_dependencies(self, service: str) -> List[str]:
        """Services that this service directly calls."""
        if service not in self.graph:
            return []
        return list(self.graph.successors(service))

    def get_impacted_services(self, root_service: str) -> Set[str]:
        """
        Get all services impacted if `root_service` fails.
        Since edge (u, v) = u calls v, if v fails, all nodes from which v can be reached
        are impacted upstream callers.
        """
        if root_service not in self.graph:
            return {root_service}

        # In reversed graph, edges point from callee to caller
        reversed_graph = self.graph.reverse(copy=False)
        impacted: Set[str] = set(nx.descendants(reversed_graph, root_service))
        impacted.add(root_service)
        return impacted

    def get_critical_paths_to_service(
        self,
        service: str,
        entrypoints: Optional[List[str]] = None,
    ) -> List[List[str]]:
        """
        Identify invocation paths from top-level entrypoints (e.g. edge-gateway)
        down to the target service.
        """
        if service not in self.graph:
            return []

        if entrypoints is None:
            # Entrypoints are nodes with in-degree 0 in dependency graph (no other internal service calls them)
            entrypoints = [node for node, in_deg in self.graph.in_degree() if in_deg == 0]
            if not entrypoints:
                entrypoints = list(self.graph.nodes())[:1]

        paths: List[List[str]] = []
        for ep in entrypoints:
            if ep == service:
                paths.append([ep])
            elif nx.has_path(self.graph, ep, service):
                for p in nx.all_shortest_paths(self.graph, ep, service):
                    paths.append(list(p))
        return paths

    def calculate_blast_radius(self, root_service: str) -> BlastRadiusReport:
        """
        Calculates comprehensive blast radius metrics when `root_service` experiences an incident.
        """
        total_services = max(len(self.graph.nodes), 1)
        impacted_nodes = self.get_impacted_services(root_service)

        tier_breakdown: Dict[str, List[str]] = {
            ServiceTier.TIER_0.value: [],
            ServiceTier.TIER_1.value: [],
            ServiceTier.TIER_2.value: [],
        }

        weighted_score_sum = 0.0
        total_possible_weight = 0.0

        for node_name in self.graph.nodes:
            node_obj = self.nodes_data.get(node_name)
            tier = node_obj.tier if node_obj else ServiceTier.TIER_1
            weight = TIER_WEIGHTS.get(tier, 0.5)
            total_possible_weight += weight

            if node_name in impacted_nodes:
                weighted_score_sum += weight
                tier_breakdown[tier.value].append(node_name)

        impact_ratio = len(impacted_nodes) / total_services
        normalized_weighted_score = (
            weighted_score_sum / total_possible_weight if total_possible_weight > 0 else impact_ratio
        )

        # Risk level categorization
        if normalized_weighted_score >= 0.5 or len(tier_breakdown[ServiceTier.TIER_0.value]) >= 2:
            risk_level = "CRITICAL"
        elif normalized_weighted_score >= 0.25 or len(tier_breakdown[ServiceTier.TIER_0.value]) >= 1:
            risk_level = "HIGH"
        elif normalized_weighted_score >= 0.12 or len(tier_breakdown[ServiceTier.TIER_1.value]) >= 1:
            risk_level = "MEDIUM"
        else:
            risk_level = "LOW"

        critical_paths = self.get_critical_paths_to_service(root_service)

        return BlastRadiusReport(
            root_service=root_service,
            impacted_services=sorted(list(impacted_nodes)),
            total_services=total_services,
            impact_ratio=impact_ratio,
            weighted_blast_radius_score=normalized_weighted_score,
            risk_level=risk_level,
            critical_paths=critical_paths,
            tier_breakdown=tier_breakdown,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize graph to dictionary structure."""
        nodes = []
        for n, data in self.graph.nodes(data=True):
            nodes.append({
                "id": n,
                "tier": data.get("tier", ServiceTier.TIER_1.value),
                "team": data.get("team", "unassigned"),
                "sla": data.get("sla", 99.9),
                "description": data.get("description", ""),
            })

        edges = []
        for u, v, data in self.graph.edges(data=True):
            edges.append({
                "source": u,
                "target": v,
                "protocol": data.get("protocol", "http"),
                "timeout_ms": data.get("timeout_ms", 1500),
                "fallback_enabled": data.get("fallback_enabled", False),
            })

        return {"nodes": nodes, "edges": edges}

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "DependencyGraph":
        """Reconstruct graph from dictionary."""
        dep_graph = cls()
        for node in data.get("nodes", []):
            tier_str = node.get("tier", "TIER_1")
            try:
                tier = ServiceTier(tier_str)
            except ValueError:
                tier = ServiceTier.TIER_1
            dep_graph.add_service(
                name=node["id"],
                tier=tier,
                team=node.get("team", "unassigned"),
                sla=node.get("sla", 99.9),
                description=node.get("description", ""),
            )
        for edge in data.get("edges", []):
            dep_graph.add_dependency(
                caller=edge["source"],
                callee=edge["target"],
                protocol=edge.get("protocol", "http"),
                timeout_ms=edge.get("timeout_ms", 1500),
                fallback_enabled=edge.get("fallback_enabled", False),
            )
        return dep_graph


def create_default_topology() -> DependencyGraph:
    """
    Standard microservice topology representing a modern cloud architecture:
    edge-gateway -> auth-service -> redis-session
                 -> order-service -> payment-service -> postgres-payments
                                  -> inventory-service -> postgres-inventory
                                  -> postgres-orders
                 -> catalog-service -> redis-cache
                                    -> mongo-catalog
                 -> notification-service -> kafka-broker
    """
    dg = DependencyGraph()

    # Tier 0 services (Mission-critical)
    dg.add_service("edge-gateway", tier=ServiceTier.TIER_0, team="traffic", sla=99.99, description="API Edge Gateway")
    dg.add_service("auth-service", tier=ServiceTier.TIER_0, team="security", sla=99.99, description="JWT & User Auth")
    dg.add_service("payment-service", tier=ServiceTier.TIER_0, team="checkout", sla=99.99, description="Stripe/Card Processing")

    # Tier 1 services (Core business)
    dg.add_service("order-service", tier=ServiceTier.TIER_1, team="checkout", sla=99.95, description="Order Placement Engine")
    dg.add_service("inventory-service", tier=ServiceTier.TIER_1, team="logistics", sla=99.95, description="Stock & Fulfillment")
    dg.add_service("postgres-orders", tier=ServiceTier.TIER_1, team="data-infra", sla=99.99, description="Primary Orders RDBMS")
    dg.add_service("postgres-payments", tier=ServiceTier.TIER_0, team="data-infra", sla=99.99, description="Ledger Database")
    dg.add_service("postgres-inventory", tier=ServiceTier.TIER_1, team="data-infra", sla=99.95, description="Inventory Database")

    # Tier 2 services (Auxiliary)
    dg.add_service("catalog-service", tier=ServiceTier.TIER_2, team="search", sla=99.5, description="Product Search & Browse")
    dg.add_service("notification-service", tier=ServiceTier.TIER_2, team="comms", sla=99.0, description="Email & SMS Alerts")
    dg.add_service("redis-session", tier=ServiceTier.TIER_1, team="caching", sla=99.9, description="Session Cache Store")
    dg.add_service("redis-cache", tier=ServiceTier.TIER_2, team="caching", sla=99.5, description="Catalog Read Cache")
    dg.add_service("mongo-catalog", tier=ServiceTier.TIER_2, team="search", sla=99.5, description="NoSQL Document Catalog")
    dg.add_service("kafka-broker", tier=ServiceTier.TIER_1, team="messaging", sla=99.9, description="Distributed Event Bus")

    # Wire dependencies: (caller -> callee)
    dg.add_dependency("edge-gateway", "auth-service", protocol="grpc", timeout_ms=500)
    dg.add_dependency("edge-gateway", "order-service", protocol="http", timeout_ms=2000)
    dg.add_dependency("edge-gateway", "catalog-service", protocol="http", timeout_ms=800)

    dg.add_dependency("auth-service", "redis-session", protocol="redis", timeout_ms=100)

    dg.add_dependency("order-service", "auth-service", protocol="grpc", timeout_ms=500)
    dg.add_dependency("order-service", "payment-service", protocol="http", timeout_ms=3000)
    dg.add_dependency("order-service", "inventory-service", protocol="http", timeout_ms=1500)
    dg.add_dependency("order-service", "postgres-orders", protocol="sql", timeout_ms=2500)
    dg.add_dependency("order-service", "notification-service", protocol="amqp", timeout_ms=500)

    dg.add_dependency("payment-service", "postgres-payments", protocol="sql", timeout_ms=2000)
    dg.add_dependency("inventory-service", "postgres-inventory", protocol="sql", timeout_ms=1500)

    dg.add_dependency("catalog-service", "redis-cache", protocol="redis", timeout_ms=100)
    dg.add_dependency("catalog-service", "mongo-catalog", protocol="mongo", timeout_ms=1000)

    dg.add_dependency("notification-service", "kafka-broker", protocol="kafka", timeout_ms=1000)

    return dg
