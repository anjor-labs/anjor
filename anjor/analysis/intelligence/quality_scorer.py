"""QualityScorer — per-tool reliability scores and per-run quality scores.

Phase 3 intelligence: synthesise multiple observability signals into a single
grade that makes it easy to triage which tools or runs need attention.
"""

from __future__ import annotations

import statistics
from dataclasses import dataclass
from typing import Any

from anjor.analysis.base import BaseAnalyser

# Score weights for the overall tool quality score
_TOOL_WEIGHTS = {
    "reliability": 0.5,  # failure rate is the most important signal
    "schema_stability": 0.3,
    "latency_consistency": 0.2,
}

# Score weights for the overall agent-run quality score
_RUN_WEIGHTS = {
    "context_efficiency": 0.5,
    "failure_recovery": 0.3,
    "tool_diversity": 0.2,
}


def _grade(score: float) -> str:
    """Map a [0.0, 1.0] score to a letter grade."""
    if score >= 0.9:
        return "A"
    if score >= 0.75:
        return "B"
    if score >= 0.6:
        return "C"
    if score >= 0.4:
        return "D"
    return "F"


@dataclass
class ToolQualityScore:
    """Quality signals for a single tool, aggregated across all its calls."""

    tool_name: str
    call_count: int
    reliability_score: float  # 1 - failure_rate
    schema_stability_score: float  # 1 - drift_rate
    latency_consistency_score: float  # 1 - coefficient_of_variation (clamped)
    overall_score: float
    grade: str


@dataclass
class AgentRunQualityScore:
    """Quality signals for a single agent run (trace_id)."""

    trace_id: str
    llm_call_count: int
    tool_call_count: int
    context_efficiency_score: float  # 1 - peak_context_utilisation
    failure_recovery_score: float  # fraction of failure types not repeated in the run
    tool_diversity_score: float  # normalised unique tools / total calls
    overall_score: float
    grade: str


class QualityScorer(BaseAnalyser):
    """Computes quality scores from raw event data.

    Tool scoring: call score_tools(tool_call_rows)
    Run scoring:  call score_runs(tool_call_rows, llm_call_rows)
    """

    def analyse(
        self,
        data: tuple[list[dict[str, Any]], list[dict[str, Any]]],
    ) -> tuple[list[ToolQualityScore], list[AgentRunQualityScore]]:
        """Convenience wrapper: returns (tool_scores, run_scores)."""
        tool_calls, llm_calls = data
        return self.score_tools(tool_calls), self.score_runs(tool_calls, llm_calls)

    def score_tools(self, tool_calls: list[dict[str, Any]]) -> list[ToolQualityScore]:
        """Compute quality scores for every tool seen in the event data.

        Args:
            tool_calls: Raw row dicts from StorageBackend.query_tool_calls().

        Returns:
            List of ToolQualityScore sorted by overall_score ascending
            (worst tools first — the ones that need attention).
        """
        # Group rows by tool_name
        by_tool: dict[str, list[dict[str, Any]]] = {}
        for row in tool_calls:
            name = row.get("tool_name", "unknown")
            by_tool.setdefault(name, []).append(row)

        scores: list[ToolQualityScore] = []
        for tool_name, rows in by_tool.items():
            score = self._score_single_tool(tool_name, rows)
            scores.append(score)

        return sorted(scores, key=lambda s: s.overall_score)

    def score_runs(
        self,
        tool_calls: list[dict[str, Any]],
        llm_calls: list[dict[str, Any]],
    ) -> list[AgentRunQualityScore]:
        """Compute quality scores for every unique trace_id in the event data.

        Args:
            tool_calls: Raw tool_call rows.
            llm_calls: Raw llm_call rows (for context utilisation).

        Returns:
            List of AgentRunQualityScore sorted by overall_score ascending.
        """
        # Gather all trace_ids
        all_traces = {str(r.get("trace_id", "")) for r in tool_calls} | {
            str(r.get("trace_id", "")) for r in llm_calls
        }
        all_traces.discard("")

        scores: list[AgentRunQualityScore] = []
        for trace_id in all_traces:
            tc = [r for r in tool_calls if r.get("trace_id") == trace_id]
            lc = [r for r in llm_calls if r.get("trace_id") == trace_id]
            score = self._score_single_run(trace_id, tc, lc)
            scores.append(score)

        return sorted(scores, key=lambda s: s.overall_score)

    @staticmethod
    def _score_single_tool(tool_name: str, rows: list[dict[str, Any]]) -> ToolQualityScore:
        call_count = len(rows)
        if call_count == 0:
            return ToolQualityScore(
                tool_name=tool_name,
                call_count=0,
                reliability_score=1.0,
                schema_stability_score=1.0,
                latency_consistency_score=1.0,
                overall_score=1.0,
                grade="A",
            )

        # Reliability: 1 - failure_rate
        failures = sum(1 for r in rows if r.get("status") == "failure")
        reliability = 1.0 - (failures / call_count)

        # Schema stability: 1 - drift_rate
        # drift_detected is stored as 1/0/None integer in SQLite
        drift_rows = sum(1 for r in rows if r.get("drift_detected") == 1)
        schema_stability = 1.0 - (drift_rows / call_count)

        # Latency consistency: 1 - CV (coefficient of variation), clamped to [0, 1]
        latencies = [float(r.get("latency_ms") or 0.0) for r in rows]
        if len(latencies) > 1 and statistics.mean(latencies) > 0:
            cv = statistics.stdev(latencies) / statistics.mean(latencies)
            # CV > 1.0 = very inconsistent; we clamp so score never goes negative
            latency_consistency = max(0.0, 1.0 - min(cv, 1.0))
        else:
            latency_consistency = 1.0

        overall = (
            reliability * _TOOL_WEIGHTS["reliability"]
            + schema_stability * _TOOL_WEIGHTS["schema_stability"]
            + latency_consistency * _TOOL_WEIGHTS["latency_consistency"]
        )
        # DECISION: reliability is a hard floor — a tool with 0% success rate is always
        # graded F regardless of how consistent or drift-free it is. Users should not see
        # a "D" for a completely broken tool.
        if reliability == 0.0:
            overall = 0.0
        overall = round(max(0.0, min(1.0, overall)), 4)

        return ToolQualityScore(
            tool_name=tool_name,
            call_count=call_count,
            reliability_score=round(reliability, 4),
            schema_stability_score=round(schema_stability, 4),
            latency_consistency_score=round(latency_consistency, 4),
            overall_score=overall,
            grade=_grade(overall),
        )

    @staticmethod
    def _score_single_run(
        trace_id: str,
        tool_calls: list[dict[str, Any]],
        llm_calls: list[dict[str, Any]],
    ) -> AgentRunQualityScore:
        tool_count = len(tool_calls)
        llm_count = len(llm_calls)

        # Context efficiency: 1 - peak context utilisation
        utilisation_values = [
            float(r["context_utilisation"])
            for r in llm_calls
            if r.get("context_utilisation") is not None
        ]
        if utilisation_values:
            peak_util = max(utilisation_values)
            context_efficiency = max(0.0, 1.0 - peak_util)
        else:
            context_efficiency = 1.0  # no LLM calls recorded → assume efficient

        # Failure recovery: fraction of failure types that didn't repeat
        # A run that hits a timeout once and recovers is better than one that loops.
        failure_types_seen: list[str] = [
            str(r.get("failure_type") or "")
            for r in tool_calls
            if r.get("status") == "failure" and r.get("failure_type")
        ]
        if failure_types_seen:
            unique_failure_types = len(set(failure_types_seen))
            total_failures = len(failure_types_seen)
            # If failures are diverse (many unique types) the agent hit different problems
            # but didn't repeat the same mistake — better than repeating one type.
            failure_recovery = min(1.0, unique_failure_types / total_failures)
        else:
            failure_recovery = 1.0  # no failures

        # Tool diversity: unique tool names / total tool calls (normalised to [0, 1])
        # A run that uses many different tools is more diverse than one that hammers one.
        # We cap at 1.0 and treat diversity as a mild quality signal.
        if tool_count > 0:
            unique_tools = len({str(r.get("tool_name", "")) for r in tool_calls})
            tool_diversity = min(1.0, unique_tools / max(1, tool_count))
        else:
            tool_diversity = 1.0  # no tool calls → no penalty

        overall = (
            context_efficiency * _RUN_WEIGHTS["context_efficiency"]
            + failure_recovery * _RUN_WEIGHTS["failure_recovery"]
            + tool_diversity * _RUN_WEIGHTS["tool_diversity"]
        )
        overall = round(max(0.0, min(1.0, overall)), 4)

        return AgentRunQualityScore(
            trace_id=trace_id,
            llm_call_count=llm_count,
            tool_call_count=tool_count,
            context_efficiency_score=round(context_efficiency, 4),
            failure_recovery_score=round(failure_recovery, 4),
            tool_diversity_score=round(tool_diversity, 4),
            overall_score=overall,
            grade=_grade(overall),
        )
