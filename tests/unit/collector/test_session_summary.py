"""Tests for session_summaries storage and related query methods."""

from __future__ import annotations

import pytest

from anjor.collector.storage.sqlite import SQLiteBackend


@pytest.fixture
async def db() -> SQLiteBackend:
    backend = SQLiteBackend(db_path=":memory:", batch_size=1, batch_interval_ms=9999)
    await backend.connect()
    yield backend
    await backend.close()


async def _seed_tool_calls(
    db: SQLiteBackend, session_id: str, n: int = 3, failures: int = 1
) -> None:
    """Insert n tool_call events, with `failures` of them having status='error'."""
    assert db._conn is not None
    for i in range(n):
        status = "error" if i < failures else "success"
        await db._conn.execute(
            """INSERT INTO tool_calls (
                event_type, trace_id, session_id, agent_id, timestamp, sequence_no,
                tool_name, status, latency_ms, source, project
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                "tool_call",
                "trace-1",
                session_id,
                "default",
                f"2025-01-01T12:00:0{i}+00:00",
                i,
                f"tool_{i}",
                status,
                100.0,
                "",
                "",
            ),
        )
    await db._conn.commit()


async def _seed_llm_calls(db: SQLiteBackend, session_id: str) -> None:
    assert db._conn is not None
    await db._conn.execute(
        """INSERT INTO llm_calls (
            trace_id, session_id, agent_id, timestamp, sequence_no,
            model, latency_ms, token_input, token_output, source, project
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "trace-1",
            session_id,
            "default",
            "2025-01-01T12:00:00+00:00",
            0,
            "claude-sonnet-4-6",
            200.0,
            1000,
            500,
            "",
            "",
        ),
    )
    await db._conn.execute(
        """INSERT INTO llm_calls (
            trace_id, session_id, agent_id, timestamp, sequence_no,
            model, latency_ms, token_input, token_output, source, project
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "trace-1",
            session_id,
            "default",
            "2025-01-01T12:00:01+00:00",
            1,
            "claude-haiku-4-5-20251001",
            100.0,
            500,
            200,
            "",
            "",
        ),
    )
    await db._conn.commit()


# ── save_session_summary / get_session_summary ────────────────────────────────


@pytest.mark.asyncio
async def test_save_and_get_session_summary(db: SQLiteBackend) -> None:
    await db.save_session_summary(
        "sess-1", "The session completed the refactor.", "claude-haiku-4-5-20251001"
    )
    row = await db.get_session_summary("sess-1")

    assert row is not None
    assert row["session_id"] == "sess-1"
    assert row["summary"] == "The session completed the refactor."
    assert row["model"] == "claude-haiku-4-5-20251001"
    assert "created_at" in row


@pytest.mark.asyncio
async def test_get_session_summary_returns_none_for_unknown(db: SQLiteBackend) -> None:
    result = await db.get_session_summary("nonexistent-session")
    assert result is None


@pytest.mark.asyncio
async def test_save_session_summary_upserts(db: SQLiteBackend) -> None:
    await db.save_session_summary("sess-2", "First summary.", "model-a")
    await db.save_session_summary("sess-2", "Updated summary.", "model-b")

    row = await db.get_session_summary("sess-2")
    assert row is not None
    assert row["summary"] == "Updated summary."
    assert row["model"] == "model-b"


# ── get_session_messages ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_messages_returns_ordered_by_turn_index(db: SQLiteBackend) -> None:
    for turn_index, role, preview in [
        (2, "assistant", "reply"),
        (0, "user", "hi"),
        (1, "user", "follow up"),
    ]:
        await db.write_event(
            {
                "event_type": "message",
                "session_id": "sess-m",
                "trace_id": "t",
                "agent_id": "default",
                "timestamp": "2025-01-01T12:00:00+00:00",
                "turn_index": turn_index,
                "role": role,
                "content_preview": preview,
                "token_count": None,
                "source": "",
                "project": "",
            }
        )

    messages = await db.get_session_messages("sess-m")
    assert len(messages) == 3
    assert [m["turn_index"] for m in messages] == [0, 1, 2]
    assert messages[0]["role"] == "user"
    assert messages[2]["role"] == "assistant"


@pytest.mark.asyncio
async def test_get_session_messages_empty_for_unknown_session(db: SQLiteBackend) -> None:
    messages = await db.get_session_messages("unknown-session")
    assert messages == []


# ── get_session_tool_stats ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_tool_stats(db: SQLiteBackend) -> None:
    await _seed_tool_calls(db, "sess-t", n=5, failures=2)
    stats = await db.get_session_tool_stats("sess-t")

    assert stats["tool_call_count"] == 5
    assert stats["tool_success_count"] == 3


@pytest.mark.asyncio
async def test_get_session_tool_stats_empty_session(db: SQLiteBackend) -> None:
    stats = await db.get_session_tool_stats("empty-session")
    assert stats["tool_call_count"] == 0
    assert stats["tool_success_count"] == 0


@pytest.mark.asyncio
async def test_get_session_tool_stats_all_success(db: SQLiteBackend) -> None:
    await _seed_tool_calls(db, "sess-ok", n=4, failures=0)
    stats = await db.get_session_tool_stats("sess-ok")
    assert stats["tool_call_count"] == 4
    assert stats["tool_success_count"] == 4


# ── get_session_llm_stats ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_get_session_llm_stats(db: SQLiteBackend) -> None:
    await _seed_llm_calls(db, "sess-l")
    stats = await db.get_session_llm_stats("sess-l")

    assert stats["llm_call_count"] == 2
    # 1500 input tokens * $3/M + 700 output tokens * $15/M
    expected_cost = (1500 / 1_000_000) * 3.0 + (700 / 1_000_000) * 15.0
    assert abs(stats["estimated_cost_usd"] - expected_cost) < 1e-9
    assert set(stats["models_used"]) == {"claude-sonnet-4-6", "claude-haiku-4-5-20251001"}


@pytest.mark.asyncio
async def test_get_session_llm_stats_empty_session(db: SQLiteBackend) -> None:
    stats = await db.get_session_llm_stats("empty-session")
    assert stats["llm_call_count"] == 0
    assert stats["estimated_cost_usd"] == 0.0
    assert stats["models_used"] == []
