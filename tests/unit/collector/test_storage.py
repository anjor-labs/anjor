"""Unit tests for StorageBackend and SQLiteBackend (in-memory SQLite)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from agentscope.collector.storage.base import LLMQueryFilters, QueryFilters, SchemaSnapshot
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

    async def test_non_tool_call_event_not_stored_in_tool_calls(
        self, storage: SQLiteBackend
    ) -> None:
        """LLMCallEvents should not appear in tool_calls table."""
        llm_event = {
            "event_type": "llm_call",
            "model": "claude-3-5-sonnet-20241022",
            "trace_id": "t1",
            "session_id": "s1",
            "timestamp": datetime.now(UTC).isoformat(),
        }
        await storage.write_event(llm_event)
        results = await storage.query_tool_calls(QueryFilters())
        assert results == []


class TestSQLiteBackendLLM:
    """Tests for LLM call storage (migration 002)."""

    async def test_write_and_query_llm_event(self, storage: SQLiteBackend) -> None:
        event = {
            "event_type": "llm_call",
            "trace_id": "t1",
            "session_id": "s1",
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
        }
        await storage.write_event(event)
        results = await storage.query_llm_calls(LLMQueryFilters())
        assert len(results) == 1
        assert results[0]["model"] == "claude-3-5-sonnet-20241022"
        assert results[0]["latency_ms"] == pytest.approx(500.0)

    async def test_write_llm_event_direct(self, storage: SQLiteBackend) -> None:
        event = {
            "trace_id": "t2",
            "session_id": "s2",
            "model": "claude-3-opus-20240229",
            "latency_ms": 1200.0,
            "timestamp": datetime.now(UTC).isoformat(),
            "token_usage": {"input": 500, "output": 200},
        }
        await storage.write_llm_event(event)
        results = await storage.query_llm_calls(LLMQueryFilters())
        assert len(results) == 1
        assert results[0]["model"] == "claude-3-opus-20240229"

    async def test_filter_by_trace_id(self, storage: SQLiteBackend) -> None:
        e1 = {"trace_id": "t1", "session_id": "s1", "model": "claude", "latency_ms": 100.0,
               "timestamp": datetime.now(UTC).isoformat(), "token_usage": {}}
        e2 = {"trace_id": "t2", "session_id": "s2", "model": "claude", "latency_ms": 200.0,
               "timestamp": datetime.now(UTC).isoformat(), "token_usage": {}}
        await storage.write_llm_event(e1)
        await storage.write_llm_event(e2)
        results = await storage.query_llm_calls(LLMQueryFilters(trace_id="t1"))
        assert len(results) == 1
        assert results[0]["trace_id"] == "t1"

    async def test_filter_by_model(self, storage: SQLiteBackend) -> None:
        e1 = {"trace_id": "t1", "session_id": "s1", "model": "sonnet", "latency_ms": 100.0,
               "timestamp": datetime.now(UTC).isoformat(), "token_usage": {}}
        e2 = {"trace_id": "t2", "session_id": "s2", "model": "opus", "latency_ms": 200.0,
               "timestamp": datetime.now(UTC).isoformat(), "token_usage": {}}
        await storage.write_llm_event(e1)
        await storage.write_llm_event(e2)
        results = await storage.query_llm_calls(LLMQueryFilters(model="opus"))
        assert len(results) == 1
        assert results[0]["model"] == "opus"

    async def test_list_llm_summaries(self, storage: SQLiteBackend) -> None:
        for _ in range(3):
            await storage.write_llm_event({
                "trace_id": "t1", "session_id": "s1", "model": "sonnet",
                "latency_ms": 300.0, "timestamp": datetime.now(UTC).isoformat(),
                "token_usage": {"input": 100, "output": 50},
                "context_utilisation": 0.5,
            })
        await storage.write_llm_event({
            "trace_id": "t2", "session_id": "s2", "model": "opus",
            "latency_ms": 800.0, "timestamp": datetime.now(UTC).isoformat(),
            "token_usage": {"input": 500, "output": 200},
            "context_utilisation": 0.3,
        })
        summaries = await storage.list_llm_summaries()
        models = {s.model for s in summaries}
        assert "sonnet" in models
        assert "opus" in models
        sonnet = next(s for s in summaries if s.model == "sonnet")
        assert sonnet.call_count == 3
        assert sonnet.avg_latency_ms == pytest.approx(300.0)
        assert sonnet.avg_token_input == pytest.approx(100.0)

    async def test_token_cache_read_stored(self, storage: SQLiteBackend) -> None:
        await storage.write_llm_event({
            "trace_id": "t1", "session_id": "s1", "model": "claude",
            "latency_ms": 100.0, "timestamp": datetime.now(UTC).isoformat(),
            "token_usage": {"input": 100, "output": 50, "cache_read": 200},
        })
        results = await storage.query_llm_calls(LLMQueryFilters())
        assert results[0]["token_cache_read"] == 200
