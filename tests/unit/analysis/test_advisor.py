"""Unit tests for SessionAdvisor and cost estimation."""

from __future__ import annotations

import pytest

from anjor.analysis.advisor import (
    SessionAdvisor,
    _budget_insights,
    _context_insights,
    _tool_failure_insights,
)
from anjor.analysis.cost import estimate_cost_usd, _get_price


# ── cost.py ───────────────────────────────────────────────────────────────────


def test_estimate_cost_known_model():
    cost = estimate_cost_usd("claude-sonnet-4-6", token_input=1_000_000, token_output=0)
    assert abs(cost - 3.00) < 1e-6


def test_estimate_cost_output():
    cost = estimate_cost_usd("claude-sonnet-4-6", token_input=0, token_output=1_000_000)
    assert abs(cost - 15.00) < 1e-6


def test_estimate_cost_cache_read():
    cost = estimate_cost_usd(
        "claude-sonnet-4-6", token_input=0, token_output=0, cache_read=1_000_000
    )
    assert abs(cost - 0.30) < 1e-6


def test_estimate_cost_zero():
    assert estimate_cost_usd("claude-sonnet-4-6", 0, 0) == 0.0


def test_estimate_cost_unknown_model_uses_default():
    cost = estimate_cost_usd("unknown-model-xyz", token_input=1_000_000, token_output=0)
    assert cost == pytest.approx(3.00)


def test_estimate_cost_prefix_match():
    # claude-haiku-4-5-20251001 exact match should work
    cost = estimate_cost_usd("claude-haiku-4-5-20251001", token_input=1_000_000, token_output=0)
    assert abs(cost - 0.80) < 1e-6


def test_get_price_exact():
    prices = _get_price("gpt-4o")
    assert prices[0] == 2.50  # input price


def test_get_price_prefix():
    # a versioned name should hit prefix fallback
    prices = _get_price("claude-sonnet-4-6-20260101")
    assert prices[0] == 3.00


# ── _tool_failure_insights ─────────────────────────────────────────────────────


def _tool(name: str, call_count: int, failure_count: int) -> dict:
    return {
        "tool_name": name,
        "call_count": call_count,
        "failure_count": failure_count,
        "success_rate": (call_count - failure_count) / call_count if call_count else 1.0,
        "avg_latency_ms": 100.0,
    }


def test_no_insight_below_threshold():
    tools = [_tool("bash", 10, 1)]  # 10% failure — below 20%
    assert _tool_failure_insights(tools) == []


def test_warn_at_20pct():
    tools = [_tool("web_search", 10, 2)]  # 20%
    ins = _tool_failure_insights(tools)
    assert len(ins) == 1
    assert ins[0].severity == "warn"
    assert "web_search" in ins[0].message


def test_error_at_40pct():
    tools = [_tool("bash", 10, 4)]  # 40%
    ins = _tool_failure_insights(tools)
    assert ins[0].severity == "error"


def test_skips_low_call_count():
    tools = [_tool("rare_tool", 2, 2)]  # 100% but only 2 calls
    assert _tool_failure_insights(tools) == []


def test_multiple_tools():
    tools = [_tool("good", 100, 5), _tool("bad", 10, 3)]
    ins = _tool_failure_insights(tools)
    assert len(ins) == 1
    assert ins[0].affected_tool == "bad"


# ── _context_insights ─────────────────────────────────────────────────────────


def _llm(
    model: str, call_count: int, avg_ctx: float, total_in: int = 0, total_out: int = 0
) -> dict:
    return {
        "model": model,
        "call_count": call_count,
        "avg_context_utilisation": avg_ctx,
        "total_token_input": total_in,
        "total_token_output": total_out,
        "total_cache_read": 0,
        "total_cache_write": 0,
    }


def test_no_context_insight_below_threshold():
    assert _context_insights([_llm("claude-sonnet-4-6", 5, 0.50)]) == []


def test_context_warn():
    ins = _context_insights([_llm("claude-sonnet-4-6", 5, 0.85)])
    assert len(ins) == 1
    assert ins[0].severity == "warn"
    assert "85%" in ins[0].message


def test_context_error():
    ins = _context_insights([_llm("claude-sonnet-4-6", 5, 0.92)])
    assert ins[0].severity == "error"


def test_empty_llm_models():
    assert _context_insights([]) == []


def test_weighted_average_across_models():
    models = [
        _llm("claude-sonnet-4-6", 10, 0.90),
        _llm("claude-haiku-4-5", 10, 0.70),
    ]
    # weighted avg = (0.90*10 + 0.70*10) / 20 = 0.80 → warn threshold exactly
    ins = _context_insights(models)
    assert len(ins) == 1
    assert ins[0].severity == "warn"


# ── _budget_insights ──────────────────────────────────────────────────────────


def test_budget_ok():
    # $0.003 of $10 budget — well under
    models = [_llm("claude-sonnet-4-6", 1, 0.5, total_in=1000, total_out=0)]
    assert _budget_insights(models, budget_usd=10.0) == []


def test_budget_warn():
    # consume 85% of a tiny $0.01 budget
    models = [_llm("claude-sonnet-4-6", 1, 0.5, total_in=2_833, total_out=0)]
    ins = _budget_insights(models, budget_usd=0.01)
    # $0.0085 ≈ 85% of $0.01 — should warn
    assert len(ins) == 1
    assert ins[0].severity == "warn"


def test_budget_exceeded():
    # 1M input tokens at $3/M = $3; budget = $1
    models = [_llm("claude-sonnet-4-6", 10, 0.5, total_in=1_000_000, total_out=0)]
    ins = _budget_insights(models, budget_usd=1.0)
    assert ins[0].severity == "error"
    assert "exceeded" in ins[0].message


# ── SessionAdvisor ────────────────────────────────────────────────────────────


class TestSessionAdvisor:
    def setup_method(self) -> None:
        self.advisor = SessionAdvisor()

    def test_empty_data_returns_no_insights(self):
        assert self.advisor.analyse([], []) == []

    def test_healthy_session_no_insights(self):
        tools = [_tool("bash", 100, 5)]
        llm = [_llm("claude-sonnet-4-6", 10, 0.5)]
        assert self.advisor.analyse(tools, llm) == []

    def test_errors_sorted_before_warns(self):
        tools = [_tool("a", 10, 4), _tool("b", 10, 2)]  # error + warn
        ins = self.advisor.analyse(tools, [])
        assert ins[0].severity == "error"
        assert ins[1].severity == "warn"

    def test_budget_no_overage(self):
        llm = [_llm("claude-sonnet-4-6", 1, 0.3, total_in=100, total_out=100)]
        ins = self.advisor.analyse([], llm, budget_usd=100.0)
        assert ins == []

    def test_format_summary_healthy(self):
        tools = [_tool("bash", 10, 0)]
        llm = [_llm("claude-sonnet-4-6", 5, 0.30, total_in=5000, total_out=1000)]
        ins = self.advisor.analyse(tools, llm)
        out = self.advisor.format_summary(tools, llm, since_minutes=120, insights=ins)
        assert "last 2h" in out
        assert "10 calls" in out
        assert "0% failure" in out

    def test_format_summary_with_insight(self):
        tools = [_tool("web_search", 10, 3)]
        ins = self.advisor.analyse(tools, [])
        out = self.advisor.format_summary(tools, [], since_minutes=60, insights=ins)
        assert "⚠" in out
        assert "web_search" in out

    def test_format_summary_window_label_minutes(self):
        out = self.advisor.format_summary([], [], since_minutes=45, insights=[])
        assert "last 45m" in out

    def test_format_summary_window_label_hours(self):
        out = self.advisor.format_summary([], [], since_minutes=120, insights=[])
        assert "last 2h" in out
