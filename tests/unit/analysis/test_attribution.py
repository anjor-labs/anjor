"""Unit tests for AttributionAnalyser."""

from __future__ import annotations

import uuid

from anjor.analysis.tracing.attribution import AttributionAnalyser


def span(
    agent_name: str = "agent",
    token_input: int = 100,
    token_output: int = 50,
    tool_calls_count: int = 1,
    llm_calls_count: int = 1,
    status: str = "ok",
) -> dict:
    return {
        "span_id": str(uuid.uuid4()),
        "agent_name": agent_name,
        "token_input": token_input,
        "token_output": token_output,
        "tool_calls_count": tool_calls_count,
        "llm_calls_count": llm_calls_count,
        "status": status,
    }


class TestAttributionAnalyser:
    def test_empty_returns_empty(self) -> None:
        assert AttributionAnalyser().analyse([]) == []

    def test_single_agent_100_pct(self) -> None:
        results = AttributionAnalyser().analyse([span("solo", 400, 200)])
        assert len(results) == 1
        a = results[0]
        assert a.agent_name == "solo"
        assert a.token_input == 400
        assert a.token_output == 200
        assert a.token_total == 600
        assert a.token_share_pct == 100.0

    def test_two_agents_equal_tokens(self) -> None:
        spans = [span("a", 100, 0), span("b", 100, 0)]
        results = AttributionAnalyser().analyse(spans)
        assert len(results) == 2
        shares = {r.agent_name: r.token_share_pct for r in results}
        assert shares["a"] == 50.0
        assert shares["b"] == 50.0

    def test_sorted_by_token_total_desc(self) -> None:
        spans = [
            span("small", 10, 0),
            span("large", 500, 0),
            span("medium", 100, 0),
        ]
        results = AttributionAnalyser().analyse(spans)
        assert [r.agent_name for r in results] == ["large", "medium", "small"]

    def test_failure_rate_computed(self) -> None:
        spans = [
            span("agent", status="ok"),
            span("agent", status="error"),
            span("agent", status="error"),
        ]
        results = AttributionAnalyser().analyse(spans)
        assert len(results) == 1
        assert results[0].failure_count == 2
        assert results[0].failure_rate == pytest.approx(2 / 3, abs=0.001)

    def test_no_failures(self) -> None:
        results = AttributionAnalyser().analyse([span("clean", status="ok")])
        assert results[0].failure_count == 0
        assert results[0].failure_rate == 0.0

    def test_span_count_aggregated(self) -> None:
        spans = [span("a"), span("a"), span("a")]
        results = AttributionAnalyser().analyse(spans)
        assert results[0].span_count == 3

    def test_tool_and_llm_counts_aggregated(self) -> None:
        spans = [
            span("agent", tool_calls_count=3, llm_calls_count=2),
            span("agent", tool_calls_count=1, llm_calls_count=4),
        ]
        results = AttributionAnalyser().analyse(spans)
        assert results[0].tool_calls_count == 4
        assert results[0].llm_calls_count == 6

    def test_zero_tokens_share(self) -> None:
        spans = [span("a", 0, 0), span("b", 0, 0)]
        results = AttributionAnalyser().analyse(spans)
        for r in results:
            assert r.token_share_pct == 0.0

    def test_multiple_agents_token_share_sums_to_100(self) -> None:
        spans = [span(f"agent_{i}", token_input=i * 100, token_output=50) for i in range(1, 5)]
        results = AttributionAnalyser().analyse(spans)
        total_share = sum(r.token_share_pct for r in results)
        assert abs(total_share - 100.0) < 0.01


import pytest  # noqa: E402 — needed for pytest.approx above
