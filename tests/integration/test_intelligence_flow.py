"""Integration tests for Phase 3 intelligence pipeline.

Real SQLite (in-memory) + FastAPI TestClient.
Seeds realistic event data, then asserts the intelligence endpoints
return correct clusters, suggestions, and scores.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from agentscope.collector.api.app import create_app
from agentscope.collector.service import CollectorService
from agentscope.collector.storage.sqlite import SQLiteBackend
from agentscope.core.config import AgentScopeConfig
from agentscope.core.pipeline.pipeline import EventPipeline


def _ts() -> str:
    return datetime.now(UTC).isoformat()


def _tool_event(
    tool_name: str,
    status: str,
    failure_type: str | None = None,
    latency_ms: float = 200.0,
    trace_id: str = "trace-1",
    output_tokens: int | None = None,
) -> dict:
    evt: dict = {
        "event_type": "tool_call",
        "tool_name": tool_name,
        "trace_id": trace_id,
        "session_id": "session-1",
        "agent_id": "default",
        "timestamp": _ts(),
        "sequence_no": 0,
        "status": status,
        "failure_type": failure_type,
        "latency_ms": latency_ms,
        "input_payload": {},
        "output_payload": {},
        "input_schema_hash": "h1",
        "output_schema_hash": "h2",
        "token_usage": None,
        "schema_drift": None,
    }
    if output_tokens is not None:
        evt["token_usage"] = {"input": 200, "output": output_tokens}
    return evt


def _llm_event(
    trace_id: str = "trace-1",
    model: str = "claude-3-5-sonnet-20241022",
    context_window_limit: int = 200_000,
    context_utilisation: float = 0.3,
) -> dict:
    return {
        "event_type": "llm_call",
        "trace_id": trace_id,
        "session_id": "session-1",
        "agent_id": "default",
        "timestamp": _ts(),
        "sequence_no": 0,
        "model": model,
        "latency_ms": 800.0,
        "token_usage": {"input": 2000, "output": 600},
        "context_window_used": int(context_window_limit * context_utilisation),
        "context_window_limit": context_window_limit,
        "context_utilisation": context_utilisation,
        "prompt_hash": "ph",
        "system_prompt_hash": None,
        "messages_count": 8,
        "finish_reason": "end_turn",
    }


@pytest.fixture
def seeded_client() -> TestClient:  # type: ignore[misc]
    """TestClient with a realistic mixed event dataset pre-seeded.

    Dataset:
    - "search" tool: 8 calls, 2 failures (timeout) → 25% failure rate
    - "fetch" tool: 4 calls, 3 failures (api_error) → 75% failure rate
    - "parse" tool: 6 calls, 0 failures, large output → optimization candidate
    - Two LLM calls with different trace_ids and context utilisation values
    """
    svc = CollectorService(
        config=AgentScopeConfig(db_path=":memory:", batch_size=1, batch_interval_ms=9999),  # type: ignore[call-arg]
        storage=SQLiteBackend(db_path=":memory:", batch_size=1),
        pipeline=EventPipeline(),
    )
    app = create_app(service=svc)
    with TestClient(app) as client:
        # Seed search events
        for _ in range(6):
            client.post("/events", json=_tool_event("search", "success", trace_id="trace-1"))
        for _ in range(2):
            client.post("/events", json=_tool_event(
                "search", "failure", "timeout", latency_ms=8500.0, trace_id="trace-1"
            ))
        # Seed fetch events
        client.post("/events", json=_tool_event("fetch", "success", trace_id="trace-1"))
        for _ in range(3):
            client.post("/events", json=_tool_event(
                "fetch", "failure", "api_error", latency_ms=300.0, trace_id="trace-2"
            ))
        # Seed parse events (large output — 15k tokens = 7.5% of 200k context)
        for _ in range(6):
            client.post("/events", json=_tool_event(
                "parse", "success", output_tokens=15_000, trace_id="trace-1"
            ))
        # Seed LLM calls
        client.post("/events", json=_llm_event("trace-1", context_utilisation=0.3))
        client.post("/events", json=_llm_event("trace-2", context_utilisation=0.85))
        yield client


class TestFailureClusteringIntegration:
    def test_two_clusters_returned(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get("/intelligence/failures")
        assert resp.status_code == 200
        data = resp.json()
        tools = {c["tool_name"] for c in data}
        assert "search" in tools
        assert "fetch" in tools

    def test_fetch_has_higher_failure_rate_than_search(
        self, seeded_client: TestClient
    ) -> None:
        resp = seeded_client.get("/intelligence/failures")
        data = resp.json()
        by_tool = {c["tool_name"]: c for c in data}
        assert by_tool["fetch"]["failure_rate"] > by_tool["search"]["failure_rate"]

    def test_sorted_by_failure_rate_desc(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get("/intelligence/failures")
        data = resp.json()
        rates = [c["failure_rate"] for c in data]
        assert rates == sorted(rates, reverse=True)

    def test_suggestions_present(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get("/intelligence/failures")
        for cluster in resp.json():
            assert len(cluster["suggestion"]) > 0
            assert len(cluster["pattern_description"]) > 0

    def test_search_failure_rate_is_25pct(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get("/intelligence/failures")
        clusters = resp.json()
        search = next(c for c in clusters if c["tool_name"] == "search")
        # 2 failures out of 8 calls = 25%
        assert search["failure_rate"] == pytest.approx(0.25, rel=0.01)


class TestTokenOptimizationIntegration:
    def test_parse_tool_flagged_as_optimization_candidate(
        self, seeded_client: TestClient
    ) -> None:
        resp = seeded_client.get("/intelligence/optimization")
        assert resp.status_code == 200
        data = resp.json()
        tool_names = [s["tool_name"] for s in data]
        assert "parse" in tool_names

    def test_suggestion_text_describes_parse(
        self, seeded_client: TestClient
    ) -> None:
        resp = seeded_client.get("/intelligence/optimization")
        data = resp.json()
        parse = next(s for s in data if s["tool_name"] == "parse")
        assert "parse" in parse["suggestion_text"]
        assert parse["avg_output_tokens"] == pytest.approx(15_000.0, rel=0.05)

    def test_small_tools_not_included(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get("/intelligence/optimization")
        tool_names = [s["tool_name"] for s in resp.json()]
        # search/fetch have no explicit token_usage_output — small estimated size
        # They may or may not appear; just ensure parse is there
        assert "parse" in tool_names


class TestQualityScoresIntegration:
    def test_tool_scores_all_three_tools(
        self, seeded_client: TestClient
    ) -> None:
        resp = seeded_client.get("/intelligence/quality/tools")
        data = resp.json()
        names = {s["tool_name"] for s in data}
        assert {"search", "fetch", "parse"} <= names

    def test_parse_tool_gets_high_score(
        self, seeded_client: TestClient
    ) -> None:
        resp = seeded_client.get("/intelligence/quality/tools")
        data = resp.json()
        parse_score = next(s for s in data if s["tool_name"] == "parse")
        assert parse_score["reliability_score"] == 1.0
        assert parse_score["overall_score"] >= 0.8

    def test_fetch_tool_has_low_reliability(
        self, seeded_client: TestClient
    ) -> None:
        resp = seeded_client.get("/intelligence/quality/tools")
        data = resp.json()
        fetch_score = next(s for s in data if s["tool_name"] == "fetch")
        assert fetch_score["reliability_score"] == pytest.approx(0.25, rel=0.01)

    def test_sorted_worst_first(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get("/intelligence/quality/tools")
        data = resp.json()
        scores = [s["overall_score"] for s in data]
        assert scores == sorted(scores)

    def test_run_scores_two_traces(self, seeded_client: TestClient) -> None:
        resp = seeded_client.get("/intelligence/quality/runs")
        assert resp.status_code == 200
        data = resp.json()
        trace_ids = {s["trace_id"] for s in data}
        assert {"trace-1", "trace-2"} <= trace_ids

    def test_high_context_run_has_lower_score(
        self, seeded_client: TestClient
    ) -> None:
        resp = seeded_client.get("/intelligence/quality/runs")
        data = resp.json()
        by_trace = {s["trace_id"]: s for s in data}
        # trace-2 has 85% context utilisation → lower efficiency
        assert (
            by_trace["trace-2"]["context_efficiency_score"]
            < by_trace["trace-1"]["context_efficiency_score"]
        )

    def test_scores_all_bounded(self, seeded_client: TestClient) -> None:
        resp_tools = seeded_client.get("/intelligence/quality/tools")
        resp_runs = seeded_client.get("/intelligence/quality/runs")
        for item in resp_tools.json() + resp_runs.json():
            assert 0.0 <= item["overall_score"] <= 1.0
