"""Unit tests for GeminiParser."""

from __future__ import annotations

from anjor.core.events.llm_call import LLMCallEvent
from anjor.core.events.tool_call import FailureType, ToolCallEvent, ToolCallStatus
from anjor.interceptors.parsers.gemini import GeminiParser

_URL = "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
_OTHER_URL = "https://api.openai.com/v1/chat/completions"

_REQUEST = {
    "contents": [
        {"role": "user", "parts": [{"text": "Search for recent AI news"}]},
    ],
}

_TOOL_RESPONSE = {
    "modelVersion": "gemini-2.0-flash",
    "candidates": [
        {
            "content": {
                "role": "model",
                "parts": [
                    {
                        "functionCall": {
                            "name": "web_search",
                            "args": {"query": "recent AI news"},
                        }
                    }
                ],
            },
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 120, "candidatesTokenCount": 30},
}

_TEXT_RESPONSE = {
    "modelVersion": "gemini-2.0-flash",
    "candidates": [
        {
            "content": {"role": "model", "parts": [{"text": "Here is the answer."}]},
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 80, "candidatesTokenCount": 20},
}

_ERROR_RESPONSE = {
    "error": {"code": 429, "message": "Resource exhausted", "status": "RESOURCE_EXHAUSTED"}
}


class TestCanParse:
    def test_matches_gemini_url(self) -> None:
        assert GeminiParser().can_parse(_URL)

    def test_does_not_match_openai(self) -> None:
        assert not GeminiParser().can_parse(_OTHER_URL)

    def test_does_not_match_random_url(self) -> None:
        assert not GeminiParser().can_parse("https://example.com/api")


class TestToolCallResponse:
    def setup_method(self) -> None:
        self.parser = GeminiParser()
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
        assert llm.model == "gemini-2.0-flash"

    def test_llm_token_input(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.token_usage is not None
        assert llm.token_usage.input == 120

    def test_llm_token_output(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.token_usage is not None
        assert llm.token_usage.output == 30

    def test_llm_finish_reason(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.finish_reason == "STOP"

    def test_llm_messages_count(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.messages_count == 1

    def test_llm_context_window_used(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_used == 150

    def test_llm_context_limit_for_gemini_flash(self) -> None:
        llm = self.events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_limit == 1_048_576

    def test_tool_name(self) -> None:
        tool = self.events[1]
        assert isinstance(tool, ToolCallEvent)
        assert tool.tool_name == "web_search"

    def test_tool_status_success(self) -> None:
        tool = self.events[1]
        assert isinstance(tool, ToolCallEvent)
        assert tool.status == ToolCallStatus.SUCCESS
        assert tool.failure_type is None

    def test_tool_args_already_dict(self) -> None:
        tool = self.events[1]
        assert isinstance(tool, ToolCallEvent)
        assert tool.input_payload == {"query": "recent AI news"}

    def test_shared_trace_id(self) -> None:
        llm, tool = self.events[0], self.events[1]
        assert isinstance(llm, LLMCallEvent)
        assert isinstance(tool, ToolCallEvent)
        assert llm.trace_id == tool.trace_id


class TestTextOnlyResponse:
    def test_only_llm_event_emitted(self) -> None:
        events = GeminiParser().parse(_URL, _REQUEST, _TEXT_RESPONSE, 400.0, 200)
        assert len(events) == 1
        assert isinstance(events[0], LLMCallEvent)

    def test_finish_reason_stop(self) -> None:
        events = GeminiParser().parse(_URL, _REQUEST, _TEXT_RESPONSE, 400.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.finish_reason == "STOP"


class TestErrorResponse:
    def test_error_produces_llm_and_error_tool_event(self) -> None:
        events = GeminiParser().parse(_URL, _REQUEST, _ERROR_RESPONSE, 200.0, 429)
        assert len(events) == 2
        assert isinstance(events[0], LLMCallEvent)
        tool = events[1]
        assert isinstance(tool, ToolCallEvent)
        assert tool.status == ToolCallStatus.FAILURE
        assert tool.failure_type == FailureType.API_ERROR
        assert tool.tool_name == "unknown"


class TestMultipleToolCalls:
    def test_two_function_calls_produce_two_tool_events(self) -> None:
        response = {
            "modelVersion": "gemini-1.5-pro",
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {"functionCall": {"name": "search", "args": {"q": "foo"}}},
                            {"functionCall": {"name": "fetch", "args": {"url": "http://x.com"}}},
                        ],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 40},
        }
        events = GeminiParser().parse(_URL, _REQUEST, response, 200.0, 200)
        assert len(events) == 3  # 1 LLM + 2 tool
        tool_names = {e.tool_name for e in events if isinstance(e, ToolCallEvent)}
        assert tool_names == {"search", "fetch"}


class TestModelExtraction:
    def test_model_from_response_body(self) -> None:
        events = GeminiParser().parse(_URL, _REQUEST, _TOOL_RESPONSE, 100.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.model == "gemini-2.0-flash"

    def test_model_from_url_when_absent_in_response(self) -> None:
        resp_no_version = {k: v for k, v in _TEXT_RESPONSE.items() if k != "modelVersion"}
        events = GeminiParser().parse(_URL, _REQUEST, resp_no_version, 100.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.model == "gemini-2.0-flash"

    def test_unknown_gemini_model_uses_fallback_limit(self) -> None:
        resp = {**_TEXT_RESPONSE, "modelVersion": "gemini-future-99"}
        events = GeminiParser().parse(_URL, _REQUEST, resp, 100.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_limit == 1_048_576

    def test_non_gemini_unknown_model_zero_limit(self) -> None:
        resp = {**_TEXT_RESPONSE, "modelVersion": "some-other-model"}
        events = GeminiParser().parse(_URL, _REQUEST, resp, 100.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_limit == 0

    def test_gemini_1_5_pro_context_limit(self) -> None:
        resp = {**_TEXT_RESPONSE, "modelVersion": "gemini-1.5-pro"}
        events = GeminiParser().parse(_URL, _REQUEST, resp, 100.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_limit == 2_097_152


class TestSanitisation:
    def test_sensitive_key_in_args_redacted(self) -> None:
        response = {
            "modelVersion": "gemini-2.0-flash",
            "candidates": [
                {
                    "content": {
                        "role": "model",
                        "parts": [
                            {
                                "functionCall": {
                                    "name": "call_api",
                                    "args": {"api_key": "sk-secret", "query": "hello"},
                                }
                            }
                        ],
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 50, "candidatesTokenCount": 10},
        }
        events = GeminiParser().parse(_URL, _REQUEST, response, 100.0, 200)
        tool = events[1]
        assert isinstance(tool, ToolCallEvent)
        assert tool.input_payload["api_key"] == "[REDACTED]"
        assert tool.input_payload["query"] == "hello"
