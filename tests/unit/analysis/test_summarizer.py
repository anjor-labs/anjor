"""Unit tests for SessionSummarizer."""

from __future__ import annotations

import pytest
import respx
import httpx

from anjor.analysis.summarizer import SessionSummarizer, SessionSummary


FAKE_API_KEY = "sk-ant-test-key"
FAKE_MODEL = "claude-haiku-4-5-20251001"

SAMPLE_MESSAGES = [
    {"role": "user", "content_preview": "Can you help me refactor the parser?"},
    {"role": "assistant", "content_preview": "Sure, I'll start by reading the existing code."},
    {"role": "user", "content_preview": "Also fix the tests."},
]


def make_summarizer() -> SessionSummarizer:
    return SessionSummarizer(api_key=FAKE_API_KEY, model=FAKE_MODEL)


# ── _build_prompt ──────────────────────────────────────────────────────────────


def test_build_prompt_contains_tool_metrics() -> None:
    s = make_summarizer()
    prompt = s._build_prompt(
        session_id="sess-abc",
        messages=SAMPLE_MESSAGES,
        tool_call_count=10,
        tool_success_count=8,
        llm_call_count=5,
        estimated_cost_usd=0.0123,
        models_used=["claude-sonnet-4-6"],
    )
    assert "10 tool calls" in prompt
    assert "80%" in prompt  # 8/10 = 80%
    assert "5 LLM calls" in prompt
    assert "$0.0123" in prompt
    assert "claude-sonnet-4-6" in prompt


def test_build_prompt_zero_tool_calls_no_division_error() -> None:
    s = make_summarizer()
    prompt = s._build_prompt(
        session_id="sess-xyz",
        messages=[],
        tool_call_count=0,
        tool_success_count=0,
        llm_call_count=0,
        estimated_cost_usd=0.0,
        models_used=[],
    )
    assert "0 tool calls" in prompt
    assert "0%" in prompt
    assert "(no messages captured)" in prompt


def test_build_prompt_truncates_messages_to_8() -> None:
    s = make_summarizer()
    many_messages = [{"role": "user", "content_preview": f"Message {i}"} for i in range(20)]
    prompt = s._build_prompt(
        session_id="sess-1",
        messages=many_messages,
        tool_call_count=0,
        tool_success_count=0,
        llm_call_count=0,
        estimated_cost_usd=0.0,
        models_used=[],
    )
    # Only first 8 messages should appear
    assert "Message 7" in prompt
    assert "Message 8" not in prompt


def test_build_prompt_no_models_shows_unknown() -> None:
    s = make_summarizer()
    prompt = s._build_prompt(
        session_id="s",
        messages=[],
        tool_call_count=0,
        tool_success_count=0,
        llm_call_count=0,
        estimated_cost_usd=0.0,
        models_used=[],
    )
    assert "unknown" in prompt


# ── summarize() with mocked API ────────────────────────────────────────────────


@respx.mock
def test_summarize_returns_session_summary() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [
                    {"type": "text", "text": "The session refactored the parser and fixed tests."}
                ],
                "model": FAKE_MODEL,
            },
        )
    )

    s = make_summarizer()
    result = s.summarize(
        session_id="sess-001",
        messages=SAMPLE_MESSAGES,
        tool_call_count=5,
        tool_success_count=5,
        llm_call_count=3,
        estimated_cost_usd=0.005,
        models_used=["claude-haiku-4-5-20251001"],
    )

    assert isinstance(result, SessionSummary)
    assert result.session_id == "sess-001"
    assert result.summary == "The session refactored the parser and fixed tests."
    assert result.model == FAKE_MODEL


@respx.mock
def test_summarize_sends_correct_headers() -> None:
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={
                "content": [{"type": "text", "text": "Done."}],
                "model": FAKE_MODEL,
            },
        )
    )

    s = make_summarizer()
    s.summarize(
        session_id="sess-002",
        messages=[],
        tool_call_count=0,
        tool_success_count=0,
        llm_call_count=0,
        estimated_cost_usd=0.0,
        models_used=[],
    )

    assert route.called
    request = route.calls[0].request
    assert request.headers["x-api-key"] == FAKE_API_KEY
    assert request.headers["anthropic-version"] == "2023-06-01"


@respx.mock
def test_summarize_api_error_raises() -> None:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(401, json={"error": {"message": "Unauthorized"}})
    )

    s = make_summarizer()
    with pytest.raises(httpx.HTTPStatusError):
        s.summarize(
            session_id="sess-err",
            messages=[],
            tool_call_count=0,
            tool_success_count=0,
            llm_call_count=0,
            estimated_cost_usd=0.0,
            models_used=[],
        )


@respx.mock
def test_summarize_uses_model_from_init() -> None:
    custom_model = "claude-opus-4-5"
    route = respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(
            200,
            json={"content": [{"type": "text", "text": "Summary here."}], "model": custom_model},
        )
    )

    s = SessionSummarizer(api_key=FAKE_API_KEY, model=custom_model)
    result = s.summarize(
        session_id="sess-003",
        messages=[],
        tool_call_count=0,
        tool_success_count=0,
        llm_call_count=0,
        estimated_cost_usd=0.0,
        models_used=[],
    )

    import json

    body = json.loads(route.calls[0].request.content)
    assert body["model"] == custom_model
    assert result.model == custom_model


def test_default_model_constant() -> None:
    assert SessionSummarizer.DEFAULT_MODEL == "claude-haiku-4-5-20251001"
