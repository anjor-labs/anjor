"""RootCauseAdvisor — automated hypothesis generation from observability data.

Phase 8 intelligence: move from passive cluster reporting to active root-cause
reasoning. Given failure clusters, tool summaries, and LLM summaries, the
advisor generates ranked hypotheses with evidence and concrete next steps.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from anjor.analysis.base import BaseAnalyser

_CONFIDENCE_ORDER = {"high": 0, "medium": 1, "low": 2}


@dataclass
class Hypothesis:
    """A single root-cause hypothesis with supporting evidence and a recommended action."""

    title: str
    evidence: str
    confidence: str  # "high" | "medium" | "low"
    action: str
    # Internal field used for secondary sort; not exposed in the public API but
    # must be carried so the sort key works without reaching back into raw data.
    _occurrence_count: int = 0

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, Hypothesis):
            return NotImplemented
        return self.title == other.title and self.evidence == other.evidence

    def __hash__(self) -> int:
        return hash((self.title, self.evidence))


class RootCauseAdvisor(BaseAnalyser):
    """Generates root-cause hypotheses from pre-aggregated observability summaries.

    Input: (clusters, tool_summaries, llm_summaries) — all pre-aggregated dicts.
    Output: list[Hypothesis] sorted by confidence desc, then occurrence_count desc.
    """

    def analyse(
        self,
        data: tuple[
            list[dict[str, Any]],
            list[dict[str, Any]],
            list[dict[str, Any]],
        ],
    ) -> list[Hypothesis]:
        clusters, tool_summaries, llm_summaries = data
        return self.generate(clusters, tool_summaries, llm_summaries)

    def generate(
        self,
        clusters: list[dict[str, Any]],
        tool_summaries: list[dict[str, Any]],
        llm_summaries: list[dict[str, Any]],
    ) -> list[Hypothesis]:
        """Check all hypothesis rules and return deduplicated, sorted results."""
        seen: set[str] = set()
        results: list[Hypothesis] = []

        def _add(h: Hypothesis) -> None:
            if h.title not in seen:
                seen.add(h.title)
                results.append(h)

        for h in self._check_context_overload(clusters, llm_summaries):
            _add(h)
        for h in self._check_timeout_pattern(clusters):
            _add(h)
        for h in self._check_schema_drift_failure(tool_summaries):
            _add(h)
        for h in self._check_dominant_failure_tool(clusters):
            _add(h)
        for h in self._check_high_latency_variance(tool_summaries):
            _add(h)
        for h in self._check_retry_storm(clusters, tool_summaries):
            _add(h)

        return sorted(
            results,
            key=lambda h: (_CONFIDENCE_ORDER.get(h.confidence, 99), -h._occurrence_count),
        )

    # ------------------------------------------------------------------
    # Rule implementations
    # ------------------------------------------------------------------

    @staticmethod
    def _check_context_overload(
        clusters: list[dict[str, Any]],
        llm_summaries: list[dict[str, Any]],
    ) -> list[Hypothesis]:
        total_failures = sum(int(c.get("occurrence_count", 0)) for c in clusters)
        if total_failures == 0:
            return []

        overloaded = [
            s for s in llm_summaries if float(s.get("avg_context_utilisation", 0.0)) > 0.75
        ]
        if not overloaded:
            return []

        worst = max(overloaded, key=lambda s: float(s.get("avg_context_utilisation", 0.0)))
        util_pct = int(float(worst.get("avg_context_utilisation", 0.0)) * 100)
        model = worst.get("model", "unknown")

        return [
            Hypothesis(
                title="Context window pressure",
                evidence=(
                    f"{model} is operating at {util_pct}% average context utilisation "
                    f"while {total_failures} tool failure(s) are present."
                ),
                confidence="medium",
                action=(
                    "Agent is operating near context limit; failures may be caused by "
                    "truncated tool outputs or degraded reasoning."
                ),
                _occurrence_count=total_failures,
            )
        ]

    @staticmethod
    def _check_timeout_pattern(clusters: list[dict[str, Any]]) -> list[Hypothesis]:
        results: list[Hypothesis] = []
        for c in clusters:
            if str(c.get("failure_type", "")).lower() != "timeout":
                continue
            rate = float(c.get("failure_rate", 0.0))
            if rate <= 0.1:
                continue
            tool = c.get("tool_name", "unknown")
            count = int(c.get("occurrence_count", 0))
            pct = int(rate * 100)
            results.append(
                Hypothesis(
                    title=f"Timeout pattern on {tool}",
                    evidence=(f"{tool} timed out {count} time(s) — {pct}% failure rate."),
                    confidence="high",
                    action=(
                        "Timeout failures suggest the upstream service is slow or rate-limiting."
                    ),
                    _occurrence_count=count,
                )
            )
        return results

    @staticmethod
    def _check_schema_drift_failure(tool_summaries: list[dict[str, Any]]) -> list[Hypothesis]:
        results: list[Hypothesis] = []
        for s in tool_summaries:
            drift_rate = float(s.get("drift_rate", 0.0))
            success_rate = float(s.get("success_rate", 1.0))
            if drift_rate <= 0.1 or success_rate >= 0.9:
                continue
            tool = s.get("tool_name", "unknown")
            drift_pct = int(drift_rate * 100)
            fail_pct = int((1.0 - success_rate) * 100)
            call_count = int(s.get("call_count", 0))
            results.append(
                Hypothesis(
                    title=f"Schema drift causing failures on {tool}",
                    evidence=(
                        f"{tool} has {drift_pct}% drift rate and {fail_pct}% failure "
                        f"rate across {call_count} call(s)."
                    ),
                    confidence="high",
                    action=(
                        "Schema instability is likely causing failures — the tool's "
                        "input/output structure is changing between calls."
                    ),
                    _occurrence_count=call_count,
                )
            )
        return results

    @staticmethod
    def _check_dominant_failure_tool(clusters: list[dict[str, Any]]) -> list[Hypothesis]:
        total_failures = sum(int(c.get("occurrence_count", 0)) for c in clusters)
        if total_failures == 0:
            return []

        # Aggregate per-tool failure counts (a tool may have multiple clusters)
        by_tool: dict[str, int] = {}
        for c in clusters:
            tool = str(c.get("tool_name", "unknown"))
            by_tool[tool] = by_tool.get(tool, 0) + int(c.get("occurrence_count", 0))

        top_tool, top_count = max(by_tool.items(), key=lambda kv: kv[1])
        fraction = top_count / total_failures
        if fraction <= 0.5:
            return []

        pct = int(fraction * 100)
        return [
            Hypothesis(
                title=f"{top_tool} dominates failures",
                evidence=(
                    f"{top_tool} accounts for {top_count} of {total_failures} total "
                    f"failures ({pct}%)."
                ),
                confidence="high",
                action=(
                    f"{top_tool} is the dominant failure source — fixing it would "
                    "eliminate the majority of agent errors."
                ),
                _occurrence_count=top_count,
            )
        ]

    @staticmethod
    def _check_high_latency_variance(tool_summaries: list[dict[str, Any]]) -> list[Hypothesis]:
        results: list[Hypothesis] = []
        for s in tool_summaries:
            call_count = int(s.get("call_count", 0))
            if call_count < 5:
                continue
            avg = float(s.get("avg_latency_ms", 0.0))
            p95 = float(s.get("p95_latency_ms", 0.0))
            if avg <= 0.0:
                continue
            ratio = p95 / avg
            if ratio <= 3.0:
                continue
            tool = s.get("tool_name", "unknown")
            ratio_rounded = round(ratio, 1)
            results.append(
                Hypothesis(
                    title=f"High latency variance on {tool}",
                    evidence=(
                        f"{tool} p95 latency is {ratio_rounded}x its average "
                        f"(p95={p95:.0f}ms, avg={avg:.0f}ms) over {call_count} calls."
                    ),
                    confidence="medium",
                    action=(
                        f"{tool} shows high latency variance (p95 is {ratio_rounded}x "
                        "the average), suggesting intermittent external dependency issues."
                    ),
                    _occurrence_count=call_count,
                )
            )
        return results

    @staticmethod
    def _check_retry_storm(
        clusters: list[dict[str, Any]],
        tool_summaries: list[dict[str, Any]],
    ) -> list[Hypothesis]:
        if not tool_summaries or not clusters:
            return []

        total_unique_tools = len({str(s.get("tool_name", "")) for s in tool_summaries})
        if total_unique_tools == 0:
            return []

        # Find the top failure tool by occurrence count
        by_tool: dict[str, int] = {}
        for c in clusters:
            tool = str(c.get("tool_name", "unknown"))
            by_tool[tool] = by_tool.get(tool, 0) + int(c.get("occurrence_count", 0))

        if not by_tool:
            return []
        top_failure_tool = max(by_tool, key=lambda t: by_tool[t])

        results: list[Hypothesis] = []
        for s in tool_summaries:
            tool = str(s.get("tool_name", "unknown"))
            call_count = int(s.get("call_count", 0))
            if call_count / total_unique_tools <= 5:
                continue
            if tool != top_failure_tool:
                continue
            failure_count = by_tool.get(tool, 0)
            ratio = round(call_count / total_unique_tools, 1)
            results.append(
                Hypothesis(
                    title=f"Possible retry storm on {tool}",
                    evidence=(
                        f"{tool} has {call_count} calls ({ratio}x the per-tool average) "
                        f"and {failure_count} failure(s)."
                    ),
                    confidence="low",
                    action=(
                        f"{tool} is called disproportionately often and fails frequently "
                        "— the agent may be in a retry loop."
                    ),
                    _occurrence_count=call_count,
                )
            )
        return results
