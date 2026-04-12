"""Unit tests for GET /traces and GET /traces/{trace_id}/graph."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from anjor.collector.api.app import create_app
from anjor.collector.service import CollectorService
from anjor.collector.storage.sqlite import SQLiteBackend
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.pipeline import EventPipeline


@pytest.fixture
def client() -> TestClient:
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


def span_event(
    trace_id: str,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    agent_name: str = "agent",
    span_kind: str = "root",
    status: str = "ok",
    token_input: int = 100,
    token_output: int = 50,
) -> dict:
    return {
        "event_type": "agent_span",
        "span_id": span_id or str(uuid.uuid4()),
        "parent_span_id": parent_span_id,
        "trace_id": trace_id,
        "span_kind": span_kind,
        "agent_name": agent_name,
        "agent_role": "",
        "started_at": datetime.now(UTC).isoformat(),
        "ended_at": datetime.now(UTC).isoformat(),
        "status": status,
        "failure_type": None,
        "token_input": token_input,
        "token_output": token_output,
        "tool_calls_count": 1,
        "llm_calls_count": 1,
    }


class TestListTraces:
    def test_empty(self, client: TestClient) -> None:
        resp = client.get("/traces")
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_seeded_trace(self, client: TestClient) -> None:
        tid = str(uuid.uuid4())
        client.post("/events", json=span_event(tid, agent_name="planner"))
        resp = client.get("/traces")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 1
        assert data[0]["trace_id"] == tid
        assert data[0]["root_agent_name"] == "planner"

    def test_pagination(self, client: TestClient) -> None:
        for _ in range(5):
            client.post("/events", json=span_event(str(uuid.uuid4())))
        page1 = client.get("/traces?limit=3&offset=0").json()
        page2 = client.get("/traces?limit=3&offset=3").json()
        assert len(page1) == 3
        assert len(page2) == 2


class TestGetTraceGraph:
    def test_404_for_unknown_trace(self, client: TestClient) -> None:
        resp = client.get(f"/traces/{uuid.uuid4()}/graph")
        assert resp.status_code == 404

    def test_single_node_graph(self, client: TestClient) -> None:
        tid = str(uuid.uuid4())
        sid = str(uuid.uuid4())
        client.post("/events", json=span_event(tid, span_id=sid, agent_name="solo"))
        resp = client.get(f"/traces/{tid}/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["trace_id"] == tid
        assert data["node_count"] == 1
        assert data["has_cycle"] is False
        assert len(data["nodes"]) == 1
        assert data["nodes"][0]["agent_name"] == "solo"
        assert data["edges"] == []

    def test_parent_child_graph(self, client: TestClient) -> None:
        tid = str(uuid.uuid4())
        root_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())
        client.post("/events", json=span_event(
            tid, span_id=root_id, agent_name="orchestrator", span_kind="orchestrator",
        ))
        client.post("/events", json=span_event(
            tid, span_id=child_id, parent_span_id=root_id,
            agent_name="worker", span_kind="subagent",
        ))
        resp = client.get(f"/traces/{tid}/graph")
        assert resp.status_code == 200
        data = resp.json()
        assert data["node_count"] == 2
        assert len(data["edges"]) == 1
        assert data["edges"][0] == [root_id, child_id]

    def test_node_shape(self, client: TestClient) -> None:
        tid = str(uuid.uuid4())
        client.post("/events", json=span_event(
            tid, agent_name="checker", token_input=300, token_output=100,
        ))
        data = client.get(f"/traces/{tid}/graph").json()
        node = data["nodes"][0]
        assert "span_id" in node
        assert "depth" in node
        assert "duration_ms" in node
        assert node["token_input"] == 300
        assert node["token_output"] == 100
