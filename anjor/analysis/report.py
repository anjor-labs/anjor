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


# ---------------------------------------------------------------------------
# DiffReport — rolling-window regression detection
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class WindowMetrics:
    call_count: int
    success_rate: float
    failure_count: int
    p50_latency_ms: float
    p95_latency_ms: float
    avg_token_input: float = 0.0


@dataclass(frozen=True)
class ToolDiff:
    tool_name: str
    current: WindowMetrics
    prior: WindowMetrics


@dataclass
class DiffData:
    window_minutes: int
    project: str | None
    tools: list[ToolDiff]
    overall_current: WindowMetrics
    overall_prior: WindowMetrics


def _percentile(data: list[float], p: float) -> float:
    if not data:
        return 0.0
    idx = int(len(data) * p / 100)
    return data[min(idx, len(data) - 1)]


def _compute_window_metrics(
    rows: list[dict[str, Any]], avg_token_input: float = 0.0
) -> WindowMetrics:
    call_count = len(rows)
    if not call_count:
        return WindowMetrics(
            call_count=0,
            success_rate=0.0,
            failure_count=0,
            p50_latency_ms=0.0,
            p95_latency_ms=0.0,
            avg_token_input=avg_token_input,
        )
    success_count = sum(1 for r in rows if r.get("status") == "success")
    latencies = sorted(float(r.get("latency_ms", 0.0)) for r in rows)
    return WindowMetrics(
        call_count=call_count,
        success_rate=success_count / call_count,
        failure_count=call_count - success_count,
        p50_latency_ms=_percentile(latencies, 50),
        p95_latency_ms=_percentile(latencies, 95),
        avg_token_input=avg_token_input,
    )


def _direction(current: float, prior: float, higher_is_better: bool) -> str:
    """Return ↑/↓/= based on change and metric direction."""
    if current == prior:
        return "="
    improved = (current > prior) if higher_is_better else (current < prior)
    return "↑" if improved else "↓"


class DiffReport:
    """Generates rolling-window regression diffs. No I/O."""

    def generate(
        self,
        current_rows: list[dict[str, Any]],
        prior_rows: list[dict[str, Any]],
        window_minutes: int,
        project: str | None,
        current_avg_token_input: float = 0.0,
        prior_avg_token_input: float = 0.0,
    ) -> DiffData:
        # Group by tool_name
        def _group(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
            out: dict[str, list[dict[str, Any]]] = {}
            for r in rows:
                out.setdefault(r["tool_name"], []).append(r)
            return out

        cur_by_tool = _group(current_rows)
        pri_by_tool = _group(prior_rows)
        all_tools = sorted(cur_by_tool.keys() | pri_by_tool.keys())

        tool_diffs = [
            ToolDiff(
                tool_name=t,
                current=_compute_window_metrics(cur_by_tool.get(t, [])),
                prior=_compute_window_metrics(pri_by_tool.get(t, [])),
            )
            for t in all_tools
        ]

        overall_current = _compute_window_metrics(current_rows, current_avg_token_input)
        overall_prior = _compute_window_metrics(prior_rows, prior_avg_token_input)

        return DiffData(
            window_minutes=window_minutes,
            project=project,
            tools=tool_diffs,
            overall_current=overall_current,
            overall_prior=overall_prior,
        )

    def _window_label(self, minutes: int) -> str:
        if minutes < 60:
            return f"{minutes}m"
        if minutes % 1440 == 0:
            return f"{minutes // 1440}d"
        return f"{minutes // 60}h"

    def format_text(self, data: DiffData) -> str:
        wl = self._window_label(data.window_minutes)
        proj_tag = f" [{data.project}]" if data.project else ""
        lines = [
            f"anjor diff — last {wl} vs prior {wl}{proj_tag}",
            "─" * 68,
            f"{'tool':<28}  {'success_rate':^18}  {'p95_ms':^16}  {'failures':^12}",
            "─" * 68,
        ]
        for td in data.tools:
            lines.append(self._tool_row(td.tool_name, td.current, td.prior))
        lines.append("─" * 68)
        lines.append(
            self._tool_row(
                f"overall ({len(data.tools)} tools)",
                data.overall_current,
                data.overall_prior,
            )
        )
        if data.overall_current.avg_token_input or data.overall_prior.avg_token_input:
            d = _direction(
                data.overall_current.avg_token_input,
                data.overall_prior.avg_token_input,
                higher_is_better=False,
            )
            lines.append(
                f"  avg tokens/llm call:"
                f" {data.overall_prior.avg_token_input:.0f}"
                f" → {data.overall_current.avg_token_input:.0f}  {d}"
            )
        return "\n".join(lines)

    def _tool_row(self, name: str, cur: WindowMetrics, pri: WindowMetrics) -> str:
        sr_d = _direction(cur.success_rate, pri.success_rate, higher_is_better=True)
        p95_d = _direction(cur.p95_latency_ms, pri.p95_latency_ms, higher_is_better=False)
        fc_d = _direction(cur.failure_count, pri.failure_count, higher_is_better=False)
        sr = f"{pri.success_rate:.0%}→{cur.success_rate:.0%} {sr_d}"
        p95 = f"{pri.p95_latency_ms:.0f}→{cur.p95_latency_ms:.0f} {p95_d}"
        fc = f"{pri.failure_count}→{cur.failure_count} {fc_d}"
        return f"  {name:<26}  {sr:^18}  {p95:^16}  {fc:^12}"

    def format_json(self, data: DiffData) -> str:
        def _metrics(m: WindowMetrics) -> dict[str, Any]:
            return {
                "call_count": m.call_count,
                "success_rate": round(m.success_rate, 4),
                "failure_count": m.failure_count,
                "p50_latency_ms": m.p50_latency_ms,
                "p95_latency_ms": m.p95_latency_ms,
                "avg_token_input": m.avg_token_input,
            }

        return json.dumps(
            {
                "window_minutes": data.window_minutes,
                "project": data.project,
                "overall": {
                    "current": _metrics(data.overall_current),
                    "prior": _metrics(data.overall_prior),
                },
                "tools": [
                    {
                        "tool_name": td.tool_name,
                        "current": _metrics(td.current),
                        "prior": _metrics(td.prior),
                    }
                    for td in data.tools
                ],
            },
            indent=2,
        )

    def format_markdown(self, data: DiffData) -> str:
        wl = self._window_label(data.window_minutes)
        proj_tag = f" · {data.project}" if data.project else ""
        lines = [
            f"## Anjor Diff — last {wl} vs prior {wl}{proj_tag}",
            "",
            "| Tool | Success rate | p95 latency | Failures |",
            "|------|-------------|-------------|----------|",
        ]
        for td in data.tools:
            sr_d = _direction(td.current.success_rate, td.prior.success_rate, True)
            p95_d = _direction(td.current.p95_latency_ms, td.prior.p95_latency_ms, False)
            fc_d = _direction(td.current.failure_count, td.prior.failure_count, False)
            lines.append(
                f"| `{td.tool_name}` |"
                f" {td.prior.success_rate:.0%} → {td.current.success_rate:.0%} {sr_d} |"
                f" {td.prior.p95_latency_ms:.0f} → {td.current.p95_latency_ms:.0f} ms {p95_d} |"
                f" {td.prior.failure_count} → {td.current.failure_count} {fc_d} |"
            )
        oc, op = data.overall_current, data.overall_prior
        sr_d = _direction(oc.success_rate, op.success_rate, True)
        p95_d = _direction(oc.p95_latency_ms, op.p95_latency_ms, False)
        fc_d = _direction(oc.failure_count, op.failure_count, False)
        lines += [
            "|------|-------------|-------------|----------|",
            f"| **overall** |"
            f" {op.success_rate:.0%} → {oc.success_rate:.0%} {sr_d} |"
            f" {op.p95_latency_ms:.0f} → {oc.p95_latency_ms:.0f} ms {p95_d} |"
            f" {op.failure_count} → {oc.failure_count} {fc_d} |",
        ]
        return "\n".join(lines)
