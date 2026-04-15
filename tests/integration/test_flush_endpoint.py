"""Tests for POST /flush and the batch_size=1 bypass behaviour."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from anjor.collector.api.app import create_app
from anjor.collector.service import CollectorService
from anjor.collector.storage.sqlite import SQLiteBackend
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.pipeline import EventPipeline


def _ts() -> str:
    return datetime.now(UTC).isoformat()


def _tool_event(tool_name: str = "search", status: str = "success") -> dict:
    return {
        "event_type": "tool_call",
        "tool_name": tool_name,
        "trace_id": "trace-flush-test",
        "session_id": "session-1",
        "agent_id": "default",
        "timestamp": _ts(),
        "sequence_no": 0,
        "status": status,
        "failure_type": None,
        "latency_ms": 100.0,
        "input_payload": {},
        "output_payload": {},
        "input_schema_hash": "h1",
        "output_schema_hash": "h2",
    }


# ---------------------------------------------------------------------------
# Fixture: large batch_interval_ms so periodic flush never fires during tests
# ---------------------------------------------------------------------------


@pytest.fixture
def client() -> TestClient:
    """TestClient backed by in-memory SQLite with a very long flush interval."""
    svc = CollectorService(
        config=AnjorConfig(db_path=":memory:", batch_interval_ms=9999),  # type: ignore[call-arg]
        storage=SQLiteBackend(db_path=":memory:", batch_interval_ms=9999),
        pipeline=EventPipeline(),
    )
    with TestClient(create_app(service=svc)) as c:
        yield c


@pytest.fixture
def batch1_client() -> TestClient:
    """TestClient backed by storage with batch_size=1 (immediate flush per event)."""
    svc = CollectorService(
        config=AnjorConfig(db_path=":memory:", batch_size=1, batch_interval_ms=9999),  # type: ignore[call-arg]
        storage=SQLiteBackend(db_path=":memory:", batch_size=1, batch_interval_ms=9999),
        pipeline=EventPipeline(),
    )
    with TestClient(create_app(service=svc)) as c:
        yield c


# ---------------------------------------------------------------------------
# POST /flush endpoint
# ---------------------------------------------------------------------------


class TestFlushEndpoint:
    def test_flush_empty_batch_returns_zero(self, client: TestClient) -> None:
        resp = client.post("/flush")
        assert resp.status_code == 200
        assert resp.json() == {"flushed": 0}

    def test_flush_after_events_returns_count(self, client: TestClient) -> None:
        for _ in range(3):
            client.post("/events", json=_tool_event())
        resp = client.post("/flush")
        assert resp.status_code == 200
        assert resp.json()["flushed"] == 3

    def test_flush_makes_events_queryable(self, client: TestClient) -> None:
        """Without /flush, events are not yet in SQLite; after /flush they are."""
        client.post("/events", json=_tool_event("calculator"))

        # Before flush: tool not yet in DB (batch interval set to 9999 ms)
        assert client.get("/tools").json() == []

        client.post("/flush")

        # After flush: immediately queryable
        tools = client.get("/tools").json()
        assert len(tools) == 1
        assert tools[0]["tool_name"] == "calculator"

    def test_flush_idempotent_second_call_returns_zero(self, client: TestClient) -> None:
        client.post("/events", json=_tool_event())
        client.post("/flush")
        resp = client.post("/flush")
        assert resp.json()["flushed"] == 0

    def test_flush_counts_only_tool_calls(self, client: TestClient) -> None:
        """LLM events are written immediately and are not counted by /flush."""
        llm_event = {
            "event_type": "llm_call",
            "trace_id": "t1",
            "session_id": "s1",
            "agent_id": "default",
            "timestamp": _ts(),
            "sequence_no": 0,
            "model": "claude-3-5-sonnet-20241022",
            "latency_ms": 500.0,
        }
        client.post("/events", json=llm_event)
        client.post("/events", json=_tool_event())

        resp = client.post("/flush")
        # Only the one tool_call event was in the pending batch
        assert resp.json()["flushed"] == 1


# ---------------------------------------------------------------------------
# batch_size=1 behaviour verification
# ---------------------------------------------------------------------------


class TestBatchSizeOne:
    def test_events_immediately_queryable_without_flush(self, batch1_client: TestClient) -> None:
        """With batch_size=1, every tool_call write triggers an immediate flush.

        Events must be queryable right after POST /events — no /flush call needed.
        This is the documented ANJOR_BATCH_SIZE=1 behaviour.
        """
        batch1_client.post("/events", json=_tool_event("web_search"))

        tools = batch1_client.get("/tools").json()
        assert len(tools) == 1
        assert tools[0]["tool_name"] == "web_search"

    def test_flush_endpoint_returns_zero_after_each_event(self, batch1_client: TestClient) -> None:
        """With batch_size=1, each write is flushed inline so /flush always sees an empty batch."""
        batch1_client.post("/events", json=_tool_event())
        resp = batch1_client.post("/flush")
        assert resp.json()["flushed"] == 0

    def test_multiple_events_all_immediately_queryable(self, batch1_client: TestClient) -> None:
        for i in range(5):
            batch1_client.post("/events", json=_tool_event(f"tool_{i}"))

        tools = batch1_client.get("/tools").json()
        assert len(tools) == 5
