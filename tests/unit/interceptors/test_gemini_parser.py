"""Unit tests for GeminiParser."""

from __future__ import annotations

from hypothesis import given, settings
from hypothesis import strategies as st

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


class TestCachedContentTokens:
    """cachedContentTokenCount → LLMTokenUsage.cache_read."""

    def _parse_with_cache(self, cached: int) -> LLMCallEvent:
        response = {
            "modelVersion": "gemini-2.0-flash",
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "Answer."}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {
                "promptTokenCount": 200,
                "candidatesTokenCount": 50,
                "totalTokenCount": 250,
                "cachedContentTokenCount": cached,
            },
        }
        events = GeminiParser().parse(_URL, _REQUEST, response, 100.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        return llm

    def test_cache_read_extracted(self) -> None:
        llm = self._parse_with_cache(80)
        assert llm.token_usage is not None
        assert llm.token_usage.cache_read == 80

    def test_cache_read_zero_when_absent(self) -> None:
        """No cachedContentTokenCount key → cache_read defaults to 0."""
        response = {
            "modelVersion": "gemini-2.0-flash",
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "Answer."}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 30},
        }
        events = GeminiParser().parse(_URL, _REQUEST, response, 100.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.token_usage is not None
        assert llm.token_usage.cache_read == 0

    def test_input_maps_to_prompt_token_count(self) -> None:
        llm = self._parse_with_cache(80)
        assert llm.token_usage is not None
        assert llm.token_usage.input == 200

    def test_output_maps_to_candidates_token_count(self) -> None:
        llm = self._parse_with_cache(80)
        assert llm.token_usage is not None
        assert llm.token_usage.output == 50

    def test_cache_creation_is_zero(self) -> None:
        """Gemini has no cache_creation concept — field stays at default 0."""
        llm = self._parse_with_cache(80)
        assert llm.token_usage is not None
        assert llm.token_usage.cache_creation == 0

    def test_cache_read_at_zero_explicit(self) -> None:
        """Explicit cachedContentTokenCount=0 is handled correctly."""
        llm = self._parse_with_cache(0)
        assert llm.token_usage is not None
        assert llm.token_usage.cache_read == 0


class TestContextWindowLimitsExtended:
    """Context limit lookup for all documented current models."""

    def _limit(self, model: str) -> int:
        resp = {
            "modelVersion": model,
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "ok"}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
        }
        events = GeminiParser().parse(_URL, _REQUEST, resp, 10.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        return llm.context_window_limit

    def test_gemini_2_5_pro(self) -> None:
        assert self._limit("gemini-2.5-pro") == 1_048_576

    def test_gemini_2_0_flash(self) -> None:
        assert self._limit("gemini-2.0-flash") == 1_048_576

    def test_gemini_1_5_pro(self) -> None:
        assert self._limit("gemini-1.5-pro") == 2_097_152

    def test_gemini_1_5_flash(self) -> None:
        assert self._limit("gemini-1.5-flash") == 1_048_576

    def test_unknown_gemini_model_fallback(self) -> None:
        """Any unrecognised gemini-* model gets the default 1M fallback."""
        assert self._limit("gemini-99-ultra") == 1_048_576


# ---------------------------------------------------------------------------
# Property-based tests (Hypothesis)
# ---------------------------------------------------------------------------


def _response_with_usage(
    prompt_tokens: int,
    candidates_tokens: int,
    total_tokens: int,
    cached_tokens: int,
) -> dict:
    return {
        "modelVersion": "gemini-2.0-flash",
        "candidates": [
            {
                "content": {"role": "model", "parts": [{"text": "answer"}]},
                "finishReason": "STOP",
            }
        ],
        "usageMetadata": {
            "promptTokenCount": prompt_tokens,
            "candidatesTokenCount": candidates_tokens,
            "totalTokenCount": total_tokens,
            "cachedContentTokenCount": cached_tokens,
        },
    }


class TestTokenMathProperties:
    """Hypothesis property tests verifying token arithmetic invariants."""

    @settings(max_examples=200)
    @given(
        prompt=st.integers(min_value=0, max_value=2_000_000),
        candidates=st.integers(min_value=0, max_value=100_000),
    )
    def test_input_plus_output_equals_total(self, prompt: int, candidates: int) -> None:
        """input + output == totalTokenCount when total == prompt + candidates."""
        total = prompt + candidates
        response = _response_with_usage(prompt, candidates, total, 0)
        events = GeminiParser().parse(_URL, _REQUEST, response, 10.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.token_usage is not None
        assert llm.token_usage.input + llm.token_usage.output == total

    @settings(max_examples=200)
    @given(
        prompt=st.integers(min_value=1, max_value=2_000_000),
        candidates=st.integers(min_value=0, max_value=100_000),
        cached_fraction=st.floats(min_value=0.0, max_value=1.0),
    )
    def test_cache_read_does_not_exceed_input(
        self, prompt: int, candidates: int, cached_fraction: float
    ) -> None:
        """cachedContentTokenCount is always <= promptTokenCount (subset relationship)."""
        cached = int(prompt * cached_fraction)
        total = prompt + candidates
        response = _response_with_usage(prompt, candidates, total, cached)
        events = GeminiParser().parse(_URL, _REQUEST, response, 10.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.token_usage is not None
        assert llm.token_usage.cache_read <= llm.token_usage.input

    @settings(max_examples=200)
    @given(
        prompt=st.integers(min_value=0, max_value=2_000_000),
        candidates=st.integers(min_value=0, max_value=100_000),
        cached=st.integers(min_value=0, max_value=2_000_000),
    )
    def test_all_token_fields_non_negative(self, prompt: int, candidates: int, cached: int) -> None:
        """All extracted token counts are always non-negative integers."""
        total = prompt + candidates
        response = _response_with_usage(prompt, candidates, total, cached)
        events = GeminiParser().parse(_URL, _REQUEST, response, 10.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.token_usage is not None
        assert llm.token_usage.input >= 0
        assert llm.token_usage.output >= 0
        assert llm.token_usage.cache_read >= 0
        assert llm.token_usage.cache_creation == 0

    @settings(max_examples=100)
    @given(
        prompt=st.integers(min_value=0, max_value=500_000),
        candidates=st.integers(min_value=0, max_value=50_000),
    )
    def test_context_window_used_equals_prompt_plus_candidates(
        self, prompt: int, candidates: int
    ) -> None:
        """context_window_used is always promptTokenCount + candidatesTokenCount."""
        response = _response_with_usage(prompt, candidates, prompt + candidates, 0)
        events = GeminiParser().parse(_URL, _REQUEST, response, 10.0, 200)
        llm = events[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.context_window_used == prompt + candidates
