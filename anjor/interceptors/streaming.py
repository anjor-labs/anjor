"""Streaming SSE interceptor — wraps httpx byte streams to emit events after exhaustion.

Design:
- _SyncAccumulatingStream / _AsyncAccumulatingStream wrap response._stream in-place.
  Every byte chunk is forwarded to the caller unchanged (transparent), and a copy is
  kept locally.  When the stream is fully exhausted a sync callback fires with all
  accumulated bytes so events can be parsed and enqueued.
- parse_sse_events() splits raw SSE bytes into a list of data dicts.
- accumulate_anthropic/openai/gemini() rebuild a synthetic "response body" dict from
  the SSE events that is structurally identical to what a non-streaming call would
  return, so the existing parsers work without modification.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Callable, Iterator
from typing import Any

import httpx

# Provider URL substrings — kept in sync with the parser modules.
_ANTHROPIC_URL = "api.anthropic.com/v1/messages"
_OPENAI_URL = "api.openai.com/v1/chat/completions"
_GEMINI_URL = "generativelanguage.googleapis.com"


# ---------------------------------------------------------------------------
# SSE byte-stream parsing
# ---------------------------------------------------------------------------


def parse_sse_events(raw: bytes) -> list[dict[str, Any]]:
    """Parse raw SSE bytes into a list of JSON data dicts.

    Each blank-line-separated block is one SSE message.  Lines starting with
    "event:" are stored under the "__event__" key.  Lines starting with
    "data:" are JSON-decoded; non-JSON and "[DONE]" sentinels are skipped.
    A message with no parseable data line is omitted.
    """
    text = raw.decode("utf-8", errors="replace")
    result: list[dict[str, Any]] = []

    for block in text.split("\n\n"):
        event_type: str | None = None
        data_str: str | None = None

        for line in block.split("\n"):
            line = line.rstrip("\r")
            if line.startswith("event: "):
                event_type = line[7:].strip()
            elif line.startswith("data: "):
                data_str = line[6:]

        if data_str is None or data_str.strip() == "[DONE]":
            continue
        try:
            data: dict[str, Any] = json.loads(data_str)
        except (json.JSONDecodeError, ValueError):
            continue
        if not isinstance(data, dict):
            continue
        if event_type is not None:
            data["__event__"] = event_type
        result.append(data)

    return result


# ---------------------------------------------------------------------------
# Provider-specific accumulators
# ---------------------------------------------------------------------------


def accumulate_anthropic(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconstruct a synthetic Anthropic /v1/messages response from SSE events.

    Extracts model, token counts, stop_reason, text blocks, and tool-use blocks
    (with fully reassembled input JSON) from the stream event sequence.
    """
    model: str = ""
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation: int = 0
    cache_read: int = 0
    stop_reason: str | None = None

    # Index → accumulated block state
    blocks: dict[int, dict[str, Any]] = {}

    for evt in events:
        etype: str = evt.get("__event__") or evt.get("type") or ""

        if etype == "message_start":
            msg = evt.get("message") or {}
            model = msg.get("model", model)
            usage = msg.get("usage") or {}
            input_tokens = usage.get("input_tokens", input_tokens)
            cache_creation = usage.get("cache_creation_input_tokens", cache_creation)
            cache_read = usage.get("cache_read_input_tokens", cache_read)

        elif etype == "content_block_start":
            idx: int = evt.get("index", 0)
            cb = evt.get("content_block") or {}
            cb_type = cb.get("type", "")
            if cb_type == "tool_use":
                blocks[idx] = {
                    "type": "tool_use",
                    "id": cb.get("id", ""),
                    "name": cb.get("name", ""),
                    "_json_buf": "",
                }
            elif cb_type == "text":
                blocks[idx] = {"type": "text", "_text_buf": ""}

        elif etype == "content_block_delta":
            idx = evt.get("index", 0)
            delta = evt.get("delta") or {}
            block = blocks.get(idx)
            if block is not None:
                dtype = delta.get("type", "")
                if dtype == "input_json_delta":
                    block["_json_buf"] = block.get("_json_buf", "") + delta.get("partial_json", "")
                elif dtype == "text_delta":
                    block["_text_buf"] = block.get("_text_buf", "") + delta.get("text", "")

        elif etype == "message_delta":
            stop_reason = (evt.get("delta") or {}).get("stop_reason", stop_reason)
            output_tokens = (evt.get("usage") or {}).get("output_tokens", output_tokens)

    # Build content list in index order
    content: list[dict[str, Any]] = []
    for idx in sorted(blocks):
        block = blocks[idx]
        if block["type"] == "text":
            content.append({"type": "text", "text": block.get("_text_buf", "")})
        elif block["type"] == "tool_use":
            raw_json = block.get("_json_buf") or "{}"
            try:
                tool_input: dict[str, Any] = json.loads(raw_json)
                if not isinstance(tool_input, dict):
                    tool_input = {}
            except (json.JSONDecodeError, ValueError):
                tool_input = {}
            content.append(
                {
                    "type": "tool_use",
                    "id": block.get("id", ""),
                    "name": block.get("name", ""),
                    "input": tool_input,
                }
            )

    return {
        "model": model,
        "content": content,
        "stop_reason": stop_reason,
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cache_creation_input_tokens": cache_creation,
            "cache_read_input_tokens": cache_read,
        },
    }


def accumulate_openai(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconstruct a synthetic OpenAI /v1/chat/completions response from SSE events.

    Merges text content deltas, reassembles tool call arguments, and picks up
    usage from the optional trailing usage chunk (stream_options.include_usage).
    """
    model: str = ""
    finish_reason: str | None = None
    text_parts: list[str] = []
    # tool call index → accumulated state
    tool_calls: dict[int, dict[str, Any]] = {}
    prompt_tokens: int = 0
    completion_tokens: int = 0
    cached_tokens: int = 0

    for evt in events:
        model = model or evt.get("model", "")

        choices = evt.get("choices") or []
        if choices and isinstance(choices[0], dict):
            choice = choices[0]
            finish_reason = choice.get("finish_reason") or finish_reason
            delta = choice.get("delta") or {}
            if delta.get("content"):
                text_parts.append(delta["content"])
            for tc_delta in delta.get("tool_calls") or []:
                if not isinstance(tc_delta, dict):
                    continue
                i: int = tc_delta.get("index", 0)
                if i not in tool_calls:
                    tool_calls[i] = {
                        "id": "",
                        "type": "function",
                        "function": {"name": "", "arguments": ""},
                    }
                tc = tool_calls[i]
                tc["id"] = tc_delta.get("id") or tc["id"]
                func = tc_delta.get("function") or {}
                tc["function"]["name"] = func.get("name") or tc["function"]["name"]
                tc["function"]["arguments"] += func.get("arguments", "")

        # Usage chunk (sent when stream_options.include_usage=true)
        usage = evt.get("usage")
        if usage and isinstance(usage, dict):
            prompt_tokens = usage.get("prompt_tokens", prompt_tokens)
            completion_tokens = usage.get("completion_tokens", completion_tokens)
            details = usage.get("prompt_tokens_details") or {}
            cached_tokens = details.get("cached_tokens", cached_tokens)

    message: dict[str, Any] = {
        "role": "assistant",
        "content": "".join(text_parts) if text_parts else None,
    }
    if tool_calls:
        message["tool_calls"] = [tool_calls[i] for i in sorted(tool_calls)]

    result: dict[str, Any] = {
        "model": model,
        "choices": [{"message": message, "finish_reason": finish_reason}],
    }
    if prompt_tokens or completion_tokens:
        result["usage"] = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        if cached_tokens:
            result["usage"]["prompt_tokens_details"] = {"cached_tokens": cached_tokens}

    return result


def accumulate_gemini(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Reconstruct a synthetic Gemini generateContent response from SSE events.

    Gemini streams complete GenerateContentResponse objects.  We use the last
    event for metadata (it carries the final usageMetadata) and collect all
    functionCall parts across every event.
    """
    if not events:
        return {}

    last = events[-1]

    # Collect all function-call parts from every chunk
    fn_parts: list[dict[str, Any]] = []
    for evt in events:
        for candidate in evt.get("candidates") or []:
            if not isinstance(candidate, dict):
                continue
            for part in (candidate.get("content") or {}).get("parts") or []:
                if isinstance(part, dict) and "functionCall" in part:
                    fn_parts.append(part)

    if not fn_parts:
        return last

    # Inject collected function-call parts into the first candidate of the last event
    result = dict(last)
    candidates = list(result.get("candidates") or [])
    if candidates and isinstance(candidates[0], dict):
        first = dict(candidates[0])
        content = dict(first.get("content") or {})
        content["parts"] = fn_parts
        first["content"] = content
        candidates[0] = first
        result["candidates"] = candidates
    return result


# ---------------------------------------------------------------------------
# URL router
# ---------------------------------------------------------------------------


def build_stream_response_body(url: str, events: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Route SSE events to the right accumulator based on the request URL.

    Returns None for unknown URLs (no events will be emitted).
    """
    if _ANTHROPIC_URL in url:
        return accumulate_anthropic(events)
    if _OPENAI_URL in url:
        return accumulate_openai(events)
    if _GEMINI_URL in url:
        return accumulate_gemini(events)
    return None


# ---------------------------------------------------------------------------
# httpx stream wrappers
# ---------------------------------------------------------------------------


class _SyncAccumulatingStream(httpx.SyncByteStream):
    """Wraps a synchronous httpx byte-stream to tee bytes and fire a callback on exhaustion.

    Subclasses httpx.SyncByteStream so that httpx.Response.close() passes its
    isinstance check before calling stream.close().

    The callback is called with all accumulated bytes only after the stream is
    fully consumed — it is never called on a partial or abandoned stream.
    """

    def __init__(
        self,
        original: httpx.SyncByteStream,
        callback: Callable[[bytes], None],
    ) -> None:
        self._original = original
        self._callback = callback
        self._chunks: list[bytes] = []

    def __iter__(self) -> Iterator[bytes]:
        for chunk in self._original:
            self._chunks.append(chunk)
            yield chunk
        self._callback(b"".join(self._chunks))

    def close(self) -> None:
        self._original.close()


class _AsyncAccumulatingStream(httpx.AsyncByteStream):
    """Wraps an asynchronous httpx byte-stream to tee bytes and fire a callback on exhaustion.

    Subclasses httpx.AsyncByteStream so that httpx.Response.aclose() passes its
    isinstance check before calling stream.aclose().

    The callback is synchronous (pipeline.put is non-blocking) so no await is needed.
    """

    def __init__(
        self,
        original: httpx.AsyncByteStream,
        callback: Callable[[bytes], None],
    ) -> None:
        self._original = original
        self._callback = callback
        self._chunks: list[bytes] = []

    async def __aiter__(self) -> AsyncIterator[bytes]:
        async for chunk in self._original:
            self._chunks.append(chunk)
            yield chunk
        self._callback(b"".join(self._chunks))

    async def aclose(self) -> None:
        await self._original.aclose()
