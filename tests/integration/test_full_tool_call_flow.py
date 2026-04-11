"""Integration test: full tool call flow with FastAPI TestClient."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from agentscope.collector.api.app import create_app
from agentscope.collector.service import CollectorService
from agentscope.collector.storage.sqlite import SQLiteBackend
from agentscope.core.config import AgentScopeConfig
from agentscope.core.pipeline.pipeline import EventPipeline

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

_TOOL_RESPONSE = {
    "content": [
        {
            "type": "tool_use",
            "id": "toolu_01",
            "name": "calculator",
            "input": {"expression": "2 + 2"},
        }
    ],
    "usage": {"input_tokens": 50, "output_tokens": 20},
}


@pytest.fixture
def collector_client() -> TestClient:
    cfg = AgentScopeConfig(db_path=":memory:", batch_size=1, batch_interval_ms=9999)  # type: ignore[call-arg]
    storage = SQLiteBackend(db_path=":memory:", batch_size=1)
    pipeline = EventPipeline()
    svc = CollectorService(config=cfg, storage=storage, pipeline=pipeline)
    app = create_app(service=svc)
    with TestClient(app) as client:
        yield client


class TestFullToolCallFlow:
    def test_health_check(self, collector_client: TestClient) -> None:
        resp = collector_client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    def test_ingest_and_query(self, collector_client: TestClient) -> None:
        event_payload = {
            "event_type": "tool_call",
            "tool_name": "calculator",
            "trace_id": "trace-integration-1",
            "session_id": "session-1",
            "agent_id": "test-agent",
            "timestamp": datetime.now(UTC).isoformat(),
            "sequence_no": 0,
            "status": "success",
            "failure_type": None,
            "latency_ms": 150.0,
            "input_payload": {"expression": "2 + 2"},
            "output_payload": {"result": 4},
            "input_schema_hash": "hash1",
            "output_schema_hash": "hash2",
        }

        # Ingest
        resp = collector_client.post("/events", json=event_payload)
        assert resp.status_code == 202

        # Query tools list
        resp = collector_client.get("/tools")
        assert resp.status_code == 200
        tools = resp.json()
        assert len(tools) == 1
        assert tools[0]["tool_name"] == "calculator"
        assert tools[0]["call_count"] == 1
        assert tools[0]["success_rate"] == 1.0

        # Query tool detail
        resp = collector_client.get("/tools/calculator")
        assert resp.status_code == 200
        detail = resp.json()
        assert detail["call_count"] == 1
        assert detail["success_count"] == 1

    def test_multiple_events_aggregation(self, collector_client: TestClient) -> None:
        def post_event(status: str, latency: float) -> None:
            collector_client.post(
                "/events",
                json={
                    "event_type": "tool_call",
                    "tool_name": "search",
                    "status": status,
                    "latency_ms": latency,
                    "timestamp": datetime.now(UTC).isoformat(),
                    "sequence_no": 0,
                    "trace_id": "t",
                    "session_id": "s",
                },
            )

        post_event("success", 100.0)
        post_event("success", 200.0)
        post_event("failure", 50.0)

        detail = collector_client.get("/tools/search").json()
        assert detail["call_count"] == 3
        assert detail["success_count"] == 2
        assert detail["failure_count"] == 1
        assert detail["success_rate"] == pytest.approx(2 / 3)
