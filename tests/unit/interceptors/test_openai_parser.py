"""Unit tests for OpenAIParser."""

from __future__ import annotations

from anjor.core.events.llm_call import LLMCallEvent
from anjor.core.events.tool_call import FailureType, ToolCallEvent, ToolCallStatus
from anjor.interceptors.parsers.openai import OpenAIParser, _parse_tool_arguments

_URL = "https://api.openai.com/v1/chat/completions"
_OTHER_URL = "https://api.anthropic.com/v1/messages"

_REQUEST = {
    "model": "gpt-4o",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "What is the weather in London?"},
    ],
}

_TOOL_RESPONSE = {
    "id": "chatcmpl-001",
    "model": "gpt-4o-2024-08-06",
    "choices": [
        {
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_abc",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"location": "London", "unit": "celsius"}',
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 120, "completion_tokens": 45, "total_tokens": 165},
}

_TEXT_RESPONSE = {
    "id": "chatcmpl-002",
    "model": "gpt-4o",
    "choices": [
        {
            "message": {"role": "assistant", "content": "The weather is sunny."},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100},
}

_ERROR_RESPONSE = {
    "error": {"message": "Rate limit exceeded", "type": "rate_limit_error"}
}


class TestCanParse:
    def test_matches_openai_url(self) -> None:
        assert OpenAIParser().can_parse(_URL)

    def test_does_not_match_anthropic(self) -> None:
        assert not OpenAIParser().can_parse(_OTHER_URL)

    def test_does_not_match_random_url(self) -> None:
        assert not OpenAIParser().can_parse("https://example.com/api")


class TestToolCallResponse:
    def setup_method(self) -> None:
        self.parser = OpenAIParser()
        self.events = self.parser.parse(_URL, _REQUEST, _TOOL_RESPONSE, 350.0, 200)

    def test_two_events_emitted(self) -> None:
        assert len(self.events) == 2

    def test_first_event_is_llm_call(self) -> None:
        assert isinstance(self.events[0], LLMCallEvent)

    def test_second_event_is_tool_call(self) -> None:
        assert isinstance(self.events[1], ToolCallEvent)

    def test_llm_model_from_response(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.model == "gpt-4o-2024-08-06"

    def test_llm_token_input(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.token_usage is not None
        assert llm.token_usage.input == 120

    def test_llm_token_output(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.token_usage is not None
        assert llm.token_usage.output == 45

    def test_llm_finish_reason(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.finish_reason == "tool_calls"

    def test_llm_messages_count(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.messages_count == 2

    def test_llm_context_window_used(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_used == 165

    def test_llm_context_limit_for_gpt4o(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_limit == 128_000

    def test_tool_name(self) -> None:
        tool = self.events[1]
        assert isinstance(tool, ToolCallEvent)
        assert tool.tool_name == "get_weather"

    def test_tool_status_success(self) -> None:
        tool = self.events[1]
        assert isinstance(tool, ToolCallEvent)
        assert tool.status == ToolCallStatus.SUCCESS
        assert tool.failure_type is None

    def test_tool_arguments_parsed_from_json_string(self) -> None:
        tool = self.events[1]
        assert isinstance(tool, ToolCallEvent)
        assert tool.input_payload == {"location": "London", "unit": "celsius"}

    def test_shared_trace_id(self) -> None:
        llm, tool = self.events[0], self.events[1]
        assert isinstance(llm, LLMCallEvent)
        assert isinstance(tool, ToolCallEvent)
        assert llm.trace_id == tool.trace_id


class TestMultipleToolCalls:
    def test_two_tool_calls_produce_two_tool_events(self) -> None:
        response = {
            "id": "chatcmpl-003",
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {"name": "search", "arguments": '{"q": "foo"}'},
                            },
                            {
                                "id": "call_2",
                                "type": "function",
                                "function": {"name": "fetch", "arguments": '{"url": "http://x.com"}'},
                            },
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 100, "completion_tokens": 30, "total_tokens": 130},
        }
        events = OpenAIParser().parse(_URL, _REQUEST, response, 200.0, 200)
        assert len(events) == 3  # 1 LLM + 2 tool
        tool_names = {e.tool_name for e in events if isinstance(e, ToolCallEvent)}
        assert tool_names == {"search", "fetch"}


class TestTextOnlyResponse:
    def test_only_llm_event_emitted(self) -> None:
        events = OpenAIParser().parse(_URL, _REQUEST, _TEXT_RESPONSE, 400.0, 200)
        assert len(events) == 1
        assert isinstance(events[0], LLMCallEvent)

    def test_finish_reason_stop(self) -> None:
        events = OpenAIParser().parse(_URL, _REQUEST, _TEXT_RESPONSE, 400.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.finish_reason == "stop"


class TestErrorResponse:
    def test_error_produces_llm_and_error_tool_event(self) -> None:
        events = OpenAIParser().parse(_URL, _REQUEST, _ERROR_RESPONSE, 200.0, 429)
        assert len(events) == 2
        assert isinstance(events[0], LLMCallEvent)
        tool = events[1]
        assert isinstance(tool, ToolCallEvent)
        assert tool.status == ToolCallStatus.FAILURE
        assert tool.failure_type == FailureType.API_ERROR
        assert tool.tool_name == "unknown"


class TestContextLimits:
    def test_known_model_gpt4(self) -> None:
        req = {**_REQUEST, "model": "gpt-4"}
        resp = {**_TEXT_RESPONSE, "model": "gpt-4"}
        events = OpenAIParser().parse(_URL, req, resp, 100.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_limit == 8_192

    def test_versioned_model_stripped_for_lookup(self) -> None:
        # gpt-4o-2024-08-06 should resolve to gpt-4o limit
        events = OpenAIParser().parse(_URL, _REQUEST, _TOOL_RESPONSE, 100.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_limit == 128_000

    def test_unknown_model_zero_limit(self) -> None:
        resp = {**_TEXT_RESPONSE, "model": "some-future-model"}
        events = OpenAIParser().parse(_URL, _REQUEST, resp, 100.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_limit == 0

    def test_o1_model(self) -> None:
        resp = {**_TEXT_RESPONSE, "model": "o1"}
        events = OpenAIParser().parse(_URL, _REQUEST, resp, 100.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_limit == 200_000


class TestParseToolArguments:
    def test_json_string_parsed(self) -> None:
        assert _parse_tool_arguments('{"key": "value"}') == {"key": "value"}

    def test_dict_passthrough(self) -> None:
        assert _parse_tool_arguments({"key": "value"}) == {"key": "value"}

    def test_invalid_json_returns_raw(self) -> None:
        result = _parse_tool_arguments("not json")
        assert result == {"raw": "not json"}

    def test_empty_string(self) -> None:
        result = _parse_tool_arguments("")
        assert result == {}

    def test_none_returns_empty(self) -> None:
        assert _parse_tool_arguments(None) == {}


class TestSanitisation:
    def test_api_key_in_arguments_redacted(self) -> None:
        response = {
            "id": "chatcmpl-004",
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": None,
                        "tool_calls": [
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "call_api",
                                    "arguments": '{"api_key": "sk-secret", "query": "hello"}',
                                },
                            }
                        ],
                    },
                    "finish_reason": "tool_calls",
                }
            ],
            "usage": {"prompt_tokens": 50, "completion_tokens": 10, "total_tokens": 60},
        }
        events = OpenAIParser().parse(_URL, _REQUEST, response, 100.0, 200)
        tool = events[1]
        assert isinstance(tool, ToolCallEvent)
        assert tool.input_payload["api_key"] == "[REDACTED]"
        assert tool.input_payload["query"] == "hello"
