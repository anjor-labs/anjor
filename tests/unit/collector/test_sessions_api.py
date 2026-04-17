"""Tests for GET /sessions and GET /sessions/{session_id}/replay."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from anjor.collector.api.app import create_app
from anjor.collector.service import CollectorService
from anjor.collector.storage.sqlite import SQLiteBackend
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.pipeline import EventPipeline


@pytest.fixture
def client() -> TestClient:
    cfg = AnjorConfig(db_path=":memory:", batch_size=1, batch_interval_ms=9999)  # type: ignore
    svc = CollectorService(
        config=cfg,
        storage=SQLiteBackend(db_path=":memory:", batch_size=1),
        pipeline=EventPipeline(),
    )
    return TestClient(create_app(config=cfg, service=svc))


@pytest.fixture
async def db_with_data() -> SQLiteBackend:
    backend = SQLiteBackend(db_path=":memory:", batch_size=1)
    await backend.connect()

    await backend.write_event(
        {
            "event_type": "message",
            "session_id": "sess-A",
            "trace_id": "sess-A",
            "agent_id": "default",
            "timestamp": "2025-01-01T10:00:00+00:00",
            "turn_index": 0,
            "role": "user",
            "content_preview": "Hello Claude",
            "token_count": None,
            "source": "claude_code",
            "project": "proj1",
        }
    )
    await backend.write_event(
        {
            "event_type": "message",
            "session_id": "sess-A",
            "trace_id": "sess-A",
            "agent_id": "default",
            "timestamp": "2025-01-01T10:00:01+00:00",
            "turn_index": 1,
            "role": "assistant",
            "content_preview": "Hi! How can I help?",
            "token_count": 10,
            "source": "claude_code",
            "project": "proj1",
        }
    )
    yield backend
    await backend.close()


class TestListSessions:
    def test_empty_returns_empty_list(self, client: TestClient) -> None:
        with client:
            resp = client.get("/sessions")
        assert resp.status_code == 200
        assert resp.json() == []

    @pytest.mark.asyncio
    async def test_list_sessions_returns_sessions(self, db_with_data: SQLiteBackend) -> None:
        rows = await db_with_data.list_sessions()
        assert len(rows) == 1
        assert rows[0]["session_id"] == "sess-A"
        assert rows[0]["message_count"] == 2
        assert rows[0]["project"] == "proj1"

    @pytest.mark.asyncio
    async def test_limit_respected(self, db_with_data: SQLiteBackend) -> None:
        rows = await db_with_data.list_sessions(limit=1, offset=0)
        assert len(rows) == 1

    @pytest.mark.asyncio
    async def test_offset_works(self, db_with_data: SQLiteBackend) -> None:
        rows = await db_with_data.list_sessions(limit=10, offset=10)
        assert rows == []


class TestGetReplay:
    @pytest.mark.asyncio
    async def test_replay_returns_turns_in_order(self, db_with_data: SQLiteBackend) -> None:
        turns = await db_with_data.get_session_replay("sess-A")
        assert len(turns) == 2
        assert turns[0]["kind"] == "user"
        assert turns[0]["content_preview"] == "Hello Claude"
        assert turns[1]["kind"] == "assistant"
        assert turns[1]["token_count"] == 10

    @pytest.mark.asyncio
    async def test_unknown_session_returns_empty(self, db_with_data: SQLiteBackend) -> None:
        turns = await db_with_data.get_session_replay("no-such-session")
        assert turns == []

    def test_api_404_on_missing_session(self, client: TestClient) -> None:
        with client:
            resp = client.get("/sessions/no-such-session/replay")
        assert resp.status_code == 404

    @pytest.mark.asyncio
    async def test_tool_turns_included(self, db_with_data: SQLiteBackend) -> None:
        # Insert a tool call with same session_id
        await db_with_data.write_event(
            {
                "event_type": "tool_call",
                "session_id": "sess-A",
                "trace_id": "sess-A",
                "agent_id": "default",
                "timestamp": "2025-01-01T10:00:02+00:00",
                "sequence_no": 0,
                "tool_name": "Bash",
                "status": "success",
                "failure_type": None,
                "latency_ms": 120.0,
                "input_payload": {},
                "output_payload": {},
                "input_schema_hash": "",
                "output_schema_hash": "",
                "source": "claude_code",
                "project": "proj1",
            }
        )
        await db_with_data._flush()
        turns = await db_with_data.get_session_replay("sess-A")
        tool_turns = [t for t in turns if t["kind"] == "tool"]
        assert len(tool_turns) == 1
        assert tool_turns[0]["tool_name"] == "Bash"
        assert tool_turns[0]["latency_ms"] == 120.0
