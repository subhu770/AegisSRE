"""
Telemetry Agent for parsing anomalous Prometheus metric spikes and microservice traces.
"""

from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional

from src.agents.state import IncidentState
from src.api.schemas import TelemetryAnalysisResult


class TelemetryAgent:
    """
    Parses and correlates Prometheus metric spikes, error rates, latency percentiles,
    and distributed tracing logs. Isolates the initial failure epicenter service.
    """

    def __init__(self) -> None:
        pass

    async def run(self, state: IncidentState) -> Dict[str, Any]:
        """
        Execute telemetry parsing and state enrichment.
        """
        metrics = state.get("metrics", [])
        traces = state.get("traces", [])

        # 1. Analyze Metric Spikes
        service_metric_scores: Dict[str, float] = defaultdict(float)
        primary_spikes: List[str] = []

        for m in metrics:
            srv = m.get("service", "unknown")
            metric_name = m.get("metric_name", "")
            val = float(m.get("value", 0.0))
            thresh = float(m.get("threshold", 1.0))
            severity = m.get("severity", "CRITICAL")

            # Score based on threshold exceedance factor and severity
            ratio = (val / thresh) if thresh > 0 else 1.0
            weight = 3.0 if severity == "CRITICAL" else 1.0
            service_metric_scores[srv] += ratio * weight

            if ratio > 1.2:
                primary_spikes.append(f"{srv}::{metric_name}={val} (threshold={thresh})")

        # 2. Analyze Traces & Chronological Order
        service_trace_scores: Dict[str, float] = defaultdict(float)
        error_signatures: List[str] = []
        earliest_error_time: Optional[datetime] = None
        earliest_service: Optional[str] = None

        parsed_traces = []
        for t in traces:
            status = int(t.get("status_code", 200))
            srv = t.get("service", "unknown")
            ts_str = t.get("timestamp")
            
            ts: Optional[datetime] = None
            if isinstance(ts_str, str):
                try:
                    ts = datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
                except Exception:
                    pass
            elif isinstance(ts_str, datetime):
                ts = ts_str

            err_msg = t.get("error_message") or ""
            latency = float(t.get("latency_ms", 0.0))

            if status >= 500 or err_msg:
                # Weight internal 500/OOM/Timeout heavier than upstream 502/503/504
                trace_weight = 4.0 if status == 500 or "OOM" in err_msg or "Timeout" in err_msg else 1.5
                service_trace_scores[srv] += trace_weight

                sig = f"[{srv} HTTP {status}] {err_msg[:90]}"
                if sig not in error_signatures:
                    error_signatures.append(sig)

                if ts:
                    if earliest_error_time is None or ts < earliest_error_time:
                        earliest_error_time = ts
                        earliest_service = srv

        # 3. Identify Epicenter Service
        combined_scores: Dict[str, float] = defaultdict(float)
        all_services = set(service_metric_scores.keys()).union(set(service_trace_scores.keys()))

        for srv in all_services:
            m_score = service_metric_scores.get(srv, 0.0)
            t_score = service_trace_scores.get(srv, 0.0)
            combined_scores[srv] = (m_score * 1.5) + (t_score * 2.0)
            # Give boost to earliest failing service in trace logs
            if srv == earliest_service:
                combined_scores[srv] += 10.0

        anomalous_services = sorted(combined_scores.keys(), key=lambda s: combined_scores[s], reverse=True)
        epicenter = anomalous_services[0] if anomalous_services else "unknown"

        # 4. Formulate Evidence Summary
        confidence = 0.92 if anomalous_services else 0.20
        primary_spike_str = primary_spikes[0] if primary_spikes else "None"
        evidence_summary = (
            f"Telemetry identified failure epicenter at '{epicenter}' based on "
            f"{len(metrics)} anomalous metric alerts and {len(traces)} distributed trace spans. "
            f"Earliest failing trace originated from '{earliest_service or epicenter}'. "
            f"Primary metric anomaly: {primary_spike_str}."
        )

        telemetry_output = TelemetryAnalysisResult(
            anomalous_services=anomalous_services,
            epicenter_service=epicenter,
            anomaly_confidence=confidence,
            primary_metric_spike=primary_spike_str,
            earliest_error_timestamp=earliest_error_time,
            error_signatures=error_signatures[:5],
            evidence_summary=evidence_summary,
        )

        return telemetry_output.model_dump()
