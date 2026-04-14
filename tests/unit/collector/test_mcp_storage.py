"""Unit tests for MCP storage methods (list_mcp_server_summaries, list_mcp_tool_summaries)."""

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


def mcp_event(tool_name: str, status: str = "success", latency_ms: float = 100.0) -> dict:
    return {
        "event_type": "tool_call",
        "trace_id": "trace-mcp",
        "session_id": "session-mcp",
        "agent_id": "default",
        "timestamp": datetime.now(UTC).isoformat(),
        "sequence_no": 0,
        "tool_name": tool_name,
        "status": status,
        "failure_type": None if status == "success" else "unknown",
        "latency_ms": latency_ms,
        "input_payload": {},
        "output_payload": {},
        "input_schema_hash": "",
        "output_schema_hash": "",
    }


class TestMCPServerSummaries:
    async def test_empty_when_no_mcp_tools(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("regular_tool"))
        result = await storage.list_mcp_server_summaries()
        assert result == []

    async def test_groups_by_server(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("mcp__github__create_pr"))
        await storage.write_event(mcp_event("mcp__github__search_issues"))
        await storage.write_event(mcp_event("mcp__filesystem__read_file"))
        result = await storage.list_mcp_server_summaries()
        server_names = {s.server_name for s in result}
        assert server_names == {"github", "filesystem"}

    async def test_call_count_per_server(self, storage: SQLiteBackend) -> None:
        for _ in range(3):
            await storage.write_event(mcp_event("mcp__github__create_pr"))
        await storage.write_event(mcp_event("mcp__slack__post_message"))
        result = await storage.list_mcp_server_summaries()
        github = next(s for s in result if s.server_name == "github")
        assert github.call_count == 3

    async def test_tool_count_per_server(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("mcp__github__create_pr"))
        await storage.write_event(mcp_event("mcp__github__create_pr"))
        await storage.write_event(mcp_event("mcp__github__search_issues"))
        result = await storage.list_mcp_server_summaries()
        github = next(s for s in result if s.server_name == "github")
        assert github.tool_count == 2

    async def test_success_count(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("mcp__github__create_pr", status="success"))
        await storage.write_event(mcp_event("mcp__github__create_pr", status="success"))
        await storage.write_event(mcp_event("mcp__github__create_pr", status="failure"))
        result = await storage.list_mcp_server_summaries()
        github = next(s for s in result if s.server_name == "github")
        assert github.success_count == 2
        assert github.success_rate == pytest.approx(2 / 3)

    async def test_excludes_non_mcp_tools(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("web_search"))
        await storage.write_event(mcp_event("mcp__brave__search"))
        result = await storage.list_mcp_server_summaries()
        assert len(result) == 1
        assert result[0].server_name == "brave"

    async def test_sorted_by_call_count_desc(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("mcp__slack__post_message"))
        for _ in range(5):
            await storage.write_event(mcp_event("mcp__github__create_pr"))
        result = await storage.list_mcp_server_summaries()
        assert result[0].server_name == "github"
        assert result[1].server_name == "slack"


class TestMCPToolSummaries:
    async def test_empty_when_no_mcp_tools(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("regular_tool"))
        result = await storage.list_mcp_tool_summaries()
        assert result == []

    async def test_groups_by_full_tool_name(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("mcp__github__create_pr"))
        await storage.write_event(mcp_event("mcp__github__create_pr"))
        await storage.write_event(mcp_event("mcp__github__search_issues"))
        result = await storage.list_mcp_tool_summaries()
        tool_names = {t.tool_name for t in result}
        assert tool_names == {"mcp__github__create_pr", "mcp__github__search_issues"}

    async def test_server_name_extracted(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("mcp__filesystem__read_file"))
        result = await storage.list_mcp_tool_summaries()
        assert result[0].server_name == "filesystem"

    async def test_short_name_property(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("mcp__postgres__list_tables"))
        result = await storage.list_mcp_tool_summaries()
        assert result[0].short_name == "list_tables"

    async def test_call_count(self, storage: SQLiteBackend) -> None:
        for _ in range(4):
            await storage.write_event(mcp_event("mcp__slack__post_message"))
        result = await storage.list_mcp_tool_summaries()
        assert result[0].call_count == 4

    async def test_success_rate(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("mcp__github__create_pr", status="success"))
        await storage.write_event(mcp_event("mcp__github__create_pr", status="failure"))
        result = await storage.list_mcp_tool_summaries()
        tool = result[0]
        assert tool.success_rate == pytest.approx(0.5)

    async def test_sorted_by_call_count_desc(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("mcp__github__search_issues"))
        for _ in range(3):
            await storage.write_event(mcp_event("mcp__github__create_pr"))
        result = await storage.list_mcp_tool_summaries()
        assert result[0].tool_name == "mcp__github__create_pr"
