"""Unit tests for the Collector REST API using FastAPI TestClient."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from agentscope.collector.api.app import create_app
from agentscope.collector.service import CollectorService
from agentscope.collector.storage.sqlite import SQLiteBackend
from agentscope.core.config import AgentScopeConfig
from agentscope.core.pipeline.pipeline import EventPipeline


def make_test_app() -> tuple[TestClient, CollectorService]:
    """Build a TestClient backed by an in-memory service.

    The TestClient owns the lifespan — service starts/stops via app startup hooks.
    """
    cfg = AgentScopeConfig(db_path=":memory:", batch_size=1, batch_interval_ms=9999)  # type: ignore[call-arg]
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
                config=AgentScopeConfig(db_path=":memory:", batch_size=1, batch_interval_ms=9999),  # type: ignore[call-arg]
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
