"""ReportGenerator — CI quality gate reporter.

Pure functions: no I/O, no async, no framework dependencies.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from anjor.analysis.cost import estimate_cost_usd

_ASSERTION_RE = re.compile(r"^\s*(\w+)\s*(>=|<=|>|<|==)\s*([0-9]*\.?[0-9]+)\s*$")
_VALID_METRICS = {"success_rate", "p95_latency_ms", "failure_count", "total_cost_usd"}


@dataclass(frozen=True)
class AssertionResult:
    expression: str
    passed: bool
    actual: float
    message: str


@dataclass
class ReportData:
    total_calls: int
    success_count: int
    failure_count: int
    success_rate: float
    p95_latency_ms: float
    total_cost_usd: float
    since_minutes: int
    project: str | None
    per_tool: list[dict[str, Any]] = field(default_factory=list)
    per_model: list[dict[str, Any]] = field(default_factory=list)


def _get(obj: Any, key: str, default: Any = 0) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


class ReportGenerator:
    """Generates quality reports and evaluates CI assertions. No I/O."""

    def generate(
        self,
        tools: list[Any],
        llm_models: list[Any],
        since_minutes: int,
        project: str | None,
    ) -> ReportData:
        total_calls = sum(_get(t, "call_count") for t in tools)
        success_count = sum(_get(t, "success_count") for t in tools)
        failure_count = sum(_get(t, "failure_count") for t in tools)
        success_rate = success_count / total_calls if total_calls else 1.0
        p95 = max((_get(t, "p95_latency_ms", 0.0) for t in tools), default=0.0)

        total_cost = sum(
            estimate_cost_usd(
                model=_get(m, "model", ""),
                token_input=_get(m, "total_token_input"),
                token_output=_get(m, "total_token_output"),
                cache_read=_get(m, "total_cache_read"),
                cache_write=_get(m, "total_cache_write"),
            )
            for m in llm_models
        )

        per_tool = [
            {
                "tool_name": _get(t, "tool_name", ""),
                "call_count": _get(t, "call_count"),
                "success_count": _get(t, "success_count"),
                "failure_count": _get(t, "failure_count"),
                "success_rate": (
                    _get(t, "success_count") / _get(t, "call_count")
                    if _get(t, "call_count")
                    else 1.0
                ),
                "p95_latency_ms": _get(t, "p95_latency_ms", 0.0),
            }
            for t in tools
        ]
        per_model = [
            {
                "model": _get(m, "model", ""),
                "call_count": _get(m, "call_count"),
                "total_token_input": _get(m, "total_token_input"),
                "total_token_output": _get(m, "total_token_output"),
            }
            for m in llm_models
        ]

        return ReportData(
            total_calls=total_calls,
            success_count=success_count,
            failure_count=failure_count,
            success_rate=success_rate,
            p95_latency_ms=p95,
            total_cost_usd=total_cost,
            since_minutes=since_minutes,
            project=project,
            per_tool=per_tool,
            per_model=per_model,
        )

    def evaluate_assertions(
        self, expressions: list[str], data: ReportData
    ) -> list[AssertionResult]:
        return [self._evaluate_one(expr, data) for expr in expressions]

    def _evaluate_one(self, expr: str, data: ReportData) -> AssertionResult:
        m = _ASSERTION_RE.match(expr)
        if not m:
            return AssertionResult(
                expression=expr,
                passed=False,
                actual=0.0,
                message=f"invalid assertion syntax: {expr!r}",
            )
        metric, op, threshold_str = m.group(1), m.group(2), m.group(3)
        if metric not in _VALID_METRICS:
            return AssertionResult(
                expression=expr,
                passed=False,
                actual=0.0,
                message=f"unknown metric {metric!r}; valid: {', '.join(sorted(_VALID_METRICS))}",
            )
        threshold = float(threshold_str)
        actual: float = getattr(data, metric)
        ops: dict[str, bool] = {
            ">=": actual >= threshold,
            "<=": actual <= threshold,
            ">": actual > threshold,
            "<": actual < threshold,
            "==": actual == threshold,
        }
        return AssertionResult(
            expression=expr,
            passed=ops[op],
            actual=actual,
            message=f"{metric} {op} {threshold} (actual: {actual:.4g})",
        )

    def format_text(self, data: ReportData, assertions: list[AssertionResult]) -> str:
        window = (
            f"last {data.since_minutes}m"
            if data.since_minutes < 60
            else f"last {data.since_minutes // 60}h"
        )
        proj_tag = f" [{data.project}]" if data.project else ""
        cost_str = (
            f"${data.total_cost_usd:.4f}"
            if data.total_cost_usd < 0.01
            else f"${data.total_cost_usd:.2f}"
        )
        lines = [
            f"anjor report — {window}{proj_tag}",
            "─" * 40,
            f"calls:        {data.total_calls}",
            f"success rate: {data.success_rate:.1%}",
            f"p95 latency:  {data.p95_latency_ms:,.0f} ms",
            f"cost:         {cost_str}",
        ]
        if data.per_tool:
            lines.append("")
            lines.append("per-tool:")
            for t in sorted(data.per_tool, key=lambda x: -x["call_count"]):
                sr = f"{t['success_rate']:.0%}"
                lines.append(
                    f"  {t['tool_name']:<30} {t['call_count']:>4} calls"
                    f"  {sr:>4}  p95: {t['p95_latency_ms']:>7,.0f} ms"
                )
        if assertions:
            lines.append("")
            lines.append("assertions:")
            for a in assertions:
                mark = "✓" if a.passed else "✗"
                lines.append(f"  {mark}  {a.message}")
        return "\n".join(lines)

    def format_json(self, data: ReportData, assertions: list[AssertionResult]) -> str:
        return json.dumps(
            {
                "since_minutes": data.since_minutes,
                "project": data.project,
                "summary": {
                    "total_calls": data.total_calls,
                    "success_count": data.success_count,
                    "failure_count": data.failure_count,
                    "success_rate": round(data.success_rate, 4),
                    "p95_latency_ms": data.p95_latency_ms,
                    "total_cost_usd": round(data.total_cost_usd, 6),
                },
                "per_tool": data.per_tool,
                "per_model": data.per_model,
                "assertions": [
                    {
                        "expression": a.expression,
                        "passed": a.passed,
                        "actual": a.actual,
                        "message": a.message,
                    }
                    for a in assertions
                ],
                "passed": all(a.passed for a in assertions) if assertions else True,
            },
            indent=2,
        )

    def format_markdown(self, data: ReportData, assertions: list[AssertionResult]) -> str:
        window = (
            f"last {data.since_minutes}m"
            if data.since_minutes < 60
            else f"last {data.since_minutes // 60}h"
        )
        proj_tag = f" · {data.project}" if data.project else ""
        cost_str = (
            f"${data.total_cost_usd:.4f}"
            if data.total_cost_usd < 0.01
            else f"${data.total_cost_usd:.2f}"
        )
        lines = [
            f"## Anjor Report — {window}{proj_tag}",
            "",
            "| Metric | Value |",
            "|--------|-------|",
            f"| Calls | {data.total_calls} |",
            f"| Success rate | {data.success_rate:.1%} |",
            f"| p95 latency | {data.p95_latency_ms:,.0f} ms |",
            f"| Cost | {cost_str} |",
        ]
        if data.per_tool:
            lines += [
                "",
                "### Per-tool",
                "",
                "| Tool | Calls | Success | p95 (ms) |",
                "|------|-------|---------|----------|",
            ]
            for t in sorted(data.per_tool, key=lambda x: -x["call_count"]):
                lines.append(
                    f"| `{t['tool_name']}` | {t['call_count']}"
                    f" | {t['success_rate']:.0%} | {t['p95_latency_ms']:,.0f} |"
                )
        if assertions:
            lines += [
                "",
                "### Assertions",
                "",
                "| Assertion | Result |",
                "|-----------|--------|",
            ]
            for a in assertions:
                mark = "✅" if a.passed else "❌"
                lines.append(f"| `{a.expression}` | {mark} {a.message} |")
        return "\n".join(lines)
