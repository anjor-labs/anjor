"""Unit tests for StorageBackend and SQLiteBackend (in-memory SQLite)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentscope.collector.storage.base import QueryFilters, SchemaSnapshot
from agentscope.collector.storage.sqlite import SQLiteBackend


@pytest.fixture
async def storage() -> SQLiteBackend:
    """In-memory SQLite backend, connected and ready."""
    backend = SQLiteBackend(db_path=":memory:", batch_size=1, batch_interval_ms=9999)
    await backend.connect()
    yield backend
    await backend.close()


def make_event(
    tool_name: str = "search",
    status: str = "success",
    latency_ms: float = 100.0,
    **kwargs: object,
) -> dict:
    return {
        "event_type": "tool_call",
        "trace_id": "trace-1",
        "session_id": "session-1",
        "agent_id": "default",
        "timestamp": datetime.now(UTC).isoformat(),
        "sequence_no": 0,
        "tool_name": tool_name,
        "status": status,
        "failure_type": None,
        "latency_ms": latency_ms,
        "input_payload": {"query": "hello"},
        "output_payload": {"results": []},
        "input_schema_hash": "abc",
        "output_schema_hash": "def",
        **kwargs,
    }


class TestSQLiteBackend:
    async def test_write_and_query_event(self, storage: SQLiteBackend) -> None:
        event = make_event()
        await storage.write_event(event)
        results = await storage.query_tool_calls(QueryFilters())
        assert len(results) == 1
        assert results[0]["tool_name"] == "search"

    async def test_filter_by_tool_name(self, storage: SQLiteBackend) -> None:
        await storage.write_event(make_event(tool_name="search"))
        await storage.write_event(make_event(tool_name="lookup"))
        results = await storage.query_tool_calls(QueryFilters(tool_name="search"))
        assert len(results) == 1
        assert results[0]["tool_name"] == "search"

    async def test_filter_by_status(self, storage: SQLiteBackend) -> None:
        await storage.write_event(make_event(status="success"))
        await storage.write_event(make_event(status="failure"))
        results = await storage.query_tool_calls(QueryFilters(status="failure"))
        assert len(results) == 1
        assert results[0]["status"] == "failure"

    async def test_query_limit_and_offset(self, storage: SQLiteBackend) -> None:
        for _ in range(5):
            await storage.write_event(make_event())
        results = await storage.query_tool_calls(QueryFilters(limit=2, offset=0))
        assert len(results) == 2

    async def test_tool_summary(self, storage: SQLiteBackend) -> None:
        await storage.write_event(make_event(latency_ms=100.0, status="success"))
        await storage.write_event(make_event(latency_ms=200.0, status="success"))
        await storage.write_event(make_event(latency_ms=300.0, status="failure"))
        summary = await storage.get_tool_summary("search")
        assert summary is not None
        assert summary.call_count == 3
        assert summary.success_count == 2
        assert summary.failure_count == 1
        assert summary.success_rate == pytest.approx(2 / 3)

    async def test_tool_summary_none_for_unknown_tool(
        self, storage: SQLiteBackend
    ) -> None:
        result = await storage.get_tool_summary("nonexistent")
        assert result is None

    async def test_list_tool_summaries(self, storage: SQLiteBackend) -> None:
        await storage.write_event(make_event(tool_name="search"))
        await storage.write_event(make_event(tool_name="lookup"))
        summaries = await storage.list_tool_summaries()
        names = {s.tool_name for s in summaries}
        assert "search" in names
        assert "lookup" in names

    async def test_write_and_get_schema_snapshot(
        self, storage: SQLiteBackend
    ) -> None:
        snap = SchemaSnapshot(
            tool_name="search",
            payload_type="input",
            schema_hash="hash123",
            captured_at=datetime.now(UTC),
            sample_payload={"query": "hello"},
        )
        await storage.write_schema_snapshot(snap)
        retrieved = await storage.get_schema_snapshot("search", "input")
        assert retrieved is not None
        assert retrieved.schema_hash == "hash123"
        assert retrieved.tool_name == "search"

    async def test_schema_snapshot_upsert(self, storage: SQLiteBackend) -> None:
        snap1 = SchemaSnapshot(
            tool_name="t",
            payload_type="input",
            schema_hash="old",
            captured_at=datetime.now(UTC),
        )
        snap2 = SchemaSnapshot(
            tool_name="t",
            payload_type="input",
            schema_hash="new",
            captured_at=datetime.now(UTC),
        )
        await storage.write_schema_snapshot(snap1)
        await storage.write_schema_snapshot(snap2)
        retrieved = await storage.get_schema_snapshot("t", "input")
        assert retrieved is not None
        assert retrieved.schema_hash == "new"

    async def test_get_schema_snapshot_none_for_unknown(
        self, storage: SQLiteBackend
    ) -> None:
        result = await storage.get_schema_snapshot("nope", "input")
        assert result is None

    async def test_event_with_token_usage(self, storage: SQLiteBackend) -> None:
        event = make_event(token_usage={"input": 50, "output": 100})
        await storage.write_event(event)
        results = await storage.query_tool_calls(QueryFilters())
        assert results[0]["token_usage_input"] == 50
        assert results[0]["token_usage_output"] == 100

    async def test_event_with_schema_drift(self, storage: SQLiteBackend) -> None:
        event = make_event(
            schema_drift={
                "detected": True,
                "missing_fields": ["count"],
                "unexpected_fields": ["total"],
                "expected_hash": "abc",
            }
        )
        await storage.write_event(event)
        results = await storage.query_tool_calls(QueryFilters())
        assert results[0]["drift_detected"] == 1

    async def test_latency_percentiles(self, storage: SQLiteBackend) -> None:
        latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
        for lat in latencies:
            await storage.write_event(make_event(latency_ms=lat))
        summary = await storage.get_tool_summary("search")
        assert summary is not None
        assert summary.p50_latency_ms > 0
        assert summary.p95_latency_ms >= summary.p50_latency_ms
        assert summary.p99_latency_ms >= summary.p95_latency_ms

    async def test_migrations_applied_once(self, storage: SQLiteBackend) -> None:
        # Reconnecting should not fail due to duplicate migration
        assert storage._conn is not None  # connection is open
        await storage._run_migrations()  # idempotent
