"""
Deterministic synthetic incident simulation engine for AegisSRE.
"""

from src.simulation.incident_generator import (
    IncidentScenario,
    SyntheticIncidentGenerator,
    generate_synthetic_incident,
)

__all__ = [
    "IncidentScenario",
    "SyntheticIncidentGenerator",
    "generate_synthetic_incident",
]
