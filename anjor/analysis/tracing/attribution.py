"""AttributionAnalyser — per-agent token and failure breakdown within a trace.

Pure module: no I/O, no async, no framework dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class AgentAttribution:
    """Token and failure attribution for a single agent within a trace set."""

    agent_name: str
    span_count: int
    token_input: int
    token_output: int
    token_total: int
    token_share_pct: float  # % of total tokens across all agents in scope
    tool_calls_count: int
    llm_calls_count: int
    failure_count: int
    failure_rate: float


class AttributionAnalyser:
    """Break down token consumption and failures by agent name.

    Usage::

        spans = [...]  # list of raw span dicts
        results = AttributionAnalyser().analyse(spans)
        # sorted by token_total descending
    """

    def analyse(self, spans: list[dict[str, Any]]) -> list[AgentAttribution]:
        """Return per-agent attribution sorted by total token consumption desc."""
        if not spans:
            return []

        # Accumulate per agent_name
        buckets: dict[str, dict[str, Any]] = {}
        for span in spans:
            name = span.get("agent_name") or "unknown"
            if name not in buckets:
                buckets[name] = {
                    "span_count": 0,
                    "token_input": 0,
                    "token_output": 0,
                    "tool_calls_count": 0,
                    "llm_calls_count": 0,
                    "failure_count": 0,
                }
            b = buckets[name]
            b["span_count"] += 1
            b["token_input"] += int(span.get("token_input", 0))
            b["token_output"] += int(span.get("token_output", 0))
            b["tool_calls_count"] += int(span.get("tool_calls_count", 0))
            b["llm_calls_count"] += int(span.get("llm_calls_count", 0))
            if span.get("status") == "error":
                b["failure_count"] += 1

        grand_total = sum(b["token_input"] + b["token_output"] for b in buckets.values())

        results = []
        for name, b in buckets.items():
            token_total = b["token_input"] + b["token_output"]
            share = (token_total / grand_total * 100) if grand_total > 0 else 0.0
            failure_rate = b["failure_count"] / b["span_count"] if b["span_count"] > 0 else 0.0
            results.append(
                AgentAttribution(
                    agent_name=name,
                    span_count=b["span_count"],
                    token_input=b["token_input"],
                    token_output=b["token_output"],
                    token_total=token_total,
                    token_share_pct=round(share, 2),
                    tool_calls_count=b["tool_calls_count"],
                    llm_calls_count=b["llm_calls_count"],
                    failure_count=b["failure_count"],
                    failure_rate=round(failure_rate, 4),
                )
            )

        return sorted(results, key=lambda a: a.token_total, reverse=True)
