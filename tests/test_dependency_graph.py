"""
Unit tests for DependencyGraph and Blast Radius calculation.
"""

import pytest
from src.graph.dependency_graph import (
    DependencyGraph,
    ServiceTier,
    create_default_topology,
)


def test_dependency_graph_creation():
    dg = DependencyGraph()
    dg.add_service("svc-a", tier=ServiceTier.TIER_0, team="team-a")
    dg.add_service("svc-b", tier=ServiceTier.TIER_1, team="team-b")
    dg.add_dependency("svc-a", "svc-b", protocol="http")

    assert "svc-a" in dg.graph.nodes
    assert "svc-b" in dg.graph.nodes
    assert dg.graph.has_edge("svc-a", "svc-b")
    assert dg.get_direct_callers("svc-b") == ["svc-a"]
    assert dg.get_direct_dependencies("svc-a") == ["svc-b"]


def test_default_topology_structure():
    dg = create_default_topology()

    # Core microservices must exist
    assert "edge-gateway" in dg.graph.nodes
    assert "auth-service" in dg.graph.nodes
    assert "order-service" in dg.graph.nodes
    assert "payment-service" in dg.graph.nodes
    assert "postgres-orders" in dg.graph.nodes

    # Check key dependencies (caller -> callee)
    assert dg.graph.has_edge("edge-gateway", "auth-service")
    assert dg.graph.has_edge("edge-gateway", "order-service")
    assert dg.graph.has_edge("order-service", "postgres-orders")
    assert dg.graph.has_edge("payment-service", "postgres-payments")


def test_blast_radius_postgres_orders():
    dg = create_default_topology()
    report = dg.calculate_blast_radius("postgres-orders")

    # If postgres-orders fails, order-service and edge-gateway are impacted callers
    assert "postgres-orders" in report.impacted_services
    assert "order-service" in report.impacted_services
    assert "edge-gateway" in report.impacted_services

    # Verify blast radius calculations
    assert report.total_services == len(dg.graph.nodes)
    assert 0.0 < report.impact_ratio <= 1.0
    assert 0.0 < report.weighted_blast_radius_score <= 1.0
    assert report.risk_level in ["CRITICAL", "HIGH", "MEDIUM", "LOW"]

    # Critical paths must reach from edge-gateway to postgres-orders
    assert any(
        path == ["edge-gateway", "order-service", "postgres-orders"]
        for path in report.critical_paths
    )


def test_blast_radius_edge_gateway():
    dg = create_default_topology()
    report = dg.calculate_blast_radius("edge-gateway")

    # edge-gateway has no internal callers calling it
    assert report.impacted_services == ["edge-gateway"]
    assert report.risk_level in ["CRITICAL", "HIGH"]


def test_graph_serialization_roundtrip():
    dg = create_default_topology()
    data = dg.to_dict()

    assert "nodes" in data
    assert "edges" in data
    assert len(data["nodes"]) == len(dg.graph.nodes)
    assert len(data["edges"]) == len(dg.graph.edges)

    reconstructed = DependencyGraph.from_dict(data)
    assert len(reconstructed.graph.nodes) == len(dg.graph.nodes)
    assert len(reconstructed.graph.edges) == len(dg.graph.edges)
    assert reconstructed.graph.has_edge("edge-gateway", "order-service")


def test_nonexistent_service_blast_radius():
    dg = create_default_topology()
    report = dg.calculate_blast_radius("unknown-service")
    assert report.impacted_services == ["unknown-service"]
    assert report.total_services == len(dg.graph.nodes)
