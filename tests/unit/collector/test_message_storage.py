"""Tests for session_messages storage (write_message_event + migration 007)."""

from __future__ import annotations

import pytest

from anjor.collector.storage.sqlite import SQLiteBackend


@pytest.fixture
async def db() -> SQLiteBackend:
    backend = SQLiteBackend(db_path=":memory:", batch_size=1)
    await backend.connect()
    yield backend
    await backend.close()


def _msg(role: str = "user", preview: str = "hello", **kw: object) -> dict:
    return {
        "event_type": "message",
        "session_id": "sess-1",
        "trace_id": "trace-1",
        "agent_id": "default",
        "timestamp": "2025-01-01T12:00:00+00:00",
        "turn_index": 0,
        "role": role,
        "content_preview": preview,
        "token_count": None,
        "source": "claude_code",
        "project": "",
        **kw,
    }


@pytest.mark.asyncio
async def test_write_message_event_persisted(db: SQLiteBackend) -> None:
    await db.write_event(_msg())
    assert db._conn is not None
    async with db._conn.execute("SELECT role, content_preview FROM session_messages") as cur:
        rows = await cur.fetchall()
    assert len(rows) == 1
    assert rows[0][0] == "user"
    assert rows[0][1] == "hello"


@pytest.mark.asyncio
async def test_write_assistant_message(db: SQLiteBackend) -> None:
    await db.write_event(_msg(role="assistant", preview="I can help with that."))
    assert db._conn is not None
    async with db._conn.execute("SELECT role FROM session_messages") as cur:
        rows = await cur.fetchall()
    assert rows[0][0] == "assistant"


@pytest.mark.asyncio
async def test_token_count_stored(db: SQLiteBackend) -> None:
    await db.write_event(_msg(token_count=42))
    assert db._conn is not None
    async with db._conn.execute("SELECT token_count FROM session_messages") as cur:
        rows = await cur.fetchall()
    assert rows[0][0] == 42


@pytest.mark.asyncio
async def test_token_count_none_stored(db: SQLiteBackend) -> None:
    await db.write_event(_msg(token_count=None))
    assert db._conn is not None
    async with db._conn.execute("SELECT token_count FROM session_messages") as cur:
        rows = await cur.fetchall()
    assert rows[0][0] is None


@pytest.mark.asyncio
async def test_multiple_messages_stored(db: SQLiteBackend) -> None:
    await db.write_event(_msg(role="user", preview="hi"))
    await db.write_event(_msg(role="assistant", preview="hello there"))
    assert db._conn is not None
    async with db._conn.execute("SELECT role FROM session_messages ORDER BY id") as cur:
        rows = await cur.fetchall()
    assert [r[0] for r in rows] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_other_event_types_not_written_to_messages(db: SQLiteBackend) -> None:
    await db.write_event({"event_type": "llm_call", "model": "claude", "session_id": "s"})
    assert db._conn is not None
    async with db._conn.execute("SELECT COUNT(*) FROM session_messages") as cur:
        (count,) = await cur.fetchone()  # type: ignore
    assert count == 0
