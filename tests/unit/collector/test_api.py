"""Unit tests for the Collector REST API using FastAPI TestClient."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from anjor.collector.api.app import create_app
from anjor.collector.service import CollectorService
from anjor.collector.storage.sqlite import SQLiteBackend
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.pipeline import EventPipeline


def make_test_app() -> tuple[TestClient, CollectorService]:
    """Build a TestClient backed by an in-memory service.

    The TestClient owns the lifespan — service starts/stops via app startup hooks.
    """
    cfg = AnjorConfig(db_path=":memory:", batch_size=1, batch_interval_ms=9999)  # type: ignore[call-arg]
    storage = SQLiteBackend(db_path=":memory:", batch_size=1)
    pipeline = EventPipeline()
    svc = CollectorService(config=cfg, storage=storage, pipeline=pipeline)
    app = create_app(service=svc)
    return TestClient(app), svc


@pytest.fixture
def client() -> TestClient:
    """TestClient with full lifespan (service starts/stops with it)."""
    with TestClient(
        create_app(
            service=CollectorService(
                config=AnjorConfig(db_path=":memory:", batch_size=1, batch_interval_ms=9999),  # type: ignore[call-arg]
                storage=SQLiteBackend(db_path=":memory:", batch_size=1),
                pipeline=EventPipeline(),
            )
        )
    ) as c:
        yield c


def sample_event(**kwargs: object) -> dict:
    return {
        "event_type": "tool_call",
        "tool_name": "search",
        "trace_id": "trace-1",
        "session_id": "session-1",
        "agent_id": "default",
        "timestamp": datetime.now(UTC).isoformat(),
        "sequence_no": 0,
        "status": "success",
        "failure_type": None,
        "latency_ms": 100.0,
        "input_payload": {"query": "hello"},
        "output_payload": {"results": []},
        "input_schema_hash": "abc",
        "output_schema_hash": "def",
        **kwargs,
    }


class TestRootRedirect:
    def test_root_redirects_to_ui(self, client: TestClient) -> None:
        resp = client.get("/", follow_redirects=False)
        assert resp.status_code in (301, 302, 307, 308)
        assert "/ui/" in resp.headers["location"]


class TestHealthEndpoint:
    def test_returns_200(self, client: TestClient) -> None:
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_response_shape(self, client: TestClient) -> None:
        data = client.get("/health").json()
        assert "status" in data
        assert "uptime_seconds" in data
        assert "queue_depth" in data
        assert "db_path" in data

    def test_status_is_ok(self, client: TestClient) -> None:
        assert client.get("/health").json()["status"] == "ok"

    def test_db_path_is_memory(self, client: TestClient) -> None:
        assert client.get("/health").json()["db_path"] == ":memory:"


class TestEventsEndpoint:
    def test_post_event_returns_202(self, client: TestClient) -> None:
        resp = client.post("/events", json=sample_event())
        assert resp.status_code == 202

    def test_response_body(self, client: TestClient) -> None:
        data = client.post("/events", json=sample_event()).json()
        assert data["accepted"] is True

    def test_invalid_payload_returns_422(self, client: TestClient) -> None:
        resp = client.post("/events", json={"event_type": "tool_call", "latency_ms": -1})
        assert resp.status_code == 422

    def test_missing_event_type_returns_422(self, client: TestClient) -> None:
        resp = client.post("/events", json={"tool_name": "x"})
        assert resp.status_code == 422


class TestToolsEndpoint:
    def test_list_tools_empty(self, client: TestClient) -> None:
        resp = client.get("/tools")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_tools_after_event(self, client: TestClient) -> None:
        client.post("/events", json=sample_event())
        resp = client.get("/tools")
        assert resp.status_code == 200
        tools = resp.json()
        assert len(tools) == 1
        assert tools[0]["tool_name"] == "search"

    def test_tool_detail_not_found(self, client: TestClient) -> None:
        resp = client.get("/tools/nonexistent")
        assert resp.status_code == 404

    def test_tool_detail_after_event(self, client: TestClient) -> None:
        client.post("/events", json=sample_event())
        resp = client.get("/tools/search")
        assert resp.status_code == 200
        data = resp.json()
        assert data["tool_name"] == "search"
        assert data["call_count"] == 1
        assert "p50_latency_ms" in data
        assert "p95_latency_ms" in data
        assert "p99_latency_ms" in data

    def test_tool_list_item_fields(self, client: TestClient) -> None:
        client.post("/events", json=sample_event())
        items = client.get("/tools").json()
        item = items[0]
        assert "tool_name" in item
        assert "call_count" in item
        assert "success_rate" in item
        assert "avg_latency_ms" in item


def sample_llm_event(**kwargs: object) -> dict:
    return {
        "event_type": "llm_call",
        "trace_id": "trace-llm-1",
        "session_id": "session-1",
        "agent_id": "default",
        "timestamp": datetime.now(UTC).isoformat(),
        "sequence_no": 0,
        "model": "claude-3-5-sonnet-20241022",
        "latency_ms": 500.0,
        "token_usage": {"input": 100, "output": 50, "cache_read": 0},
        "context_window_used": 150,
        "context_window_limit": 200_000,
        "context_utilisation": 0.00075,
        "prompt_hash": "abc123",
        "system_prompt_hash": None,
        "messages_count": 2,
        "finish_reason": "end_turn",
        **kwargs,
    }


class TestLLMEndpoint:
    def test_list_llm_empty(self, client: TestClient) -> None:
        resp = client.get("/llm")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_list_llm_after_event(self, client: TestClient) -> None:
        client.post("/events", json=sample_llm_event())
        resp = client.get("/llm")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["model"] == "claude-3-5-sonnet-20241022"

    def test_llm_summary_fields(self, client: TestClient) -> None:
        client.post("/events", json=sample_llm_event())
        item = client.get("/llm").json()[0]
        assert "model" in item
        assert "call_count" in item
        assert "avg_latency_ms" in item
        assert "avg_token_input" in item
        assert "avg_token_output" in item
        assert "avg_context_utilisation" in item

    def test_llm_trace_not_found(self, client: TestClient) -> None:
        resp = client.get("/llm/trace/nonexistent-trace")
        assert resp.status_code == 404

    def test_llm_trace_detail(self, client: TestClient) -> None:
        client.post("/events", json=sample_llm_event(trace_id="trace-xyz"))
        resp = client.get("/llm/trace/trace-xyz")
        assert resp.status_code == 200
        items = resp.json()
        assert len(items) == 1
        assert items[0]["trace_id"] == "trace-xyz"
        assert items[0]["model"] == "claude-3-5-sonnet-20241022"

    def test_llm_trace_multiple_calls(self, client: TestClient) -> None:
        for _ in range(3):
            client.post("/events", json=sample_llm_event(trace_id="trace-multi"))
        resp = client.get("/llm/trace/trace-multi")
        assert resp.status_code == 200
        assert len(resp.json()) == 3

    def test_llm_aggregate_call_count(self, client: TestClient) -> None:
        for _ in range(4):
            client.post("/events", json=sample_llm_event())
        items = client.get("/llm").json()
        assert items[0]["call_count"] == 4


class TestCallsEndpoint:
    def test_empty_returns_200(self, client: TestClient) -> None:
        resp = client.get("/calls")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_tool_calls_after_event(self, client: TestClient) -> None:
        client.post("/events", json=sample_event(tool_name="search"))
        resp = client.get("/calls")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["tool_name"] == "search"

    def test_filter_by_tool_name(self, client: TestClient) -> None:
        client.post("/events", json=sample_event(tool_name="search"))
        client.post("/events", json=sample_event(tool_name="fetch"))
        resp = client.get("/calls?tool_name=search")
        assert len(resp.json()) == 1
        assert resp.json()[0]["tool_name"] == "search"

    def test_drift_only_filter(self, client: TestClient) -> None:
        # post one normal call and one drift call
        client.post("/events", json=sample_event())
        drift_event = {
            **sample_event(),
            "schema_drift": {"detected": True, "missing_fields": ["x"], "unexpected_fields": []},
        }
        client.post("/events", json=drift_event)
        resp = client.get("/calls?drift_only=true")
        rows = resp.json()
        assert len(rows) == 1
        assert rows[0]["drift_detected"] == 1

    def test_drift_only_false_returns_all(self, client: TestClient) -> None:
        client.post("/events", json=sample_event())
        client.post("/events", json=sample_event())
        resp = client.get("/calls?drift_only=false")
        assert len(resp.json()) == 2

    def test_limit_param(self, client: TestClient) -> None:
        for _ in range(5):
            client.post("/events", json=sample_event())
        resp = client.get("/calls?limit=2")
        assert len(resp.json()) == 2

    def test_offset_param(self, client: TestClient) -> None:
        for i in range(3):
            client.post("/events", json=sample_event(sequence_no=i))
        all_rows = client.get("/calls?limit=10").json()
        offset_rows = client.get("/calls?limit=10&offset=1").json()
        assert len(offset_rows) == len(all_rows) - 1

    def test_llm_events_not_returned(self, client: TestClient) -> None:
        client.post("/events", json=sample_llm_event())
        resp = client.get("/calls")
        assert resp.json() == []


class TestLLMUsageEndpoints:
    """Tests for cache fields in /llm and new /llm/usage/daily endpoint."""

    def test_llm_summary_includes_totals(self, client: TestClient) -> None:
        client.post("/events", json=sample_llm_event())
        client.post("/events", json=sample_llm_event())
        item = client.get("/llm").json()[0]
        assert "total_token_input" in item
        assert "total_token_output" in item
        assert item["total_token_input"] == 200  # 2 × 100
        assert item["total_token_output"] == 100  # 2 × 50

    def test_llm_summary_includes_cache_fields(self, client: TestClient) -> None:
        usage = {"input": 100, "output": 50, "cache_read": 300, "cache_creation": 150}
        event = sample_llm_event(token_usage=usage)
        client.post("/events", json=event)
        item = client.get("/llm").json()[0]
        assert "total_cache_read" in item
        assert "total_cache_write" in item
        assert item["total_cache_read"] == 300
        assert item["total_cache_write"] == 150

    def test_daily_usage_empty(self, client: TestClient) -> None:
        resp = client.get("/llm/usage/daily")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_daily_usage_returns_data(self, client: TestClient) -> None:
        client.post("/events", json=sample_llm_event())
        resp = client.get("/llm/usage/daily?days=14")
        assert resp.status_code == 200
        rows = resp.json()
        assert len(rows) == 1
        row = rows[0]
        assert row["model"] == "claude-3-5-sonnet-20241022"
        assert row["tokens_in"] == 100
        assert row["tokens_out"] == 50
        assert row["calls"] == 1

    def test_daily_usage_fields(self, client: TestClient) -> None:
        client.post("/events", json=sample_llm_event())
        row = client.get("/llm/usage/daily").json()[0]
        assert "date" in row
        assert "model" in row
        assert "tokens_in" in row
        assert "tokens_out" in row
        assert "cache_read" in row
        assert "cache_write" in row
        assert "calls" in row


class TestProjectsEndpoint:
    def test_projects_empty(self, client: TestClient) -> None:
        resp = client.get("/projects")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_projects_returns_tagged_events(self, client: TestClient) -> None:
        client.post("/events", json=sample_event(project="myproject"))
        client.post("/events", json=sample_event(project="myproject"))
        resp = client.get("/projects")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["project"] == "myproject"
        assert data[0]["tool_call_count"] == 2

    def test_projects_excludes_untagged(self, client: TestClient) -> None:
        client.post("/events", json=sample_event(project=""))
        client.post("/events", json=sample_event(project="tagged"))
        resp = client.get("/projects")
        assert resp.status_code == 200
        assert len(resp.json()) == 1
        assert resp.json()[0]["project"] == "tagged"

    def test_tools_filter_by_project(self, client: TestClient) -> None:
        client.post("/events", json=sample_event(tool_name="search", project="alpha"))
        client.post("/events", json=sample_event(tool_name="lookup", project="beta"))
        resp = client.get("/tools?project=alpha")
        assert resp.status_code == 200
        names = [t["tool_name"] for t in resp.json()]
        assert names == ["search"]

    def test_calls_filter_by_project(self, client: TestClient) -> None:
        client.post("/events", json=sample_event(tool_name="search", project="alpha"))
        client.post("/events", json=sample_event(tool_name="lookup", project="beta"))
        resp = client.get("/calls?project=alpha")
        assert resp.status_code == 200
        calls = resp.json()
        assert len(calls) == 1
        assert calls[0]["tool_name"] == "search"

    def test_llm_filter_by_project(self, client: TestClient) -> None:
        client.post("/events", json=sample_llm_event(project="alpha"))
        client.post("/events", json=sample_llm_event(project="beta"))
        resp = client.get("/llm?project=alpha")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["call_count"] == 1
