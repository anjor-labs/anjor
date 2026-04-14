"""Unit tests for PatchInterceptor."""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import httpx
import pytest

from anjor.core.events.base import BaseEvent, EventType
from anjor.core.events.llm_call import LLMCallEvent
from anjor.core.events.tool_call import ToolCallEvent
from anjor.core.pipeline.pipeline import EventPipeline
from anjor.interceptors.patch import (
    PatchInterceptor,
    ProxyInterceptor,
    _body_to_dict,
    _infer_agent_id,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

_TOOL_RESPONSE = {
    "content": [
        {
            "type": "tool_use",
            "id": "toolu_01",
            "name": "search",
            "input": {"query": "AI news"},
        }
    ],
    "usage": {"input_tokens": 10, "output_tokens": 5},
}

_REQUEST_BODY = {
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [],
}


def make_httpx_request(url: str, body: dict) -> httpx.Request:
    return httpx.Request(
        "POST",
        url,
        content=json.dumps(body).encode(),
        headers={"content-type": "application/json"},
    )


def make_httpx_response(status: int, body: dict) -> httpx.Response:
    content = json.dumps(body).encode()
    return httpx.Response(
        status_code=status,
        content=content,
        headers={"content-type": "application/json"},
    )


class CapturingPipeline(EventPipeline):
    """Pipeline that records what was put."""

    def __init__(self) -> None:
        super().__init__()
        self.captured: list[BaseEvent] = []

    def put(self, event: BaseEvent) -> bool:
        self.captured.append(event)
        return super().put(event)


# ---------------------------------------------------------------------------
# PatchInterceptor tests
# ---------------------------------------------------------------------------


class TestPatchInterceptor:
    def setup_method(self) -> None:
        self.pipeline = CapturingPipeline()
        self.interceptor = PatchInterceptor(pipeline=self.pipeline)

    def teardown_method(self) -> None:
        self.interceptor.uninstall()

    def test_not_installed_by_default(self) -> None:
        assert self.interceptor.is_installed is False

    def test_install_sets_installed(self) -> None:
        self.interceptor.install()
        assert self.interceptor.is_installed is True

    def test_install_is_idempotent(self) -> None:
        self.interceptor.install()
        self.interceptor.install()  # second call must not raise
        assert self.interceptor.is_installed is True

    def test_uninstall_restores_state(self) -> None:
        original_send = httpx.Client.send
        self.interceptor.install()
        self.interceptor.uninstall()
        assert httpx.Client.send is original_send

    def test_uninstall_is_idempotent(self) -> None:
        self.interceptor.install()
        self.interceptor.uninstall()
        self.interceptor.uninstall()  # second call must not raise
        assert self.interceptor.is_installed is False

    def test_process_enqueues_events(self) -> None:
        request = make_httpx_request(_ANTHROPIC_URL, _REQUEST_BODY)
        response = make_httpx_response(200, _TOOL_RESPONSE)
        self.interceptor._process(request, response, latency_ms=100.0)
        # Phase 2: every call emits LLMCallEvent + ToolCallEvent(s)
        assert len(self.pipeline.captured) == 2
        assert isinstance(self.pipeline.captured[0], LLMCallEvent)
        assert isinstance(self.pipeline.captured[1], ToolCallEvent)
        assert self.pipeline.captured[1].event_type == EventType.TOOL_CALL

    def test_process_non_matching_url_no_events(self) -> None:
        request = make_httpx_request("https://example.com/api", {})
        response = make_httpx_response(200, {})
        self.interceptor._process(request, response, latency_ms=10.0)
        assert len(self.pipeline.captured) == 0

    def test_process_never_raises(self) -> None:
        # Malformed request/response should not propagate
        bad_request = MagicMock()
        bad_request.url = _ANTHROPIC_URL
        bad_request.content = b"not json {"
        bad_response = MagicMock()
        bad_response.content = b"not json {"
        bad_response.status_code = 200
        self.interceptor._process(bad_request, bad_response, latency_ms=0.0)

    def test_sync_httpx_intercepted(self) -> None:
        self.interceptor.install()
        with respx.mock:
            respx.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=_TOOL_RESPONSE))
            with httpx.Client() as client:
                client.post(
                    _ANTHROPIC_URL,
                    json=_REQUEST_BODY,
                    headers={"x-api-key": "test"},
                )
        # LLMCallEvent + ToolCallEvent
        assert len(self.pipeline.captured) == 2
        assert isinstance(self.pipeline.captured[0], LLMCallEvent)

    async def test_async_httpx_intercepted(self) -> None:
        self.interceptor.install()
        with respx.mock:
            respx.post(_ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=_TOOL_RESPONSE))
            async with httpx.AsyncClient() as client:
                await client.post(
                    _ANTHROPIC_URL,
                    json=_REQUEST_BODY,
                    headers={"x-api-key": "test"},
                )
        # LLMCallEvent + ToolCallEvent
        assert len(self.pipeline.captured) == 2
        assert isinstance(self.pipeline.captured[0], LLMCallEvent)


# Import respx at module level for tests that use it
try:
    import respx
except ImportError:
    pass


class TestInferAgentId:
    def test_returns_empty_for_no_system(self) -> None:
        assert _infer_agent_id({}) == ""
        assert _infer_agent_id({"model": "claude-3"}) == ""

    def test_returns_prefix_and_hash_for_string_system(self) -> None:
        result = _infer_agent_id({"system": "You are a web researcher."})
        assert result.startswith("You are a web res")
        assert "_" in result
        # Hash portion is 8 hex chars
        assert len(result.split("_")[-1]) == 8

    def test_stable_for_same_system_prompt(self) -> None:
        body = {"system": "You are an analyst."}
        assert _infer_agent_id(body) == _infer_agent_id(body)

    def test_different_prompts_produce_different_ids(self) -> None:
        a = _infer_agent_id({"system": "You are agent A."})
        b = _infer_agent_id({"system": "You are agent B."})
        assert a != b

    def test_handles_list_system_prompt(self) -> None:
        # Anthropic accepts system as a list of content blocks
        body = {"system": [{"type": "text", "text": "You are a helpful assistant."}]}
        result = _infer_agent_id(body)
        assert result != ""
        assert "You are a helpful" in result

    def test_empty_string_system_returns_empty(self) -> None:
        assert _infer_agent_id({"system": ""}) == ""
        assert _infer_agent_id({"system": "   "}) == ""


class TestBodyToDict:
    def test_valid_json(self) -> None:
        result = _body_to_dict(b'{"key": "value"}')
        assert result == {"key": "value"}

    def test_empty_bytes(self) -> None:
        assert _body_to_dict(b"") == {}

    def test_invalid_json(self) -> None:
        assert _body_to_dict(b"not json {") == {}


class TestProxyInterceptor:
    def test_is_not_installed(self) -> None:
        proxy = ProxyInterceptor()
        assert proxy.is_installed is False

    def test_install_raises(self) -> None:
        proxy = ProxyInterceptor()
        with pytest.raises(NotImplementedError):
            proxy.install()

    def test_uninstall_does_nothing(self) -> None:
        proxy = ProxyInterceptor()
        proxy.uninstall()  # must not raise
