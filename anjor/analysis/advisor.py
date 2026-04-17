"""SessionAdvisor — generates actionable insights from time-windowed event summaries.

Pure function: no I/O, no async, no framework dependencies.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

Severity = str  # "info" | "warn" | "error"

_FAILURE_RATE_WARN = 0.20
_FAILURE_RATE_ERROR = 0.40
_CONTEXT_WARN = 0.80
_CONTEXT_ERROR = 0.90
_MIN_CALLS_FOR_INSIGHT = 3  # ignore tools with fewer calls (noisy)
_BUDGET_WARN_FRACTION = 0.80


@dataclass(frozen=True)
class Insight:
    severity: Severity
    message: str
    affected_tool: str | None = None


class SessionAdvisor:
    """Analyses filtered event summaries; returns insights. Silent when healthy."""

    def analyse(
        self,
        tools: list[dict[str, Any]],
        llm_models: list[dict[str, Any]],
        budget_usd: float | None = None,
    ) -> list[Insight]:
        """Return insights sorted by severity. Empty list when everything is healthy."""
        insights: list[Insight] = []
        insights.extend(_tool_failure_insights(tools))
        insights.extend(_context_insights(llm_models))
        if budget_usd is not None:
            insights.extend(_budget_insights(llm_models, budget_usd))
        # error first, then warn, then info
        order = {"error": 0, "warn": 1, "info": 2}
        return sorted(insights, key=lambda i: order.get(i.severity, 9))

    def format_summary(
        self,
        tools: list[dict[str, Any]],
        llm_models: list[dict[str, Any]],
        since_minutes: int,
        insights: list[Insight],
    ) -> str:
        """Return a human-readable status string with inline insights."""
        total_calls = sum(t.get("call_count", 0) for t in tools)
        failure_count = sum(t.get("failure_count", 0) for t in tools)
        failure_pct = int(failure_count / total_calls * 100) if total_calls else 0

        from anjor.analysis.cost import estimate_cost_usd

        total_cost = sum(
            estimate_cost_usd(
                model=m.get("model", ""),
                token_input=m.get("total_token_input", 0),
                token_output=m.get("total_token_output", 0),
                cache_read=m.get("total_cache_read", 0),
                cache_write=m.get("total_cache_write", 0),
            )
            for m in llm_models
        )

        total_llm_calls = sum(m.get("call_count", 0) for m in llm_models)
        avg_ctx: float = 0.0
        if total_llm_calls:
            avg_ctx = (
                sum(
                    m.get("avg_context_utilisation", 0.0) * m.get("call_count", 0)
                    for m in llm_models
                )
                / total_llm_calls
            )

        if since_minutes < 60:
            window_label = f"last {since_minutes}m"
        else:
            window_label = f"last {since_minutes // 60}h"
        cost_str = f"${total_cost:.4f}" if total_cost < 0.01 else f"${total_cost:.2f}"
        ctx_str = f"{int(avg_ctx * 100)}% ctx" if avg_ctx > 0 else ""

        parts = [f"{window_label}: {total_calls} calls · {failure_pct}% failure · {cost_str}"]
        if ctx_str:
            parts[0] += f" · {ctx_str}"

        lines = [parts[0]]
        for ins in insights:
            prefix = "⚠ " if ins.severity == "warn" else "✗ " if ins.severity == "error" else "· "
            lines.append(f"{prefix} {ins.message}")

        return "\n".join(lines)


# ── Pure helper functions ──────────────────────────────────────────────────────


def _tool_failure_insights(tools: list[dict[str, Any]]) -> list[Insight]:
    insights = []
    for t in tools:
        call_count = t.get("call_count", 0)
        if call_count < _MIN_CALLS_FOR_INSIGHT:
            continue
        failure_count = t.get("failure_count", 0)
        rate = failure_count / call_count
        if rate < _FAILURE_RATE_WARN:
            continue
        pct = int(rate * 100)
        severity: Severity = "error" if rate >= _FAILURE_RATE_ERROR else "warn"
        insights.append(
            Insight(
                severity=severity,
                message=(
                    f"{t['tool_name']} has a {pct}% failure rate"
                    f" ({failure_count}/{call_count} calls)"
                ),
                affected_tool=t["tool_name"],
            )
        )
    return insights


def _context_insights(llm_models: list[dict[str, Any]]) -> list[Insight]:
    total_calls = sum(m.get("call_count", 0) for m in llm_models)
    if not total_calls:
        return []
    avg_util = (
        sum(m.get("avg_context_utilisation", 0.0) * m.get("call_count", 0) for m in llm_models)
        / total_calls
    )
    pct = int(avg_util * 100)
    if avg_util >= _CONTEXT_ERROR:
        return [
            Insight(
                severity="error",
                message=(
                    f"Context at {pct}% — approaching limit."
                    " Consider compressing outputs or starting a new session."
                ),
            )
        ]
    if avg_util >= _CONTEXT_WARN:
        return [Insight(severity="warn", message=f"Context at {pct}%")]
    return []


def _budget_insights(llm_models: list[dict[str, Any]], budget_usd: float) -> list[Insight]:
    from anjor.analysis.cost import estimate_cost_usd

    total_cost = sum(
        estimate_cost_usd(
            model=m.get("model", ""),
            token_input=m.get("total_token_input", 0),
            token_output=m.get("total_token_output", 0),
            cache_read=m.get("total_cache_read", 0),
            cache_write=m.get("total_cache_write", 0),
        )
        for m in llm_models
    )
    if total_cost >= budget_usd:
        return [
            Insight(
                severity="error",
                message=f"Budget exceeded: ${total_cost:.2f} of ${budget_usd:.2f} limit",
            )
        ]
    if total_cost >= budget_usd * _BUDGET_WARN_FRACTION:
        pct_used = int(total_cost / budget_usd * 100)
        return [
            Insight(
                severity="warn",
                message=f"Budget at {pct_used}%: ${total_cost:.2f} of ${budget_usd:.2f}",
            )
        ]
    return []
