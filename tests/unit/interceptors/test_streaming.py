"""Unit tests for the streaming SSE accumulator module."""

from __future__ import annotations

import json

import httpx

from anjor.interceptors.streaming import (
    _AsyncAccumulatingStream,
    _SyncAccumulatingStream,
    accumulate_anthropic,
    accumulate_gemini,
    accumulate_openai,
    build_stream_response_body,
    parse_sse_events,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _sse(*blocks: str) -> bytes:
    """Join SSE blocks separated by blank lines."""
    return ("\n\n".join(blocks) + "\n\n").encode()


def _evt(event_type: str, data: object) -> str:
    return f"event: {event_type}\ndata: {json.dumps(data)}"


def _data(data: object) -> str:
    return f"data: {json.dumps(data)}"


# ---------------------------------------------------------------------------
# parse_sse_events
# ---------------------------------------------------------------------------


class TestParseSSEEvents:
    def test_empty_bytes_returns_empty_list(self) -> None:
        assert parse_sse_events(b"") == []

    def test_done_sentinel_skipped(self) -> None:
        raw = b"data: [DONE]\n\n"
        assert parse_sse_events(raw) == []

    def test_event_and_data_parsed(self) -> None:
        raw = _sse(_evt("message_start", {"type": "message_start", "message": {}}))
        events = parse_sse_events(raw)
        assert len(events) == 1
        assert events[0]["__event__"] == "message_start"
        assert events[0]["type"] == "message_start"

    def test_data_only_no_event_field(self) -> None:
        raw = _sse(_data({"model": "gpt-4o", "choices": []}))
        events = parse_sse_events(raw)
        assert len(events) == 1
        assert "__event__" not in events[0]
        assert events[0]["model"] == "gpt-4o"

    def test_malformed_json_skipped(self) -> None:
        raw = b"data: not-json\n\ndata: {}\n\n"
        events = parse_sse_events(raw)
        assert len(events) == 1

    def test_multiple_blocks_all_parsed(self) -> None:
        raw = _sse(
            _evt("message_start", {"type": "message_start"}),
            _evt("message_stop", {"type": "message_stop"}),
        )
        assert len(parse_sse_events(raw)) == 2

    def test_windows_line_endings_handled(self) -> None:
        raw = b'data: {"k": 1}\r\n\r\n'
        events = parse_sse_events(raw)
        assert len(events) == 1
        assert events[0]["k"] == 1


# ---------------------------------------------------------------------------
# accumulate_anthropic
# ---------------------------------------------------------------------------


_ANTHROPIC_TEXT_SSE = _sse(
    _evt(
        "message_start",
        {
            "type": "message_start",
            "message": {
                "model": "claude-3-5-sonnet-20241022",
                "usage": {
                    "input_tokens": 150,
                    "output_tokens": 1,
                    "cache_creation_input_tokens": 20,
                    "cache_read_input_tokens": 10,
                },
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
            "delta": {"type": "text_delta", "text": "Hello!"},
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
                "id": "toolu_01",
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
            "delta": {"type": "input_json_delta", "partial_json": '"latest news"}'},
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


class TestAccumulateAnthropic:
    def _body(self, raw: bytes) -> dict:
        return accumulate_anthropic(parse_sse_events(raw))

    def test_text_model_extracted(self) -> None:
        body = self._body(_ANTHROPIC_TEXT_SSE)
        assert body["model"] == "claude-3-5-sonnet-20241022"

    def test_text_token_counts(self) -> None:
        body = self._body(_ANTHROPIC_TEXT_SSE)
        assert body["usage"]["input_tokens"] == 150
        assert body["usage"]["output_tokens"] == 60

    def test_text_cache_tokens(self) -> None:
        body = self._body(_ANTHROPIC_TEXT_SSE)
        assert body["usage"]["cache_creation_input_tokens"] == 20
        assert body["usage"]["cache_read_input_tokens"] == 10

    def test_text_stop_reason(self) -> None:
        assert self._body(_ANTHROPIC_TEXT_SSE)["stop_reason"] == "end_turn"

    def test_text_content_block(self) -> None:
        content = self._body(_ANTHROPIC_TEXT_SSE)["content"]
        assert len(content) == 1
        assert content[0]["type"] == "text"
        assert content[0]["text"] == "Hello!"

    def test_tool_use_name_and_id(self) -> None:
        content = self._body(_ANTHROPIC_TOOL_SSE)["content"]
        assert len(content) == 1
        assert content[0]["type"] == "tool_use"
        assert content[0]["name"] == "web_search"
        assert content[0]["id"] == "toolu_01"

    def test_tool_use_input_json_reassembled(self) -> None:
        content = self._body(_ANTHROPIC_TOOL_SSE)["content"]
        assert content[0]["input"] == {"query": "latest news"}

    def test_tool_use_token_counts(self) -> None:
        body = self._body(_ANTHROPIC_TOOL_SSE)
        assert body["usage"]["input_tokens"] == 200
        assert body["usage"]["output_tokens"] == 80

    def test_empty_events_returns_empty_content(self) -> None:
        body = accumulate_anthropic([])
        assert body["content"] == []
        assert body["model"] == ""


# ---------------------------------------------------------------------------
# accumulate_openai
# ---------------------------------------------------------------------------


_OPENAI_TEXT_SSE = _sse(
    _data(
        {
            "model": "gpt-4o",
            "choices": [
                {"index": 0, "delta": {"role": "assistant", "content": "Hi"}, "finish_reason": None}
            ],
        }
    ),
    _data(
        {
            "model": "gpt-4o",
            "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
        }
    ),
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
                                "id": "call_01",
                                "type": "function",
                                "function": {"name": "web_search", "arguments": ""},
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
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"q":"'}}]},
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
                    "delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'news"}'}}]},
                    "finish_reason": "tool_calls",
                }
            ],
        }
    ),
    "data: [DONE]",
)


class TestAccumulateOpenAI:
    def _body(self, raw: bytes) -> dict:
        return accumulate_openai(parse_sse_events(raw))

    def test_model_extracted(self) -> None:
        assert self._body(_OPENAI_TEXT_SSE)["model"] == "gpt-4o"

    def test_text_content_accumulated(self) -> None:
        msg = self._body(_OPENAI_TEXT_SSE)["choices"][0]["message"]
        assert msg["content"] == "Hi"

    def test_finish_reason(self) -> None:
        choice = self._body(_OPENAI_TEXT_SSE)["choices"][0]
        assert choice["finish_reason"] == "stop"

    def test_usage_included_when_present(self) -> None:
        body = self._body(_OPENAI_TEXT_SSE)
        assert body["usage"]["prompt_tokens"] == 10
        assert body["usage"]["completion_tokens"] == 5

    def test_tool_call_name_and_id(self) -> None:
        msg = self._body(_OPENAI_TOOL_SSE)["choices"][0]["message"]
        assert "tool_calls" in msg
        assert msg["tool_calls"][0]["function"]["name"] == "web_search"
        assert msg["tool_calls"][0]["id"] == "call_01"

    def test_tool_call_arguments_reassembled(self) -> None:
        msg = self._body(_OPENAI_TOOL_SSE)["choices"][0]["message"]
        assert msg["tool_calls"][0]["function"]["arguments"] == '{"q":"news"}'

    def test_no_usage_chunk_omits_usage_key(self) -> None:
        raw = _sse(_data({"model": "gpt-4o", "choices": []}))
        body = accumulate_openai(parse_sse_events(raw))
        assert "usage" not in body

    def test_empty_events(self) -> None:
        body = accumulate_openai([])
        assert body["model"] == ""
        assert body["choices"][0]["message"]["content"] is None


# ---------------------------------------------------------------------------
# accumulate_gemini
# ---------------------------------------------------------------------------


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
                        "parts": [{"functionCall": {"name": "web_search", "args": {"q": "news"}}}],
                        "role": "model",
                    },
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 20, "candidatesTokenCount": 10},
            "modelVersion": "gemini-2.0-flash",
        }
    )
)


class TestAccumulateGemini:
    def _body(self, raw: bytes) -> dict:
        return accumulate_gemini(parse_sse_events(raw))

    def test_usage_metadata_preserved(self) -> None:
        body = self._body(_GEMINI_TEXT_SSE)
        assert body["usageMetadata"]["promptTokenCount"] == 10
        assert body["usageMetadata"]["candidatesTokenCount"] == 5

    def test_model_version_preserved(self) -> None:
        assert self._body(_GEMINI_TEXT_SSE)["modelVersion"] == "gemini-2.0-flash"

    def test_function_call_present(self) -> None:
        body = self._body(_GEMINI_TOOL_SSE)
        parts = body["candidates"][0]["content"]["parts"]
        assert parts[0]["functionCall"]["name"] == "web_search"

    def test_function_args_preserved(self) -> None:
        body = self._body(_GEMINI_TOOL_SSE)
        args = body["candidates"][0]["content"]["parts"][0]["functionCall"]["args"]
        assert args == {"q": "news"}

    def test_empty_events_returns_empty_dict(self) -> None:
        assert accumulate_gemini([]) == {}

    def test_multi_chunk_uses_last_for_metadata(self) -> None:
        first = {
            "candidates": [],
            "usageMetadata": {"promptTokenCount": 1, "candidatesTokenCount": 2},
            "modelVersion": "v1",
        }
        last = {
            "candidates": [],
            "usageMetadata": {"promptTokenCount": 10, "candidatesTokenCount": 20},
            "modelVersion": "v2",
        }
        body = accumulate_gemini([first, last])
        assert body["usageMetadata"]["promptTokenCount"] == 10
        assert body["modelVersion"] == "v2"


# ---------------------------------------------------------------------------
# build_stream_response_body routing
# ---------------------------------------------------------------------------


class TestBuildStreamResponseBody:
    def test_anthropic_url_routes_to_anthropic(self) -> None:
        body = build_stream_response_body(
            "https://api.anthropic.com/v1/messages", parse_sse_events(_ANTHROPIC_TEXT_SSE)
        )
        assert body is not None
        assert "content" in body
        assert body["model"] == "claude-3-5-sonnet-20241022"

    def test_openai_url_routes_to_openai(self) -> None:
        body = build_stream_response_body(
            "https://api.openai.com/v1/chat/completions", parse_sse_events(_OPENAI_TEXT_SSE)
        )
        assert body is not None
        assert "choices" in body

    def test_gemini_url_routes_to_gemini(self) -> None:
        body = build_stream_response_body(
            "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:streamGenerateContent",
            parse_sse_events(_GEMINI_TEXT_SSE),
        )
        assert body is not None
        assert "candidates" in body

    def test_unknown_url_returns_none(self) -> None:
        assert build_stream_response_body("https://example.com/api", []) is None


# ---------------------------------------------------------------------------
# _SyncAccumulatingStream
# ---------------------------------------------------------------------------


class TestSyncAccumulatingStream:
    def test_all_chunks_forwarded(self) -> None:
        original = httpx.ByteStream(b"hello world")
        received: list[bytes] = []
        stream = _SyncAccumulatingStream(original, lambda _: None)
        for chunk in stream:
            received.append(chunk)
        assert b"".join(received) == b"hello world"

    def test_callback_called_with_accumulated_bytes(self) -> None:
        original = httpx.ByteStream(b"foobar")
        result: list[bytes] = []
        stream = _SyncAccumulatingStream(original, result.append)
        list(stream)  # exhaust
        assert result == [b"foobar"]

    def test_callback_not_called_if_not_iterated(self) -> None:
        original = httpx.ByteStream(b"data")
        called: list[bool] = []
        _SyncAccumulatingStream(original, lambda _: called.append(True))
        # never iterated → callback not called
        assert called == []

    def test_close_delegates_to_original(self) -> None:
        # httpx.ByteStream.close() is a no-op, but our wrapper must call it without error
        original = httpx.ByteStream(b"")
        stream = _SyncAccumulatingStream(original, lambda _: None)
        stream.close()  # should not raise

    def test_is_sync_byte_stream_subclass(self) -> None:
        stream = _SyncAccumulatingStream(httpx.ByteStream(b""), lambda _: None)
        assert isinstance(stream, httpx.SyncByteStream)


# ---------------------------------------------------------------------------
# _AsyncAccumulatingStream
# ---------------------------------------------------------------------------


class TestAsyncAccumulatingStream:
    async def test_all_chunks_forwarded(self) -> None:
        original = httpx.ByteStream(b"abc")
        received: list[bytes] = []
        stream = _AsyncAccumulatingStream(original, lambda _: None)
        async for chunk in stream:
            received.append(chunk)
        assert b"".join(received) == b"abc"

    async def test_callback_called_with_accumulated_bytes(self) -> None:
        original = httpx.ByteStream(b"xy")
        result: list[bytes] = []
        stream = _AsyncAccumulatingStream(original, result.append)
        async for _ in stream:
            pass
        assert result == [b"xy"]

    async def test_aclose_does_not_raise(self) -> None:
        stream = _AsyncAccumulatingStream(httpx.ByteStream(b""), lambda _: None)
        await stream.aclose()  # should not raise

    def test_is_async_byte_stream_subclass(self) -> None:
        stream = _AsyncAccumulatingStream(httpx.ByteStream(b""), lambda _: None)
        assert isinstance(stream, httpx.AsyncByteStream)
