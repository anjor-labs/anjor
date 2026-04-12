"""Unit tests for the Phase 3 intelligence API endpoints.

Tests GET /intelligence/failures, /intelligence/optimization,
/intelligence/quality/tools, /intelligence/quality/runs.
All tests use in-memory SQLite and FastAPI TestClient — no real I/O.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from anjor.collector.api.app import create_app
from anjor.collector.service import CollectorService
from anjor.collector.storage.sqlite import SQLiteBackend
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.pipeline import EventPipeline


def _make_client() -> TestClient:
    svc = CollectorService(
        config=AnjorConfig(db_path=":memory:", batch_size=1, batch_interval_ms=9999),  # type: ignore[call-arg]
        storage=SQLiteBackend(db_path=":memory:", batch_size=1),
        pipeline=EventPipeline(),
    )
    return TestClient(create_app(service=svc))


def _ts() -> str:
    return datetime.now(UTC).isoformat()


def _tool_event(
    tool_name: str = "search",
    status: str = "success",
    failure_type: str | None = None,
    latency_ms: float = 100.0,
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
        "input_schema_hash": "abc",
        "output_schema_hash": "def",
        "token_usage": None,
        "schema_drift": None,
    }
    if output_tokens is not None:
        evt["token_usage"] = {"input": 100, "output": output_tokens}
    return evt


def _llm_event(
    trace_id: str = "trace-1",
    model: str = "claude-3-5-sonnet-20241022",
    context_window_limit: int = 200_000,
    context_utilisation: float = 0.05,
) -> dict:
    return {
        "event_type": "llm_call",
        "trace_id": trace_id,
        "session_id": "session-1",
        "agent_id": "default",
        "timestamp": _ts(),
        "sequence_no": 0,
        "model": model,
        "latency_ms": 500.0,
        "token_usage": {"input": 1000, "output": 500},
        "context_window_used": int(context_window_limit * context_utilisation),
        "context_window_limit": context_window_limit,
        "context_utilisation": context_utilisation,
        "prompt_hash": "ph1",
        "system_prompt_hash": None,
        "messages_count": 5,
        "finish_reason": "end_turn",
    }


# ---------------------------------------------------------------------------
# GET /intelligence/failures
# ---------------------------------------------------------------------------


class TestIntelligureFailures:
    def test_empty_db_returns_empty_list(self) -> None:
        with _make_client() as client:
            resp = client.get("/intelligence/failures")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_failures_returned_with_correct_shape(self) -> None:
        with _make_client() as client:
            client.post("/events", json=_tool_event(status="success"))
            client.post("/events", json=_tool_event(
                status="failure", failure_type="timeout", latency_ms=9000.0
            ))
            resp = client.get("/intelligence/failures")

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        cluster = data[0]
        assert cluster["tool_name"] == "search"
        assert cluster["failure_type"] == "timeout"
        assert cluster["occurrence_count"] == 1
        assert cluster["total_calls"] == 2
        assert cluster["failure_rate"] == pytest.approx(0.5, rel=0.01)
        assert "pattern_description" in cluster
        assert "suggestion" in cluster

    def test_multiple_tools_clustered(self) -> None:
        with _make_client() as client:
            client.post("/events", json=_tool_event(
                tool_name="fetch", status="failure", failure_type="api_error"
            ))
            client.post("/events", json=_tool_event(
                tool_name="search", status="failure", failure_type="schema_drift"
            ))
            resp = client.get("/intelligence/failures")

        data = resp.json()
        tools = {c["tool_name"] for c in data}
        assert tools == {"fetch", "search"}

    def test_sorted_by_failure_rate_desc(self) -> None:
        with _make_client() as client:
            # "slow" fails 1/1 = 100%
            client.post("/events", json=_tool_event(
                tool_name="slow", status="failure", failure_type="timeout"
            ))
            # "partial" fails 1/3 ≈ 33%
            for _ in range(2):
                client.post("/events", json=_tool_event(tool_name="partial", status="success"))
            client.post("/events", json=_tool_event(
                tool_name="partial", status="failure", failure_type="api_error"
            ))
            resp = client.get("/intelligence/failures")

        data = resp.json()
        assert len(data) >= 2
        assert data[0]["failure_rate"] >= data[1]["failure_rate"]


# ---------------------------------------------------------------------------
# GET /intelligence/optimization
# ---------------------------------------------------------------------------


class TestIntelligenceOptimization:
    def test_empty_db_returns_empty_list(self) -> None:
        with _make_client() as client:
            resp = client.get("/intelligence/optimization")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_small_output_excluded(self) -> None:
        with _make_client() as client:
            client.post("/events", json=_tool_event(output_tokens=100))
            client.post("/events", json=_llm_event(context_window_limit=200_000))
            resp = client.get("/intelligence/optimization")
        assert resp.json() == []

    def test_large_output_included(self) -> None:
        with _make_client() as client:
            # 12k tokens = 6% of 200k → above threshold
            client.post("/events", json=_tool_event(output_tokens=12_000))
            client.post("/events", json=_llm_event(context_window_limit=200_000))
            resp = client.get("/intelligence/optimization")

        data = resp.json()
        assert len(data) == 1
        s = data[0]
        assert s["tool_name"] == "search"
        assert s["avg_output_tokens"] == pytest.approx(12_000.0, rel=0.05)
        assert 0.0 <= s["waste_score"] <= 1.0
        assert "suggestion_text" in s

    def test_response_shape_complete(self) -> None:
        with _make_client() as client:
            client.post("/events", json=_tool_event(output_tokens=15_000))
            client.post("/events", json=_llm_event())
            resp = client.get("/intelligence/optimization")

        assert resp.status_code == 200
        if resp.json():
            keys = resp.json()[0].keys()
            for field in [
                "tool_name", "avg_output_tokens", "avg_context_fraction",
                "waste_score", "estimated_savings_tokens_per_call",
                "estimated_savings_usd_per_1k_calls", "suggestion_text",
            ]:
                assert field in keys


# ---------------------------------------------------------------------------
# GET /intelligence/quality/tools
# ---------------------------------------------------------------------------


class TestIntelligenceQualityTools:
    def test_empty_db_returns_empty(self) -> None:
        with _make_client() as client:
            resp = client.get("/intelligence/quality/tools")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_perfect_tool_gets_grade_a(self) -> None:
        with _make_client() as client:
            for _ in range(5):
                client.post("/events", json=_tool_event(status="success", latency_ms=100.0))
            resp = client.get("/intelligence/quality/tools")

        data = resp.json()
        assert len(data) == 1
        assert data[0]["grade"] == "A"
        assert data[0]["overall_score"] >= 0.9

    def test_all_failures_grade_f(self) -> None:
        with _make_client() as client:
            for _ in range(5):
                client.post("/events", json=_tool_event(
                    status="failure", failure_type="timeout", latency_ms=9000.0
                ))
            resp = client.get("/intelligence/quality/tools")

        data = resp.json()
        assert data[0]["grade"] == "F"
        assert data[0]["reliability_score"] == 0.0

    def test_response_shape(self) -> None:
        with _make_client() as client:
            client.post("/events", json=_tool_event(status="success"))
            resp = client.get("/intelligence/quality/tools")

        assert resp.status_code == 200
        item = resp.json()[0]
        for field in [
            "tool_name", "call_count", "reliability_score",
            "schema_stability_score", "latency_consistency_score",
            "overall_score", "grade",
        ]:
            assert field in item

    def test_sorted_worst_first(self) -> None:
        with _make_client() as client:
            # good tool: all success
            for _ in range(3):
                client.post("/events", json=_tool_event(tool_name="good", status="success"))
            # bad tool: all failure
            for _ in range(3):
                client.post("/events", json=_tool_event(
                    tool_name="bad", status="failure", failure_type="timeout"
                ))
            resp = client.get("/intelligence/quality/tools")

        data = resp.json()
        assert data[0]["overall_score"] <= data[-1]["overall_score"]


# ---------------------------------------------------------------------------
# GET /intelligence/quality/runs
# ---------------------------------------------------------------------------


class TestIntelligenceQualityRuns:
    def test_empty_db_returns_empty(self) -> None:
        with _make_client() as client:
            resp = client.get("/intelligence/quality/runs")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_efficient_run_gets_high_score(self) -> None:
        with _make_client() as client:
            client.post("/events", json=_tool_event(
                status="success", trace_id="run1"
            ))
            client.post("/events", json=_llm_event(
                trace_id="run1", context_utilisation=0.1
            ))
            resp = client.get("/intelligence/quality/runs")

        data = resp.json()
        assert len(data) == 1
        s = data[0]
        assert s["trace_id"] == "run1"
        assert s["context_efficiency_score"] == pytest.approx(0.9, rel=0.01)
        assert s["overall_score"] > 0.7

    def test_response_shape(self) -> None:
        with _make_client() as client:
            client.post("/events", json=_tool_event(status="success", trace_id="r"))
            resp = client.get("/intelligence/quality/runs")

        assert resp.status_code == 200
        item = resp.json()[0]
        for field in [
            "trace_id", "llm_call_count", "tool_call_count",
            "context_efficiency_score", "failure_recovery_score",
            "tool_diversity_score", "overall_score", "grade",
        ]:
            assert field in item

    def test_sorted_worst_first(self) -> None:
        with _make_client() as client:
            # good run: low context usage
            client.post("/events", json=_tool_event(status="success", trace_id="good"))
            client.post("/events", json=_llm_event(
                trace_id="good", context_utilisation=0.1
            ))
            # bad run: high context usage + failures
            for _ in range(3):
                client.post("/events", json=_tool_event(
                    status="failure", failure_type="timeout", trace_id="bad"
                ))
            client.post("/events", json=_llm_event(
                trace_id="bad", context_utilisation=0.95
            ))
            resp = client.get("/intelligence/quality/runs")

        data = resp.json()
        assert len(data) >= 2
        assert data[0]["overall_score"] <= data[-1]["overall_score"]
