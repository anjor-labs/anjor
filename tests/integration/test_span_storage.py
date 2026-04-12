"""Integration tests for SpanStorage — write, query, list_traces."""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from anjor.collector.storage.sqlite import SQLiteBackend


def _span(
    trace_id: str,
    span_id: str | None = None,
    parent_span_id: str | None = None,
    agent_name: str = "agent",
    span_kind: str = "root",
    status: str = "ok",
    token_input: int = 100,
    token_output: int = 50,
    started_at: str = "2026-04-12T10:00:00.000000+00:00",
    ended_at: str | None = "2026-04-12T10:00:01.000000+00:00",
) -> dict:
    return {
        "event_type": "agent_span",
        "span_id": span_id or str(uuid.uuid4()),
        "parent_span_id": parent_span_id,
        "trace_id": trace_id,
        "span_kind": span_kind,
        "agent_name": agent_name,
        "agent_role": "",
        "started_at": started_at,
        "ended_at": ended_at,
        "status": status,
        "failure_type": None,
        "token_input": token_input,
        "token_output": token_output,
        "tool_calls_count": 2,
        "llm_calls_count": 1,
    }


@pytest_asyncio.fixture
async def db() -> SQLiteBackend:  # type: ignore[misc]
    backend = SQLiteBackend(db_path=":memory:")
    await backend.connect()
    yield backend
    await backend.close()


class TestWriteAndQuerySpans:
    @pytest.mark.asyncio
    async def test_write_and_query_round_trip(self, db: SQLiteBackend) -> None:
        trace_id = str(uuid.uuid4())
        s = _span(trace_id=trace_id, agent_name="planner")
        await db.write_span(s)
        rows = await db.query_spans(trace_id)
        assert len(rows) == 1
        assert rows[0]["agent_name"] == "planner"
        assert rows[0]["trace_id"] == trace_id

    @pytest.mark.asyncio
    async def test_query_returns_correct_trace_only(self, db: SQLiteBackend) -> None:
        tid_a = str(uuid.uuid4())
        tid_b = str(uuid.uuid4())
        await db.write_span(_span(trace_id=tid_a, agent_name="a"))
        await db.write_span(_span(trace_id=tid_b, agent_name="b"))
        rows_a = await db.query_spans(tid_a)
        assert len(rows_a) == 1
        assert rows_a[0]["agent_name"] == "a"

    @pytest.mark.asyncio
    async def test_query_empty_trace(self, db: SQLiteBackend) -> None:
        rows = await db.query_spans(str(uuid.uuid4()))
        assert rows == []

    @pytest.mark.asyncio
    async def test_multiple_spans_same_trace(self, db: SQLiteBackend) -> None:
        trace_id = str(uuid.uuid4())
        root_id = str(uuid.uuid4())
        child_id = str(uuid.uuid4())
        await db.write_span(
            _span(
                trace_id=trace_id,
                span_id=root_id,
                agent_name="orchestrator",
                started_at="2026-04-12T10:00:00.000000+00:00",
            )
        )
        await db.write_span(
            _span(
                trace_id=trace_id,
                span_id=child_id,
                parent_span_id=root_id,
                agent_name="worker",
                span_kind="subagent",
                started_at="2026-04-12T10:00:01.000000+00:00",
            )
        )
        rows = await db.query_spans(trace_id)
        assert len(rows) == 2
        assert rows[0]["agent_name"] == "orchestrator"
        assert rows[1]["agent_name"] == "worker"

    @pytest.mark.asyncio
    async def test_token_counts_persisted(self, db: SQLiteBackend) -> None:
        trace_id = str(uuid.uuid4())
        await db.write_span(_span(trace_id=trace_id, token_input=1200, token_output=400))
        rows = await db.query_spans(trace_id)
        assert rows[0]["token_input"] == 1200
        assert rows[0]["token_output"] == 400

    @pytest.mark.asyncio
    async def test_error_status_persisted(self, db: SQLiteBackend) -> None:
        trace_id = str(uuid.uuid4())
        await db.write_span(_span(trace_id=trace_id, status="error"))
        rows = await db.query_spans(trace_id)
        assert rows[0]["status"] == "error"

    @pytest.mark.asyncio
    async def test_write_via_write_event(self, db: SQLiteBackend) -> None:
        trace_id = str(uuid.uuid4())
        s = _span(trace_id=trace_id, agent_name="via_write_event")
        await db.write_event(s)
        rows = await db.query_spans(trace_id)
        assert len(rows) == 1
        assert rows[0]["agent_name"] == "via_write_event"


class TestListTraces:
    @pytest.mark.asyncio
    async def test_empty(self, db: SQLiteBackend) -> None:
        summaries = await db.list_traces()
        assert summaries == []

    @pytest.mark.asyncio
    async def test_single_trace_summary(self, db: SQLiteBackend) -> None:
        trace_id = str(uuid.uuid4())
        await db.write_span(
            _span(
                trace_id=trace_id,
                agent_name="root_agent",
                token_input=500,
                token_output=200,
            )
        )
        summaries = await db.list_traces()
        assert len(summaries) == 1
        s = summaries[0]
        assert s.trace_id == trace_id
        assert s.root_agent_name == "root_agent"
        assert s.span_count == 1
        assert s.total_token_input == 500
        assert s.total_token_output == 200
        assert s.status == "ok"

    @pytest.mark.asyncio
    async def test_trace_status_error_if_any_span_errors(self, db: SQLiteBackend) -> None:
        trace_id = str(uuid.uuid4())
        root_id = str(uuid.uuid4())
        await db.write_span(_span(trace_id=trace_id, span_id=root_id, status="ok"))
        await db.write_span(
            _span(
                trace_id=trace_id,
                parent_span_id=root_id,
                status="error",
                span_kind="subagent",
            )
        )
        summaries = await db.list_traces()
        assert summaries[0].status == "error"

    @pytest.mark.asyncio
    async def test_multiple_traces(self, db: SQLiteBackend) -> None:
        for i in range(3):
            tid = str(uuid.uuid4())
            await db.write_span(
                _span(
                    trace_id=tid,
                    started_at=f"2026-04-12T10:0{i}:00.000000+00:00",
                )
            )
        summaries = await db.list_traces()
        assert len(summaries) == 3

    @pytest.mark.asyncio
    async def test_list_traces_pagination(self, db: SQLiteBackend) -> None:
        for _ in range(5):
            await db.write_span(_span(trace_id=str(uuid.uuid4())))
        page1 = await db.list_traces(limit=3, offset=0)
        page2 = await db.list_traces(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 2

    @pytest.mark.asyncio
    async def test_token_totals_aggregated(self, db: SQLiteBackend) -> None:
        trace_id = str(uuid.uuid4())
        root_id = str(uuid.uuid4())
        await db.write_span(
            _span(
                trace_id=trace_id,
                span_id=root_id,
                token_input=300,
                token_output=100,
            )
        )
        await db.write_span(
            _span(
                trace_id=trace_id,
                parent_span_id=root_id,
                token_input=200,
                token_output=80,
                span_kind="subagent",
            )
        )
        summaries = await db.list_traces()
        assert summaries[0].total_token_input == 500
        assert summaries[0].total_token_output == 180
