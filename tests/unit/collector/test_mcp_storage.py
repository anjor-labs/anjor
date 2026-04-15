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


# ---------------------------------------------------------------------------
# Edge-case / malformed tool names
# ---------------------------------------------------------------------------


class TestMalformedMCPNames:
    """Tools that start with mcp__ but don't follow the full convention must
    be silently excluded from /mcp aggregates — no exceptions, no blank rows."""

    async def test_no_second_separator_excluded_from_servers(self, storage: SQLiteBackend) -> None:
        """mcp__notvalid has no second __ → server_name would be empty → excluded."""
        await storage.write_event(mcp_event("mcp__notvalid"))
        await storage.write_event(mcp_event("mcp__github__create_pr"))
        result = await storage.list_mcp_server_summaries()
        server_names = {s.server_name for s in result}
        assert "" not in server_names
        assert server_names == {"github"}

    async def test_no_second_separator_excluded_from_tools(self, storage: SQLiteBackend) -> None:
        await storage.write_event(mcp_event("mcp__notvalid"))
        await storage.write_event(mcp_event("mcp__github__create_pr"))
        result = await storage.list_mcp_tool_summaries()
        tool_names = {t.tool_name for t in result}
        assert "mcp__notvalid" not in tool_names
        assert "mcp__github__create_pr" in tool_names

    async def test_empty_server_segment_excluded_from_servers(self, storage: SQLiteBackend) -> None:
        """mcp____tool has an empty server segment → excluded."""
        await storage.write_event(mcp_event("mcp____tool"))
        result = await storage.list_mcp_server_summaries()
        assert result == []

    async def test_empty_tool_segment_excluded_from_tools(self, storage: SQLiteBackend) -> None:
        """mcp__server__ has an empty tool segment → excluded."""
        await storage.write_event(mcp_event("mcp__server__"))
        result = await storage.list_mcp_tool_summaries()
        assert result == []

    async def test_malformed_names_do_not_raise(self, storage: SQLiteBackend) -> None:
        """Writing and querying any malformed name must never raise an exception."""
        for name in ["mcp__notvalid", "mcp____tool", "mcp__server__", "mcp__"]:
            await storage.write_event(mcp_event(name))
        # Both queries must complete without error
        servers = await storage.list_mcp_server_summaries()
        tools = await storage.list_mcp_tool_summaries()
        assert servers == []
        assert tools == []

    async def test_tool_with_double_underscores_in_name_included(
        self, storage: SQLiteBackend
    ) -> None:
        """Tool names containing __ are valid — only the first __ is the separator."""
        await storage.write_event(mcp_event("mcp__server__tool__with__extras"))
        result = await storage.list_mcp_tool_summaries()
        assert len(result) == 1
        assert result[0].server_name == "server"
        assert result[0].short_name == "tool__with__extras"

    async def test_server_with_underscores_included(self, storage: SQLiteBackend) -> None:
        """Server names with single underscores (e.g. brave_search) are valid."""
        await storage.write_event(mcp_event("mcp__brave_search__web_search"))
        result = await storage.list_mcp_server_summaries()
        assert len(result) == 1
        assert result[0].server_name == "brave_search"
