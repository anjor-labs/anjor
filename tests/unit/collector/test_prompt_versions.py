"""Unit tests for SQLiteBackend.list_prompt_versions."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from anjor.collector.storage.sqlite import SQLiteBackend


@pytest.fixture
async def storage() -> SQLiteBackend:
    backend = SQLiteBackend(db_path=":memory:", batch_size=1, batch_interval_ms=9999)
    await backend.connect()
    yield backend
    await backend.close()


def _llm_event(
    system_prompt_hash: str | None = "hash-a",
    model: str = "claude-3-5-sonnet",
    project: str = "",
    token_input: int = 1000,
    context_utilisation: float = 0.05,
) -> dict:
    return {
        "event_type": "llm_call",
        "trace_id": "trace-1",
        "session_id": "session-1",
        "agent_id": "default",
        "timestamp": datetime.now(UTC).isoformat(),
        "sequence_no": 0,
        "model": model,
        "latency_ms": 500.0,
        "token_usage": {"input": token_input, "output": 200},
        "context_window_used": int(200_000 * context_utilisation),
        "context_window_limit": 200_000,
        "context_utilisation": context_utilisation,
        "prompt_hash": "ph1",
        "system_prompt_hash": system_prompt_hash,
        "messages_count": 5,
        "finish_reason": "end_turn",
        "source": "",
        "project": project,
    }


class TestListPromptVersions:
    async def test_empty_returns_empty_list(self, storage: SQLiteBackend) -> None:
        result = await storage.list_prompt_versions()
        assert result == []

    async def test_returns_grouped_by_hash(self, storage: SQLiteBackend) -> None:
        await storage.write_llm_event(_llm_event(system_prompt_hash="hash-a", token_input=1000))
        await storage.write_llm_event(_llm_event(system_prompt_hash="hash-a", token_input=2000))
        await storage.write_llm_event(_llm_event(system_prompt_hash="hash-b", token_input=500))

        result = await storage.list_prompt_versions()

        assert len(result) == 2
        hashes = {r["system_prompt_hash"] for r in result}
        assert hashes == {"hash-a", "hash-b"}

        row_a = next(r for r in result if r["system_prompt_hash"] == "hash-a")
        assert row_a["call_count"] == 2
        assert row_a["avg_token_input"] == pytest.approx(1500.0)
        assert "first_seen" in row_a
        assert "last_seen" in row_a
        assert "models" in row_a
        assert "avg_context_utilisation" in row_a

    async def test_null_and_empty_hashes_excluded(self, storage: SQLiteBackend) -> None:
        await storage.write_llm_event(_llm_event(system_prompt_hash=None))
        await storage.write_llm_event(_llm_event(system_prompt_hash=""))
        await storage.write_llm_event(_llm_event(system_prompt_hash="real-hash"))

        result = await storage.list_prompt_versions()

        assert len(result) == 1
        assert result[0]["system_prompt_hash"] == "real-hash"

    async def test_project_filter(self, storage: SQLiteBackend) -> None:
        await storage.write_llm_event(_llm_event(system_prompt_hash="hash-a", project="proj-x"))
        await storage.write_llm_event(_llm_event(system_prompt_hash="hash-b", project="proj-y"))

        result = await storage.list_prompt_versions(project="proj-x")

        assert len(result) == 1
        assert result[0]["system_prompt_hash"] == "hash-a"

    async def test_limit_respected(self, storage: SQLiteBackend) -> None:
        for i in range(5):
            await storage.write_llm_event(_llm_event(system_prompt_hash=f"hash-{i}"))

        result = await storage.list_prompt_versions(limit=3)

        assert len(result) == 3
