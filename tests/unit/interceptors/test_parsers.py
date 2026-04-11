"""Unit tests for parsers and ParserRegistry."""

from __future__ import annotations

from agentscope.core.events.tool_call import FailureType, ToolCallEvent, ToolCallStatus
from agentscope.interceptors.parsers.anthropic import AnthropicParser, _sanitise
from agentscope.interceptors.parsers.openai import OpenAIParser
from agentscope.interceptors.parsers.registry import ParserRegistry, build_default_registry

# ---------------------------------------------------------------------------
# AnthropicParser tests
# ---------------------------------------------------------------------------

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

_TOOL_USE_RESPONSE = {
    "id": "msg_123",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "tool_use",
            "id": "toolu_01",
            "name": "web_search",
            "input": {"query": "latest AI news"},
        }
    ],
    "usage": {"input_tokens": 150, "output_tokens": 50},
}

_REQUEST_BODY = {
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Search for AI news"}],
}


class TestAnthropicParser:
    def setup_method(self) -> None:
        self.parser = AnthropicParser()

    def test_can_parse_anthropic_url(self) -> None:
        assert self.parser.can_parse(_ANTHROPIC_URL) is True

    def test_cannot_parse_other_url(self) -> None:
        assert self.parser.can_parse("https://api.openai.com/v1/chat") is False

    def test_parses_tool_use_block(self) -> None:
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=250.0,
            status_code=200,
        )
        assert len(events) == 1
        assert isinstance(events[0], ToolCallEvent)

    def test_tool_name_extracted(self) -> None:
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=250.0,
            status_code=200,
        )
        assert events[0].tool_name == "web_search"  # type: ignore[union-attr]

    def test_latency_preserved(self) -> None:
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=333.0,
            status_code=200,
        )
        assert events[0].latency_ms == 333.0  # type: ignore[union-attr]

    def test_token_usage_extracted(self) -> None:
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=100.0,
            status_code=200,
        )
        event = events[0]
        assert isinstance(event, ToolCallEvent)
        assert event.token_usage is not None
        assert event.token_usage.input == 150
        assert event.token_usage.output == 50

    def test_status_success_on_200(self) -> None:
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=100.0,
            status_code=200,
        )
        assert events[0].status == ToolCallStatus.SUCCESS  # type: ignore[union-attr]

    def test_status_failure_on_500(self) -> None:
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=100.0,
            status_code=500,
        )
        assert events[0].status == ToolCallStatus.FAILURE  # type: ignore[union-attr]

    def test_multiple_tool_use_blocks(self) -> None:
        response = {
            "content": [
                {"type": "tool_use", "id": "1", "name": "search", "input": {}},
                {"type": "tool_use", "id": "2", "name": "lookup", "input": {}},
            ],
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=response,
            latency_ms=100.0,
            status_code=200,
        )
        assert len(events) == 2
        names = {e.tool_name for e in events}  # type: ignore[union-attr]
        assert names == {"search", "lookup"}

    def test_no_tool_use_blocks_returns_empty(self) -> None:
        response = {"content": [{"type": "text", "text": "Hello!"}]}
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=response,
            latency_ms=100.0,
            status_code=200,
        )
        assert events == []

    def test_api_error_response(self) -> None:
        response = {"error": {"type": "invalid_request_error", "message": "bad input"}}
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=response,
            latency_ms=50.0,
            status_code=400,
        )
        assert len(events) == 1
        assert events[0].status == ToolCallStatus.FAILURE  # type: ignore[union-attr]
        assert events[0].failure_type == FailureType.API_ERROR  # type: ignore[union-attr]

    def test_schema_hash_populated(self) -> None:
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=100.0,
            status_code=200,
        )
        event = events[0]
        assert isinstance(event, ToolCallEvent)
        assert event.input_schema_hash != ""

    def test_trace_id_from_metadata(self) -> None:
        req = {**_REQUEST_BODY, "metadata": {"trace_id": "my-trace"}}
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=req,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=100.0,
            status_code=200,
        )
        assert events[0].trace_id == "my-trace"


class TestSanitise:
    def test_redacts_api_key(self) -> None:
        result = _sanitise({"api_key": "sk-secret123", "query": "hello"})
        assert result["api_key"] == "[REDACTED]"
        assert result["query"] == "hello"

    def test_redacts_nested_sensitive_parent(self) -> None:
        # "auth" key itself matches *auth*, so whole value is redacted
        result = _sanitise({"auth": {"bearer": "token123", "user": "alice"}})
        assert result["auth"] == "[REDACTED]"

    def test_redacts_nested_sensitive_child(self) -> None:
        # "data" key doesn't match patterns, so we recurse into it
        result = _sanitise({"data": {"api_key": "sk-123", "user": "alice"}})
        assert result["data"]["api_key"] == "[REDACTED]"
        assert result["data"]["user"] == "alice"

    def test_redacts_in_list(self) -> None:
        result = _sanitise({"items": [{"password": "secret", "name": "x"}]})  # noqa: S105
        assert result["items"][0]["password"] == "[REDACTED]"  # noqa: S105
        assert result["items"][0]["name"] == "x"

    def test_case_insensitive(self) -> None:
        result = _sanitise({"API_KEY": "value"})
        assert result["API_KEY"] == "[REDACTED]"

    def test_non_sensitive_keys_pass_through(self) -> None:
        result = _sanitise({"query": "hello", "limit": 10})
        assert result == {"query": "hello", "limit": 10}


# ---------------------------------------------------------------------------
# OpenAIParser stub tests
# ---------------------------------------------------------------------------


class TestOpenAIParser:
    def test_can_parse_openai_url(self) -> None:
        parser = OpenAIParser()
        assert parser.can_parse("https://api.openai.com/v1/chat/completions") is True

    def test_returns_empty_list(self) -> None:
        parser = OpenAIParser()
        events = parser.parse("https://api.openai.com/v1/chat", {}, {}, 100.0, 200)
        assert events == []


# ---------------------------------------------------------------------------
# ParserRegistry tests
# ---------------------------------------------------------------------------


class TestParserRegistry:
    def test_find_anthropic_parser(self) -> None:
        reg = build_default_registry()
        parser = reg.find_parser(_ANTHROPIC_URL)
        assert isinstance(parser, AnthropicParser)

    def test_no_parser_for_unknown_url(self) -> None:
        reg = ParserRegistry()
        assert reg.find_parser("https://example.com/api") is None

    def test_parse_returns_empty_for_no_match(self) -> None:
        reg = ParserRegistry()
        result = reg.parse("https://example.com", {}, {}, 100.0, 200)
        assert result == []

    def test_parse_delegates_to_parser(self) -> None:
        reg = build_default_registry()
        events = reg.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=100.0,
            status_code=200,
        )
        assert len(events) == 1

    def test_first_matching_parser_wins(self) -> None:
        reg = ParserRegistry()
        reg.register(AnthropicParser())
        reg.register(OpenAIParser())
        parser = reg.find_parser(_ANTHROPIC_URL)
        assert isinstance(parser, AnthropicParser)
