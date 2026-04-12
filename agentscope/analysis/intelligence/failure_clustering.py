"""FailureClusterer — groups historical tool call failures into patterns.

Phase 3 intelligence: move from passive event logging to active insight.
Clusters failures by (tool_name, failure_type) and generates natural-language
descriptions and actionable suggestions.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass, field
from typing import Any

from agentscope.analysis.base import BaseAnalyser


@dataclass
class FailureCluster:
    """A cluster of similar failures for a given tool + failure type."""

    tool_name: str
    failure_type: str
    occurrence_count: int
    total_calls: int
    failure_rate: float  # [0.0, 1.0]
    avg_latency_ms: float
    pattern_description: str
    suggestion: str
    example_trace_ids: list[str] = field(default_factory=list)


# DECISION: suggestion templates are keyed by failure_type so they remain
# testable in isolation and can be overridden without modifying the clusterer.
_SUGGESTIONS: dict[str, str] = {
    "timeout": (
        "Add retry logic with exponential back-off. "
        "Check if the tool's upstream service has SLA guarantees that match your timeout threshold."
    ),
    "schema_drift": (
        "Pin the tool's API version if available, or add a schema validation step "
        "before injecting output into the agent's context."
    ),
    "api_error": (
        "Review the tool's error response handling. "
        "Consider circuit-breaker logic to prevent cascading failures."
    ),
    "unknown": (
        "Inspect raw tool call payloads for the affected trace IDs "
        "to identify the root cause."
    ),
}


class FailureClusterer(BaseAnalyser):
    """Clusters tool call failures from historical data.

    Input: raw tool_call rows as returned by StorageBackend.query_tool_calls()
    Output: list[FailureCluster], sorted by failure_rate descending
    """

    def analyse(self, data: list[dict[str, Any]]) -> list[FailureCluster]:
        """Cluster failures and return patterns with descriptions."""
        return self.cluster(data)

    def cluster(self, tool_calls: list[dict[str, Any]]) -> list[FailureCluster]:
        """Group tool calls into failure clusters.

        Args:
            tool_calls: Raw row dicts from StorageBackend.query_tool_calls().

        Returns:
            List of FailureCluster sorted by failure_rate descending.
        """
        # Aggregate per-tool totals and per-(tool, failure_type) failure data
        tool_totals: dict[str, int] = {}
        # key: (tool_name, failure_type)
        cluster_data: dict[tuple[str, str], _ClusterAccumulator] = {}

        for row in tool_calls:
            tool_name = row.get("tool_name", "unknown")
            status = row.get("status", "")
            failure_type = row.get("failure_type") or "unknown"
            latency_ms = float(row.get("latency_ms") or 0.0)
            trace_id = row.get("trace_id", "")

            tool_totals[tool_name] = tool_totals.get(tool_name, 0) + 1

            if status != "failure":
                continue

            key = (tool_name, failure_type)
            if key not in cluster_data:
                cluster_data[key] = _ClusterAccumulator(tool_name, failure_type)
            cluster_data[key].add(latency_ms, trace_id)

        clusters: list[FailureCluster] = []
        for (tool_name, failure_type), acc in cluster_data.items():
            total = tool_totals.get(tool_name, acc.count)
            failure_rate = acc.count / total if total > 0 else 0.0
            avg_latency = statistics.mean(acc.latencies) if acc.latencies else 0.0
            description = self._describe(
                tool_name, failure_type, acc.count, failure_rate, avg_latency
            )
            suggestion = _SUGGESTIONS.get(failure_type.lower(), _SUGGESTIONS["unknown"])
            clusters.append(
                FailureCluster(
                    tool_name=tool_name,
                    failure_type=failure_type,
                    occurrence_count=acc.count,
                    total_calls=total,
                    failure_rate=round(failure_rate, 4),
                    avg_latency_ms=round(avg_latency, 2),
                    pattern_description=description,
                    suggestion=suggestion,
                    example_trace_ids=acc.trace_ids[:5],
                )
            )

        return sorted(clusters, key=lambda c: c.failure_rate, reverse=True)

    @staticmethod
    def _describe(
        tool_name: str,
        failure_type: str,
        count: int,
        rate: float,
        avg_latency_ms: float,
    ) -> str:
        pct = f"{rate * 100:.1f}%"
        latency_note = (
            f" (avg latency {avg_latency_ms:,.0f}ms)"
            if failure_type.lower() == "timeout" and avg_latency_ms > 0
            else ""
        )
        return (
            f"Tool '{tool_name}' failed with {failure_type.upper()} "
            f"{count} time(s) — {pct} failure rate{latency_note}."
        )


class _ClusterAccumulator:
    """Internal accumulator for a single (tool_name, failure_type) cluster."""

    def __init__(self, tool_name: str, failure_type: str) -> None:
        self.tool_name = tool_name
        self.failure_type = failure_type
        self.count = 0
        self.latencies: list[float] = []
        self.trace_ids: list[str] = []

    def add(self, latency_ms: float, trace_id: str) -> None:
        self.count += 1
        self.latencies.append(latency_ms)
        if trace_id and trace_id not in self.trace_ids:
            self.trace_ids.append(trace_id)
