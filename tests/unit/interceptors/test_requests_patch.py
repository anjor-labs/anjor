"""Unit tests for RequestsInterceptor."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

# Skip entire module if requests is not installed
requests = pytest.importorskip("requests")

from anjor.core.events.base import BaseEvent
from anjor.core.events.llm_call import LLMCallEvent
from anjor.core.events.tool_call import ToolCallEvent
from anjor.core.pipeline.pipeline import EventPipeline
from anjor.interceptors.requests_patch import RequestsInterceptor

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"

_ANTHROPIC_TOOL_RESPONSE = {
    "content": [
        {
            "type": "tool_use",
            "id": "toolu_01",
            "name": "search",
            "input": {"query": "AI news"},
        }
    ],
    "usage": {"input_tokens": 10, "output_tokens": 5},
    "stop_reason": "tool_use",
}

_ANTHROPIC_TEXT_RESPONSE = {
    "content": [{"type": "text", "text": "Hello!"}],
    "usage": {"input_tokens": 8, "output_tokens": 3},
    "stop_reason": "end_turn",
    "model": "claude-3-5-sonnet-20241022",
}

_REQUEST_BODY = {
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "search for AI news"}],
}

_OPENAI_RESPONSE = {
    "model": "gpt-4o",
    "choices": [
        {
            "message": {"role": "assistant", "content": "Hello"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
}

_OPENAI_REQUEST = {
    "model": "gpt-4o",
    "messages": [{"role": "user", "content": "hi"}],
}


def _make_prepared_request(url: str, body: bytes | str | None) -> MagicMock:
    req = MagicMock()
    req.url = url
    req.body = body
    return req


def _make_response(
    status: int,
    body: dict,
    content_type: str = "application/json",
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status
    resp.content = json.dumps(body).encode()
    # Use a real dict so .headers.get() works correctly
    resp.headers = {"content-type": content_type}
    return resp


def _sse_bytes(*events: tuple[str, dict]) -> bytes:
    """Build raw SSE bytes from (event_type, data_dict) pairs."""
    parts: list[str] = []
    for evt_type, data in events:
        parts.append(f"event: {evt_type}\ndata: {json.dumps(data)}\n\n")
    return "".join(parts).encode()


class CapturingPipeline(EventPipeline):
    def __init__(self) -> None:
        super().__init__()
        self.captured: list[BaseEvent] = []

    def put(self, event: BaseEvent) -> bool:
        self.captured.append(event)
        return super().put(event)


# ---------------------------------------------------------------------------
# Install / uninstall lifecycle
# ---------------------------------------------------------------------------


class TestRequestsInterceptorLifecycle:
    def setup_method(self) -> None:
        self.pipeline = CapturingPipeline()
        self.interceptor = RequestsInterceptor(pipeline=self.pipeline)

    def teardown_method(self) -> None:
        self.interceptor.uninstall()

    def test_not_installed_by_default(self) -> None:
        assert self.interceptor.is_installed is False

    def test_install_sets_installed(self) -> None:
        self.interceptor.install()
        assert self.interceptor.is_installed is True

    def test_install_patches_session_send(self) -> None:
        original = requests.Session.send
        self.interceptor.install()
        assert requests.Session.send is not original

    def test_install_is_idempotent(self) -> None:
        self.interceptor.install()
        patched = requests.Session.send
        self.interceptor.install()  # second call must not double-wrap
        assert requests.Session.send is patched

    def test_uninstall_restores_session_send(self) -> None:
        original = requests.Session.send
        self.interceptor.install()
        self.interceptor.uninstall()
        assert requests.Session.send is original

    def test_uninstall_clears_installed(self) -> None:
        self.interceptor.install()
        self.interceptor.uninstall()
        assert self.interceptor.is_installed is False

    def test_uninstall_is_idempotent(self) -> None:
        self.interceptor.install()
        self.interceptor.uninstall()
        self.interceptor.uninstall()  # must not raise
        assert self.interceptor.is_installed is False


# ---------------------------------------------------------------------------
# _process — direct unit tests (no network)
# ---------------------------------------------------------------------------


class TestRequestsInterceptorProcess:
    def setup_method(self) -> None:
        self.pipeline = CapturingPipeline()
        self.interceptor = RequestsInterceptor(pipeline=self.pipeline)

    def test_anthropic_tool_use_emits_llm_and_tool_events(self) -> None:
        req = _make_prepared_request(_ANTHROPIC_URL, json.dumps(_REQUEST_BODY).encode())
        resp = _make_response(200, _ANTHROPIC_TOOL_RESPONSE)
        self.interceptor._process(req, resp, latency_ms=42.0)
        assert len(self.pipeline.captured) == 2
        assert isinstance(self.pipeline.captured[0], LLMCallEvent)
        assert isinstance(self.pipeline.captured[1], ToolCallEvent)

    def test_anthropic_text_response_emits_llm_event(self) -> None:
        req = _make_prepared_request(_ANTHROPIC_URL, json.dumps(_REQUEST_BODY).encode())
        resp = _make_response(200, _ANTHROPIC_TEXT_RESPONSE)
        self.interceptor._process(req, resp, latency_ms=20.0)
        assert len(self.pipeline.captured) == 1
        assert isinstance(self.pipeline.captured[0], LLMCallEvent)

    def test_openai_response_emits_llm_event(self) -> None:
        req = _make_prepared_request(_OPENAI_URL, json.dumps(_OPENAI_REQUEST).encode())
        resp = _make_response(200, _OPENAI_RESPONSE)
        self.interceptor._process(req, resp, latency_ms=15.0)
        assert len(self.pipeline.captured) == 1
        assert isinstance(self.pipeline.captured[0], LLMCallEvent)

    def test_unknown_url_emits_no_events(self) -> None:
        req = _make_prepared_request("https://example.com/api", b"{}")
        resp = _make_response(200, {})
        self.interceptor._process(req, resp, latency_ms=5.0)
        assert len(self.pipeline.captured) == 0

    def test_string_body_handled(self) -> None:
        """request.body can be a str (e.g. application/x-www-form-urlencoded)."""
        req = _make_prepared_request(_ANTHROPIC_URL, json.dumps(_REQUEST_BODY))  # str
        resp = _make_response(200, _ANTHROPIC_TEXT_RESPONSE)
        self.interceptor._process(req, resp, latency_ms=10.0)
        assert len(self.pipeline.captured) == 1

    def test_none_body_handled(self) -> None:
        """request.body is None for GET requests."""
        req = _make_prepared_request(_ANTHROPIC_URL, None)
        resp = _make_response(200, _ANTHROPIC_TEXT_RESPONSE)
        self.interceptor._process(req, resp, latency_ms=5.0)
        # No request body — parser still emits LLM event from response
        assert len(self.pipeline.captured) >= 1

    def test_latency_propagated_to_event(self) -> None:
        req = _make_prepared_request(_ANTHROPIC_URL, json.dumps(_REQUEST_BODY).encode())
        resp = _make_response(200, _ANTHROPIC_TEXT_RESPONSE)
        self.interceptor._process(req, resp, latency_ms=99.5)
        assert self.pipeline.captured[0].latency_ms == pytest.approx(99.5)

    def test_process_never_raises(self) -> None:
        """Malformed data must not propagate an exception."""
        bad_req = MagicMock()
        bad_req.url = _ANTHROPIC_URL
        bad_req.body = b"not json {"
        bad_resp = MagicMock()
        bad_resp.content = b"not json {"
        bad_resp.status_code = 200
        bad_resp.headers = {}
        self.interceptor._process(bad_req, bad_resp, latency_ms=0.0)  # must not raise


# ---------------------------------------------------------------------------
# SSE (streaming) response handling
# ---------------------------------------------------------------------------


class TestRequestsInterceptorSSE:
    def setup_method(self) -> None:
        self.pipeline = CapturingPipeline()
        self.interceptor = RequestsInterceptor(pipeline=self.pipeline)

    def test_anthropic_sse_text_response(self) -> None:
        raw = _sse_bytes(
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "model": "claude-3-5-sonnet-20241022",
                        "usage": {"input_tokens": 8, "output_tokens": 0},
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "text"},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "text_delta", "text": "Hello"},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "end_turn"},
                    "usage": {"output_tokens": 3},
                },
            ),
            ("message_stop", {"type": "message_stop"}),
        )

        req = _make_prepared_request(_ANTHROPIC_URL, json.dumps(_REQUEST_BODY).encode())
        resp = MagicMock()
        resp.status_code = 200
        resp.content = raw
        resp.headers = {"content-type": "text/event-stream"}

        self.interceptor._process(req, resp, latency_ms=30.0)

        assert len(self.pipeline.captured) == 1
        llm = self.pipeline.captured[0]
        assert isinstance(llm, LLMCallEvent)
        assert llm.token_usage is not None
        assert llm.token_usage.input == 8
        assert llm.token_usage.output == 3

    def test_anthropic_sse_tool_use(self) -> None:
        raw = _sse_bytes(
            (
                "message_start",
                {
                    "type": "message_start",
                    "message": {
                        "model": "claude-3-5-sonnet-20241022",
                        "usage": {"input_tokens": 12, "output_tokens": 0},
                    },
                },
            ),
            (
                "content_block_start",
                {
                    "type": "content_block_start",
                    "index": 0,
                    "content_block": {"type": "tool_use", "id": "toolu_01", "name": "search"},
                },
            ),
            (
                "content_block_delta",
                {
                    "type": "content_block_delta",
                    "index": 0,
                    "delta": {"type": "input_json_delta", "partial_json": '{"query": "AI"}'},
                },
            ),
            ("content_block_stop", {"type": "content_block_stop", "index": 0}),
            (
                "message_delta",
                {
                    "type": "message_delta",
                    "delta": {"stop_reason": "tool_use"},
                    "usage": {"output_tokens": 8},
                },
            ),
        )

        req = _make_prepared_request(_ANTHROPIC_URL, json.dumps(_REQUEST_BODY).encode())
        resp = MagicMock()
        resp.status_code = 200
        resp.content = raw
        resp.headers = {"content-type": "text/event-stream; charset=utf-8"}

        self.interceptor._process(req, resp, latency_ms=50.0)

        assert len(self.pipeline.captured) == 2
        assert isinstance(self.pipeline.captured[0], LLMCallEvent)
        assert isinstance(self.pipeline.captured[1], ToolCallEvent)
        assert self.pipeline.captured[1].tool_name == "search"

    def test_unknown_url_sse_emits_no_events(self) -> None:
        raw = b"event: ping\ndata: {}\n\n"
        req = _make_prepared_request("https://example.com/stream", b"{}")
        resp = MagicMock()
        resp.status_code = 200
        resp.content = raw
        resp.headers = {"content-type": "text/event-stream"}
        self.interceptor._process(req, resp, latency_ms=5.0)
        assert len(self.pipeline.captured) == 0


# ---------------------------------------------------------------------------
# Full end-to-end path: install → mock original → call Session.send
# ---------------------------------------------------------------------------


class TestRequestsInterceptorFullPath:
    def setup_method(self) -> None:
        self.pipeline = CapturingPipeline()
        self.interceptor = RequestsInterceptor(pipeline=self.pipeline)

    def teardown_method(self) -> None:
        self.interceptor.uninstall()

    def test_session_send_triggers_event_capture(self) -> None:
        """Full path: install wrapper, replace saved original with mock, call Session.send."""
        self.interceptor.install()

        mock_response = _make_response(200, _ANTHROPIC_TOOL_RESPONSE)
        # Replace the saved original so the wrapper returns our mock response
        # without making a real network call.
        self.interceptor._original_session_send = MagicMock(return_value=mock_response)

        session = requests.Session()
        prepared = requests.Request(
            "POST",
            _ANTHROPIC_URL,
            json=_REQUEST_BODY,
        ).prepare()

        result = session.send(prepared)

        # Events captured
        assert len(self.pipeline.captured) == 2
        assert isinstance(self.pipeline.captured[0], LLMCallEvent)
        assert isinstance(self.pipeline.captured[1], ToolCallEvent)
        # Original response returned unchanged
        assert result is mock_response

    def test_response_returned_unmodified(self) -> None:
        """The wrapper must return exactly what the original send returns."""
        self.interceptor.install()
        mock_response = _make_response(200, _ANTHROPIC_TEXT_RESPONSE)
        self.interceptor._original_session_send = MagicMock(return_value=mock_response)

        session = requests.Session()
        prepared = requests.Request("POST", _ANTHROPIC_URL, json=_REQUEST_BODY).prepare()
        result = session.send(prepared)

        assert result is mock_response

    def test_exception_in_process_does_not_affect_response(self) -> None:
        """A bug in event processing must never break the caller's response."""
        self.interceptor.install()
        mock_response = _make_response(200, _ANTHROPIC_TEXT_RESPONSE)
        self.interceptor._original_session_send = MagicMock(return_value=mock_response)

        # Make _emit_events raise to simulate a processing bug
        self.interceptor._emit_events = MagicMock(side_effect=RuntimeError("boom"))

        session = requests.Session()
        prepared = requests.Request("POST", _ANTHROPIC_URL, json=_REQUEST_BODY).prepare()
        result = session.send(prepared)  # must not raise

        assert result is mock_response
