"""Unit tests for anjor.mcp: is_mcp_tool and parse_mcp_tool_name."""

from __future__ import annotations

import pytest

import anjor
from anjor.mcp import is_mcp_tool, parse_mcp_tool_name

# ---------------------------------------------------------------------------
# is_mcp_tool
# ---------------------------------------------------------------------------


class TestIsMcpTool:
    def test_standard_name(self) -> None:
        assert is_mcp_tool("mcp__github__create_pr")

    def test_server_with_single_underscores(self) -> None:
        assert is_mcp_tool("mcp__brave_search__web_search")

    def test_tool_with_single_underscores(self) -> None:
        assert is_mcp_tool("mcp__github__create_pull_request")

    def test_tool_with_double_underscores(self) -> None:
        assert is_mcp_tool("mcp__server__tool__with__double__underscores")

    def test_minimal_server_and_tool(self) -> None:
        assert is_mcp_tool("mcp__s__t")

    def test_filesystem_server(self) -> None:
        assert is_mcp_tool("mcp__filesystem__read_file")

    def test_postgres_server(self) -> None:
        assert is_mcp_tool("mcp__postgres__list_tables")

    # -- non-MCP names -------------------------------------------------------

    def test_plain_tool_name(self) -> None:
        assert not is_mcp_tool("web_search")

    def test_no_mcp_prefix(self) -> None:
        assert not is_mcp_tool("github__create_pr")

    def test_empty_string(self) -> None:
        assert not is_mcp_tool("")

    def test_mcp_prefix_only(self) -> None:
        assert not is_mcp_tool("mcp__")

    def test_server_only_no_second_separator(self) -> None:
        assert not is_mcp_tool("mcp__github")

    def test_missing_second_separator(self) -> None:
        assert not is_mcp_tool("mcp__notvalid")

    def test_empty_server_segment(self) -> None:
        # "mcp____tool" → server segment between "mcp__" and next "__" is empty
        assert not is_mcp_tool("mcp____tool")

    def test_empty_tool_segment(self) -> None:
        # "mcp__server__" → tool segment is empty
        assert not is_mcp_tool("mcp__server__")

    def test_case_sensitive_prefix(self) -> None:
        assert not is_mcp_tool("MCP__github__create_pr")

    def test_mixed_case_prefix(self) -> None:
        assert not is_mcp_tool("Mcp__github__create_pr")

    def test_single_underscore_separator(self) -> None:
        # Only double underscore is valid separator
        assert not is_mcp_tool("mcp_github_create_pr")


# ---------------------------------------------------------------------------
# parse_mcp_tool_name
# ---------------------------------------------------------------------------


class TestParseMcpToolName:
    def test_standard_name(self) -> None:
        assert parse_mcp_tool_name("mcp__github__create_pr") == ("github", "create_pr")

    def test_server_with_underscores(self) -> None:
        assert parse_mcp_tool_name("mcp__brave_search__web_search") == (
            "brave_search",
            "web_search",
        )

    def test_tool_with_underscores(self) -> None:
        assert parse_mcp_tool_name("mcp__github__create_pull_request") == (
            "github",
            "create_pull_request",
        )

    def test_tool_with_double_underscores_first_sep_wins(self) -> None:
        # First __ after mcp__ is the boundary; the rest goes to tool
        assert parse_mcp_tool_name("mcp__server__tool__with__more") == (
            "server",
            "tool__with__more",
        )

    def test_ambiguous_server_first_segment_wins(self) -> None:
        # mcp__a__b__c → server=a, tool=b__c
        assert parse_mcp_tool_name("mcp__a__b__c") == ("a", "b__c")

    def test_minimal_valid(self) -> None:
        assert parse_mcp_tool_name("mcp__s__t") == ("s", "t")

    def test_filesystem_server(self) -> None:
        assert parse_mcp_tool_name("mcp__filesystem__read_file") == (
            "filesystem",
            "read_file",
        )

    def test_postgres_server(self) -> None:
        assert parse_mcp_tool_name("mcp__postgres__list_tables") == (
            "postgres",
            "list_tables",
        )

    def test_returns_tuple(self) -> None:
        result = parse_mcp_tool_name("mcp__github__create_pr")
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_server_is_first_element(self) -> None:
        result = parse_mcp_tool_name("mcp__filesystem__read_file")
        assert result is not None
        assert result[0] == "filesystem"

    def test_tool_is_second_element(self) -> None:
        result = parse_mcp_tool_name("mcp__filesystem__read_file")
        assert result is not None
        assert result[1] == "read_file"

    # -- returns None cases --------------------------------------------------

    def test_no_prefix_returns_none(self) -> None:
        assert parse_mcp_tool_name("web_search") is None

    def test_empty_string_returns_none(self) -> None:
        assert parse_mcp_tool_name("") is None

    def test_mcp_prefix_only_returns_none(self) -> None:
        assert parse_mcp_tool_name("mcp__") is None

    def test_server_only_no_separator_returns_none(self) -> None:
        assert parse_mcp_tool_name("mcp__github") is None

    def test_missing_second_separator_returns_none(self) -> None:
        assert parse_mcp_tool_name("mcp__notvalid") is None

    def test_empty_server_segment_returns_none(self) -> None:
        assert parse_mcp_tool_name("mcp____tool") is None

    def test_empty_tool_segment_returns_none(self) -> None:
        assert parse_mcp_tool_name("mcp__server__") is None

    def test_uppercase_prefix_returns_none(self) -> None:
        assert parse_mcp_tool_name("MCP__github__create_pr") is None


# ---------------------------------------------------------------------------
# Parametrized agreement: is_mcp_tool ↔ parse_mcp_tool_name must always agree
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "name",
    [
        "mcp__github__create_pr",
        "mcp__brave_search__web_search",
        "mcp__server__tool__with__extras",
        "mcp__filesystem__read_file",
        "mcp__s__t",
        "mcp__postgres__list_tables",
    ],
)
def test_valid_names_both_agree(name: str) -> None:
    assert is_mcp_tool(name) is True
    assert parse_mcp_tool_name(name) is not None


@pytest.mark.parametrize(
    "name",
    [
        "web_search",
        "mcp__notvalid",
        "mcp__",
        "mcp____tool",
        "mcp__server__",
        "",
        "MCP__github__create_pr",
        "github__create_pr",
        "mcp_github_create_pr",
    ],
)
def test_invalid_names_both_agree(name: str) -> None:
    assert is_mcp_tool(name) is False
    assert parse_mcp_tool_name(name) is None


# ---------------------------------------------------------------------------
# Public API surface: helpers accessible via top-level import
# ---------------------------------------------------------------------------


class TestPublicAPIExposure:
    def test_is_mcp_tool_importable_from_anjor(self) -> None:
        assert callable(anjor.is_mcp_tool)

    def test_parse_mcp_tool_name_importable_from_anjor(self) -> None:
        assert callable(anjor.parse_mcp_tool_name)

    def test_is_mcp_tool_in_all(self) -> None:
        assert "is_mcp_tool" in anjor.__all__

    def test_parse_mcp_tool_name_in_all(self) -> None:
        assert "parse_mcp_tool_name" in anjor.__all__

    def test_top_level_is_mcp_tool_works(self) -> None:
        assert anjor.is_mcp_tool("mcp__github__create_pr") is True

    def test_top_level_parse_mcp_tool_name_works(self) -> None:
        assert anjor.parse_mcp_tool_name("mcp__github__create_pr") == ("github", "create_pr")
