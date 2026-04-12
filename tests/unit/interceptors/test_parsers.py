"""Unit tests for parsers and ParserRegistry."""

from __future__ import annotations

import pytest

from anjor.core.events.llm_call import LLMCallEvent
from anjor.core.events.tool_call import FailureType, ToolCallEvent, ToolCallStatus
from anjor.interceptors.parsers.anthropic import AnthropicParser, _sanitise
from anjor.interceptors.parsers.openai import OpenAIParser
from anjor.interceptors.parsers.registry import ParserRegistry, build_default_registry

# ---------------------------------------------------------------------------
# Fixtures
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
    "stop_reason": "tool_use",
    "usage": {"input_tokens": 150, "output_tokens": 50},
}

_REQUEST_BODY = {
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Search for AI news"}],
}

_TEXT_RESPONSE = {
    "id": "msg_456",
    "content": [{"type": "text", "text": "Hello!"}],
    "stop_reason": "end_turn",
    "usage": {"input_tokens": 20, "output_tokens": 10},
}


# ---------------------------------------------------------------------------
# AnthropicParser — LLMCallEvent (emitted for every call)
# ---------------------------------------------------------------------------


class TestAnthropicParserLLMCallEvent:
    def setup_method(self) -> None:
        self.parser = AnthropicParser()

    def _parse_tool(self, **kwargs: object) -> list[object]:
        return self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=250.0,
            status_code=200,
            **kwargs,  # type: ignore[arg-type]
        )

    def test_llm_event_always_emitted_for_tool_response(self) -> None:
        events = self._parse_tool()
        # First event is always the LLMCallEvent
        assert isinstance(events[0], LLMCallEvent)

    def test_llm_event_emitted_for_text_response(self) -> None:
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=_TEXT_RESPONSE,
            latency_ms=120.0,
            status_code=200,
        )
        assert len(events) == 1
        assert isinstance(events[0], LLMCallEvent)

    def test_llm_event_model_extracted(self) -> None:
        events = self._parse_tool()
        assert isinstance(events[0], LLMCallEvent)
        assert events[0].model == "claude-3-5-sonnet-20241022"

    def test_llm_event_latency(self) -> None:
        events = self._parse_tool()
        assert isinstance(events[0], LLMCallEvent)
        assert events[0].latency_ms == 250.0

    def test_llm_event_token_usage(self) -> None:
        events = self._parse_tool()
        assert isinstance(events[0], LLMCallEvent)
        assert events[0].token_usage is not None
        assert events[0].token_usage.input == 150
        assert events[0].token_usage.output == 50

    def test_llm_event_context_window_utilisation(self) -> None:
        events = self._parse_tool()
        assert isinstance(events[0], LLMCallEvent)
        # 150+50=200 tokens used / 200_000 limit → 0.001
        assert events[0].context_utilisation == pytest.approx(0.001)
        assert events[0].context_window_limit == 200_000

    def test_llm_event_finish_reason(self) -> None:
        events = self._parse_tool()
        assert isinstance(events[0], LLMCallEvent)
        assert events[0].finish_reason == "tool_use"

    def test_llm_event_messages_count(self) -> None:
        events = self._parse_tool()
        assert isinstance(events[0], LLMCallEvent)
        assert events[0].messages_count == 1

    def test_llm_event_prompt_hash_populated(self) -> None:
        events = self._parse_tool()
        assert isinstance(events[0], LLMCallEvent)
        assert events[0].prompt_hash != ""

    def test_llm_event_system_prompt_hash_absent(self) -> None:
        events = self._parse_tool()
        assert isinstance(events[0], LLMCallEvent)
        assert events[0].system_prompt_hash is None

    def test_llm_event_system_prompt_hash_present(self) -> None:
        req = {**_REQUEST_BODY, "system": "You are a helpful assistant."}
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=req,
            response_body=_TEXT_RESPONSE,
            latency_ms=100.0,
            status_code=200,
        )
        assert isinstance(events[0], LLMCallEvent)
        assert events[0].system_prompt_hash is not None
        assert len(events[0].system_prompt_hash) == 64  # SHA-256 hex

    def test_llm_event_system_prompt_hash_deterministic(self) -> None:
        req = {**_REQUEST_BODY, "system": "You are a helpful assistant."}
        e1 = self.parser.parse(_ANTHROPIC_URL, req, _TEXT_RESPONSE, 100.0, 200)
        e2 = self.parser.parse(_ANTHROPIC_URL, req, _TEXT_RESPONSE, 200.0, 200)
        assert isinstance(e1[0], LLMCallEvent)
        assert isinstance(e2[0], LLMCallEvent)
        assert e1[0].system_prompt_hash == e2[0].system_prompt_hash

    def test_llm_event_trace_id_from_metadata(self) -> None:
        req = {**_REQUEST_BODY, "metadata": {"trace_id": "trace-123"}}
        events = self.parser.parse(_ANTHROPIC_URL, req, _TEXT_RESPONSE, 100.0, 200)
        assert isinstance(events[0], LLMCallEvent)
        assert events[0].trace_id == "trace-123"

    def test_llm_event_cache_read_tokens(self) -> None:
        resp = {
            **_TEXT_RESPONSE,
            "usage": {"input_tokens": 100, "output_tokens": 50, "cache_read_input_tokens": 200},
        }
        events = self.parser.parse(_ANTHROPIC_URL, _REQUEST_BODY, resp, 100.0, 200)
        assert isinstance(events[0], LLMCallEvent)
        assert events[0].token_usage is not None
        assert events[0].token_usage.cache_read == 200


# ---------------------------------------------------------------------------
# AnthropicParser — ToolCallEvent behaviour
# ---------------------------------------------------------------------------


class TestAnthropicParserToolCallEvent:
    def setup_method(self) -> None:
        self.parser = AnthropicParser()

    def _parse_tool(self, status_code: int = 200, latency_ms: float = 250.0) -> list[object]:
        return self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=latency_ms,
            status_code=status_code,
        )

    def test_tool_call_event_is_second_event(self) -> None:
        events = self._parse_tool()
        # events[0] = LLMCallEvent, events[1] = ToolCallEvent
        assert len(events) == 2
        assert isinstance(events[1], ToolCallEvent)

    def test_tool_name_extracted(self) -> None:
        events = self._parse_tool()
        assert isinstance(events[1], ToolCallEvent)
        assert events[1].tool_name == "web_search"

    def test_latency_preserved(self) -> None:
        events = self._parse_tool(latency_ms=333.0)
        assert isinstance(events[1], ToolCallEvent)
        assert events[1].latency_ms == 333.0

    def test_token_usage_extracted(self) -> None:
        events = self._parse_tool()
        event = events[1]
        assert isinstance(event, ToolCallEvent)
        assert event.token_usage is not None
        assert event.token_usage.input == 150
        assert event.token_usage.output == 50

    def test_status_success_on_200(self) -> None:
        events = self._parse_tool(status_code=200)
        assert isinstance(events[1], ToolCallEvent)
        assert events[1].status == ToolCallStatus.SUCCESS

    def test_status_failure_on_500(self) -> None:
        events = self._parse_tool(status_code=500)
        assert isinstance(events[1], ToolCallEvent)
        assert events[1].status == ToolCallStatus.FAILURE

    def test_multiple_tool_use_blocks(self) -> None:
        response = {
            "content": [
                {"type": "tool_use", "id": "1", "name": "search", "input": {}},
                {"type": "tool_use", "id": "2", "name": "lookup", "input": {}},
            ],
            "stop_reason": "tool_use",
            "usage": {"input_tokens": 10, "output_tokens": 5},
        }
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=response,
            latency_ms=100.0,
            status_code=200,
        )
        # 1 LLMCallEvent + 2 ToolCallEvents
        assert len(events) == 3
        tool_events = [e for e in events if isinstance(e, ToolCallEvent)]
        names = {e.tool_name for e in tool_events}
        assert names == {"search", "lookup"}

    def test_no_tool_use_returns_only_llm_event(self) -> None:
        response = {
            "content": [{"type": "text", "text": "Hello!"}],
            "stop_reason": "end_turn",
        }
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=response,
            latency_ms=100.0,
            status_code=200,
        )
        assert len(events) == 1
        assert isinstance(events[0], LLMCallEvent)

    def test_api_error_returns_llm_and_tool_failure(self) -> None:
        response = {"error": {"type": "invalid_request_error", "message": "bad input"}}
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=_REQUEST_BODY,
            response_body=response,
            latency_ms=50.0,
            status_code=400,
        )
        # LLMCallEvent + ToolCallEvent(failure)
        assert len(events) == 2
        tool_event = events[1]
        assert isinstance(tool_event, ToolCallEvent)
        assert tool_event.status == ToolCallStatus.FAILURE
        assert tool_event.failure_type == FailureType.API_ERROR

    def test_schema_hash_populated(self) -> None:
        events = self._parse_tool()
        event = events[1]
        assert isinstance(event, ToolCallEvent)
        assert event.input_schema_hash != ""

    def test_trace_id_propagated_to_tool_event(self) -> None:
        req = {**_REQUEST_BODY, "metadata": {"trace_id": "my-trace"}}
        events = self.parser.parse(
            url=_ANTHROPIC_URL,
            request_body=req,
            response_body=_TOOL_USE_RESPONSE,
            latency_ms=100.0,
            status_code=200,
        )
        # Both events should share the same trace_id
        assert events[0].trace_id == "my-trace"
        assert events[1].trace_id == "my-trace"

    def test_can_parse_anthropic_url(self) -> None:
        assert self.parser.can_parse(_ANTHROPIC_URL) is True

    def test_cannot_parse_other_url(self) -> None:
        assert self.parser.can_parse("https://api.openai.com/v1/chat") is False


# ---------------------------------------------------------------------------
# Sanitise helper
# ---------------------------------------------------------------------------


class TestSanitise:
    def test_redacts_api_key(self) -> None:
        result = _sanitise({"api_key": "sk-secret123", "query": "hello"})
        assert result["api_key"] == "[REDACTED]"
        assert result["query"] == "hello"

    def test_redacts_nested_sensitive_parent(self) -> None:
        result = _sanitise({"auth": {"bearer": "token123", "user": "alice"}})
        assert result["auth"] == "[REDACTED]"

    def test_redacts_nested_sensitive_child(self) -> None:
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
# OpenAIParser stub
# ---------------------------------------------------------------------------


class TestOpenAIParser:
    def test_can_parse_openai_url(self) -> None:
        parser = OpenAIParser()
        assert parser.can_parse("https://api.openai.com/v1/chat/completions") is True

    def test_does_not_parse_non_completions_url(self) -> None:
        parser = OpenAIParser()
        assert parser.can_parse("https://api.openai.com/v1/embeddings") is False


# ---------------------------------------------------------------------------
# ParserRegistry
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
        # LLMCallEvent + ToolCallEvent
        assert len(events) == 2

    def test_first_matching_parser_wins(self) -> None:
        reg = ParserRegistry()
        reg.register(AnthropicParser())
        reg.register(OpenAIParser())
        parser = reg.find_parser(_ANTHROPIC_URL)
        assert isinstance(parser, AnthropicParser)
