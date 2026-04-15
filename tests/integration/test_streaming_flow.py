"""Integration tests: streaming SSE interception → events stored in SQLite.

Each test verifies the full path:
  respx mock SSE response
    → PatchInterceptor detects text/event-stream, installs tee wrapper
    → SDK iterates the stream (simulated via client.stream())
    → wrapper callback fires with accumulated bytes
    → _process_stream parses SSE, reconstructs response body
    → parser emits LLMCallEvent / ToolCallEvent
    → EventPipeline dispatches to StorageWritingHandler
    → SQLiteBackend persists
    → assertions on stored rows
"""

from __future__ import annotations

import json

import httpx
import pytest
import respx

from anjor.collector.storage.base import LLMQueryFilters, QueryFilters
from anjor.collector.storage.sqlite import SQLiteBackend
from anjor.core.events.base import BaseEvent
from anjor.core.pipeline.pipeline import EventPipeline
from anjor.interceptors.parsers.registry import build_default_registry
from anjor.interceptors.patch import PatchInterceptor

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_OPENAI_URL = "https://api.openai.com/v1/chat/completions"
_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:streamGenerateContent"
)

_REQUEST_BODY = {
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "system": "You are a research assistant.",
    "messages": [{"role": "user", "content": "Hello"}],
}
_OPENAI_REQUEST = {
    "model": "gpt-4o",
    "stream": True,
    "stream_options": {"include_usage": True},
    "messages": [{"role": "user", "content": "Hello"}],
}
_GEMINI_REQUEST = {"contents": [{"role": "user", "parts": [{"text": "Hello"}]}]}


def _sse(*blocks: str) -> bytes:
    return ("\n\n".join(blocks) + "\n\n").encode()


def _evt(etype: str, data: object) -> str:
    return f"event: {etype}\ndata: {json.dumps(data)}"


def _data(data: object) -> str:
    return f"data: {json.dumps(data)}"


def _streaming_response(sse_bytes: bytes) -> httpx.Response:
    return httpx.Response(
        200,
        headers={"content-type": "text/event-stream"},
        stream=httpx.ByteStream(sse_bytes),
    )


class StorageWritingHandler:
    name = "storage_writer"

    def __init__(self, storage: SQLiteBackend) -> None:
        self.storage = storage

    async def handle(self, event: BaseEvent) -> None:
        await self.storage.write_event(event.model_dump(mode="json"))


@pytest.fixture
async def storage() -> SQLiteBackend:  # type: ignore[misc]
    s = SQLiteBackend(db_path=":memory:", batch_interval_ms=9999)
    await s.connect()
    yield s
    await s.close()


# ---------------------------------------------------------------------------
# SSE fixtures
# ---------------------------------------------------------------------------

_ANTHROPIC_TEXT_SSE = _sse(
    _evt(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "model": "claude-3-5-sonnet-20241022",
                "usage": {"input_tokens": 150, "output_tokens": 1},
            },
        },
    ),
    _evt(
        "content_block_start",
        {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    ),
    _evt(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "text_delta", "text": "Hello world"},
        },
    ),
    _evt("content_block_stop", {"type": "content_block_stop", "index": 0}),
    _evt(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "end_turn"},
            "usage": {"output_tokens": 60},
        },
    ),
    _evt("message_stop", {"type": "message_stop"}),
)

_ANTHROPIC_TOOL_SSE = _sse(
    _evt(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "model": "claude-3-5-sonnet-20241022",
                "usage": {"input_tokens": 200, "output_tokens": 1},
            },
        },
    ),
    _evt(
        "content_block_start",
        {
            "type": "content_block_start",
            "index": 0,
            "content_block": {
                "type": "tool_use",
                "id": "toolu_stream_01",
                "name": "web_search",
                "input": {},
            },
        },
    ),
    _evt(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '{"query":'},
        },
    ),
    _evt(
        "content_block_delta",
        {
            "type": "content_block_delta",
            "index": 0,
            "delta": {"type": "input_json_delta", "partial_json": '"AI research"}'},
        },
    ),
    _evt("content_block_stop", {"type": "content_block_stop", "index": 0}),
    _evt(
        "message_delta",
        {
            "type": "message_delta",
            "delta": {"stop_reason": "tool_use"},
            "usage": {"output_tokens": 80},
        },
    ),
    _evt("message_stop", {"type": "message_stop"}),
)

_OPENAI_TEXT_SSE = _sse(
    _data(
        {
            "model": "gpt-4o",
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": "Hi"}, "finish_reason": None}
            ],
        }
    ),
    _data({"model": "gpt-4o", "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]}),
    _data(
        {
            "model": "gpt-4o",
            "choices": [],
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
        }
    ),
    "data: [DONE]",
)

_OPENAI_TOOL_SSE = _sse(
    _data(
        {
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [
                            {
                                "index": 0,
                                "id": "call_stream_01",
                                "type": "function",
                                "function": {"name": "search", "arguments": ""},
                            }
                        ]
                    },
                    "finish_reason": None,
                }
            ],
        }
    ),
    _data(
        {
            "model": "gpt-4o",
            "choices": [
                {
                    "index": 0,
                    "delta": {
                        "tool_calls": [{"index": 0, "function": {"arguments": '{"q":"news"}'}}]
                    },
                    "finish_reason": "tool_calls",
                }
            ],
        }
    ),
    "data: [DONE]",
)

_GEMINI_TEXT_SSE = _sse(
    _data(
        {
            "candidates": [
                {
                    "content": {"parts": [{"text": "Hello"}], "role": "model"},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 5},
            "modelVersion": "gemini-2.0-flash",
        }
    )
)

_GEMINI_TOOL_SSE = _sse(
    _data(
        {
            "candidates": [
                {
                    "content": {
                        "parts": [
                            {"functionCall": {"name": "web_search", "args": {"query": "AI news"}}}
                        ],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 30, "candidatesTokenCount": 15},
            "modelVersion": "gemini-2.0-flash",
        }
    )
)


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


def _run_streaming_request(
    interceptor: PatchInterceptor,
    url: str,
    body: dict,
    sse_bytes: bytes,
) -> None:
    """Mock an SSE response and drive a sync streaming client through it."""
    with respx.mock:
        respx.post(url).mock(return_value=_streaming_response(sse_bytes))
        with httpx.Client() as client:
            with client.stream("POST", url, json=body) as response:
                for _ in response.iter_lines():
                    pass  # consume the full stream so the callback fires


async def _run_async_streaming_request(
    interceptor: PatchInterceptor,
    url: str,
    body: dict,
    sse_bytes: bytes,
) -> None:
    """Mock an SSE response and drive an async streaming client through it."""
    with respx.mock:
        respx.post(url).mock(return_value=_streaming_response(sse_bytes))
        async with httpx.AsyncClient() as client:
            async with client.stream("POST", url, json=body) as response:
                async for _ in response.aiter_lines():
                    pass


# ---------------------------------------------------------------------------
# Anthropic streaming tests
# ---------------------------------------------------------------------------


class TestAnthropicStreamingFlow:
    async def test_text_stream_emits_llm_event(self, storage: SQLiteBackend) -> None:
        """A text-only streaming response produces one LLMCallEvent."""
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline, parser_registry=build_default_registry()
            )
            interceptor.install()
            try:
                _run_streaming_request(
                    interceptor, _ANTHROPIC_URL, _REQUEST_BODY, _ANTHROPIC_TEXT_SSE
                )
            finally:
                interceptor.uninstall()

        llm_calls = await storage.query_llm_calls(LLMQueryFilters())
        assert len(llm_calls) == 1
        row = llm_calls[0]
        assert row["model"] == "claude-3-5-sonnet-20241022"
        assert row["token_input"] == 150
        assert row["token_output"] == 60
        assert row["finish_reason"] == "end_turn"

    async def test_text_stream_no_tool_events(self, storage: SQLiteBackend) -> None:
        """A text-only streaming response produces no ToolCallEvents."""
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline, parser_registry=build_default_registry()
            )
            interceptor.install()
            try:
                _run_streaming_request(
                    interceptor, _ANTHROPIC_URL, _REQUEST_BODY, _ANTHROPIC_TEXT_SSE
                )
            finally:
                interceptor.uninstall()

        await storage.flush()
        tool_calls = await storage.query_tool_calls(QueryFilters())
        assert tool_calls == []

    async def test_tool_stream_emits_both_events(self, storage: SQLiteBackend) -> None:
        """A tool-use streaming response produces LLMCallEvent + ToolCallEvent."""
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline, parser_registry=build_default_registry()
            )
            interceptor.install()
            try:
                _run_streaming_request(
                    interceptor, _ANTHROPIC_URL, _REQUEST_BODY, _ANTHROPIC_TOOL_SSE
                )
            finally:
                interceptor.uninstall()

        await storage.flush()
        llm_calls = await storage.query_llm_calls(LLMQueryFilters())
        tool_calls = await storage.query_tool_calls(QueryFilters())

        assert len(llm_calls) == 1
        assert llm_calls[0]["token_input"] == 200
        assert llm_calls[0]["token_output"] == 80
        assert llm_calls[0]["finish_reason"] == "tool_use"

        assert len(tool_calls) == 1
        assert tool_calls[0]["tool_name"] == "web_search"
        assert tool_calls[0]["status"] == "success"

    async def test_tool_stream_input_payload_assembled(self, storage: SQLiteBackend) -> None:
        """Tool input JSON that was split across SSE deltas is correctly assembled."""
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline, parser_registry=build_default_registry()
            )
            interceptor.install()
            try:
                _run_streaming_request(
                    interceptor, _ANTHROPIC_URL, _REQUEST_BODY, _ANTHROPIC_TOOL_SSE
                )
            finally:
                interceptor.uninstall()

        await storage.flush()
        tool_calls = await storage.query_tool_calls(QueryFilters())
        payload = json.loads(tool_calls[0]["input_payload"])
        assert payload == {"query": "AI research"}

    async def test_async_stream_emits_llm_event(self, storage: SQLiteBackend) -> None:
        """Async streaming path also emits events."""
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline, parser_registry=build_default_registry()
            )
            interceptor.install()
            try:
                await _run_async_streaming_request(
                    interceptor, _ANTHROPIC_URL, _REQUEST_BODY, _ANTHROPIC_TEXT_SSE
                )
            finally:
                interceptor.uninstall()

        llm_calls = await storage.query_llm_calls(LLMQueryFilters())
        assert len(llm_calls) == 1
        assert llm_calls[0]["token_input"] == 150
        assert llm_calls[0]["token_output"] == 60


# ---------------------------------------------------------------------------
# OpenAI streaming tests
# ---------------------------------------------------------------------------


class TestOpenAIStreamingFlow:
    async def test_text_stream_emits_llm_event(self, storage: SQLiteBackend) -> None:
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline, parser_registry=build_default_registry()
            )
            interceptor.install()
            try:
                _run_streaming_request(interceptor, _OPENAI_URL, _OPENAI_REQUEST, _OPENAI_TEXT_SSE)
            finally:
                interceptor.uninstall()

        llm_calls = await storage.query_llm_calls(LLMQueryFilters())
        assert len(llm_calls) == 1
        assert llm_calls[0]["model"] == "gpt-4o"
        assert llm_calls[0]["token_input"] == 10
        assert llm_calls[0]["token_output"] == 5

    async def test_tool_stream_emits_both_events(self, storage: SQLiteBackend) -> None:
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline, parser_registry=build_default_registry()
            )
            interceptor.install()
            try:
                _run_streaming_request(interceptor, _OPENAI_URL, _OPENAI_REQUEST, _OPENAI_TOOL_SSE)
            finally:
                interceptor.uninstall()

        await storage.flush()
        tool_calls = await storage.query_tool_calls(QueryFilters())
        assert len(tool_calls) == 1
        assert tool_calls[0]["tool_name"] == "search"


# ---------------------------------------------------------------------------
# Gemini streaming tests
# ---------------------------------------------------------------------------


class TestGeminiStreamingFlow:
    async def test_text_stream_emits_llm_event(self, storage: SQLiteBackend) -> None:
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline, parser_registry=build_default_registry()
            )
            interceptor.install()
            try:
                _run_streaming_request(interceptor, _GEMINI_URL, _GEMINI_REQUEST, _GEMINI_TEXT_SSE)
            finally:
                interceptor.uninstall()

        llm_calls = await storage.query_llm_calls(LLMQueryFilters())
        assert len(llm_calls) == 1
        assert llm_calls[0]["model"] == "gemini-2.0-flash"
        assert llm_calls[0]["token_input"] == 10
        assert llm_calls[0]["token_output"] == 5

    async def test_tool_stream_emits_both_events(self, storage: SQLiteBackend) -> None:
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline, parser_registry=build_default_registry()
            )
            interceptor.install()
            try:
                _run_streaming_request(interceptor, _GEMINI_URL, _GEMINI_REQUEST, _GEMINI_TOOL_SSE)
            finally:
                interceptor.uninstall()

        await storage.flush()
        tool_calls = await storage.query_tool_calls(QueryFilters())
        assert len(tool_calls) == 1
        assert tool_calls[0]["tool_name"] == "web_search"


# ---------------------------------------------------------------------------
# Non-streaming responses are still handled (regression)
# ---------------------------------------------------------------------------


class TestNonStreamingUnchanged:
    async def test_regular_json_response_still_processed(self, storage: SQLiteBackend) -> None:
        """Non-streaming JSON responses continue to work after the streaming changes."""
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline, parser_registry=build_default_registry()
            )
            interceptor.install()
            try:
                with respx.mock:
                    respx.post(_ANTHROPIC_URL).mock(
                        return_value=httpx.Response(
                            200,
                            json={
                                "model": "claude-3-5-sonnet-20241022",
                                "content": [{"type": "text", "text": "hi"}],
                                "stop_reason": "end_turn",
                                "usage": {"input_tokens": 100, "output_tokens": 20},
                            },
                        )
                    )
                    with httpx.Client() as client:
                        client.post(_ANTHROPIC_URL, json=_REQUEST_BODY)
            finally:
                interceptor.uninstall()

        llm_calls = await storage.query_llm_calls(LLMQueryFilters())
        assert len(llm_calls) == 1
        assert llm_calls[0]["token_input"] == 100
