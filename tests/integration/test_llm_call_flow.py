"""Integration test: AnthropicParser emits LLMCallEvent → stored in llm_calls table."""

from __future__ import annotations

import httpx
import pytest
import respx

from anjor.collector.storage.base import LLMQueryFilters, QueryFilters
from anjor.collector.storage.sqlite import SQLiteBackend
from anjor.core.events.base import BaseEvent
from anjor.core.pipeline.pipeline import EventPipeline
from anjor.interceptors.parsers.registry import build_default_registry
from anjor.interceptors.patch import PatchInterceptor

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

_TOOL_RESPONSE = {
    "id": "msg_01",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "tool_use",
            "id": "toolu_01",
            "name": "web_search",
            "input": {"query": "latest AI research"},
        }
    ],
    "stop_reason": "tool_use",
    "model": "claude-3-5-sonnet-20241022",
    "usage": {"input_tokens": 200, "output_tokens": 80},
}

_TEXT_RESPONSE = {
    "id": "msg_02",
    "type": "message",
    "role": "assistant",
    "content": [{"type": "text", "text": "Here is the result."}],
    "stop_reason": "end_turn",
    "model": "claude-3-5-sonnet-20241022",
    "usage": {"input_tokens": 150, "output_tokens": 60},
}

_REQUEST_BODY = {
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "system": "You are a research assistant.",
    "messages": [{"role": "user", "content": "Search for AI research"}],
}


class StorageWritingHandler:
    name = "storage_writer"

    def __init__(self, storage: SQLiteBackend) -> None:
        self.storage = storage

    async def handle(self, event: BaseEvent) -> None:
        await self.storage.write_event(event.model_dump(mode="json"))


@pytest.fixture
async def storage() -> SQLiteBackend:
    s = SQLiteBackend(db_path=":memory:", batch_size=1, batch_interval_ms=9999)
    await s.connect()
    yield s
    await s.close()


class TestLLMCallFlow:
    async def test_tool_call_stores_both_events(
        self, storage: SQLiteBackend
    ) -> None:
        """A tool-use response produces both LLMCallEvent and ToolCallEvent."""
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline,
                parser_registry=build_default_registry(),
            )
            interceptor.install()
            try:
                with respx.mock:
                    respx.post(_ANTHROPIC_URL).mock(
                        return_value=httpx.Response(200, json=_TOOL_RESPONSE)
                    )
                    with httpx.Client() as client:
                        client.post(
                            _ANTHROPIC_URL,
                            json=_REQUEST_BODY,
                            headers={"x-api-key": "test-key"},
                        )
            finally:
                interceptor.uninstall()

        tool_calls = await storage.query_tool_calls(QueryFilters())
        llm_calls = await storage.query_llm_calls(LLMQueryFilters())

        assert len(tool_calls) == 1
        assert tool_calls[0]["tool_name"] == "web_search"

        assert len(llm_calls) == 1
        assert llm_calls[0]["model"] == "claude-3-5-sonnet-20241022"
        assert llm_calls[0]["token_input"] == 200
        assert llm_calls[0]["token_output"] == 80

    async def test_text_only_response_stores_only_llm_event(
        self, storage: SQLiteBackend
    ) -> None:
        """A text-only response produces only LLMCallEvent (no tool calls)."""
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline,
                parser_registry=build_default_registry(),
            )
            interceptor.install()
            try:
                with respx.mock:
                    respx.post(_ANTHROPIC_URL).mock(
                        return_value=httpx.Response(200, json=_TEXT_RESPONSE)
                    )
                    with httpx.Client() as client:
                        client.post(
                            _ANTHROPIC_URL,
                            json=_REQUEST_BODY,
                            headers={"x-api-key": "test-key"},
                        )
            finally:
                interceptor.uninstall()

        tool_calls = await storage.query_tool_calls(QueryFilters())
        llm_calls = await storage.query_llm_calls(LLMQueryFilters())

        assert tool_calls == []
        assert len(llm_calls) == 1
        assert llm_calls[0]["finish_reason"] == "end_turn"

    async def test_system_prompt_hash_stored(
        self, storage: SQLiteBackend
    ) -> None:
        """System prompt hash is captured and stored in llm_calls."""
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline,
                parser_registry=build_default_registry(),
            )
            interceptor.install()
            try:
                with respx.mock:
                    respx.post(_ANTHROPIC_URL).mock(
                        return_value=httpx.Response(200, json=_TEXT_RESPONSE)
                    )
                    with httpx.Client() as client:
                        client.post(
                            _ANTHROPIC_URL,
                            json=_REQUEST_BODY,
                            headers={"x-api-key": "test-key"},
                        )
            finally:
                interceptor.uninstall()

        llm_calls = await storage.query_llm_calls(LLMQueryFilters())
        assert len(llm_calls) == 1
        assert llm_calls[0]["system_prompt_hash"] is not None
        assert len(llm_calls[0]["system_prompt_hash"]) == 64  # SHA-256

    async def test_context_utilisation_stored(
        self, storage: SQLiteBackend
    ) -> None:
        """Context utilisation is computed and stored."""
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline,
                parser_registry=build_default_registry(),
            )
            interceptor.install()
            try:
                with respx.mock:
                    respx.post(_ANTHROPIC_URL).mock(
                        return_value=httpx.Response(200, json=_TEXT_RESPONSE)
                    )
                    with httpx.Client() as client:
                        client.post(
                            _ANTHROPIC_URL,
                            json=_REQUEST_BODY,
                            headers={"x-api-key": "test-key"},
                        )
            finally:
                interceptor.uninstall()

        llm_calls = await storage.query_llm_calls(LLMQueryFilters())
        assert llm_calls[0]["context_utilisation"] is not None
        assert 0.0 < llm_calls[0]["context_utilisation"] < 1.0

    async def test_trace_id_consistent_across_events(
        self, storage: SQLiteBackend
    ) -> None:
        """LLMCallEvent and ToolCallEvent for the same request share trace_id."""
        req = {**_REQUEST_BODY, "metadata": {"trace_id": "shared-trace-123"}}
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline,
                parser_registry=build_default_registry(),
            )
            interceptor.install()
            try:
                with respx.mock:
                    respx.post(_ANTHROPIC_URL).mock(
                        return_value=httpx.Response(200, json=_TOOL_RESPONSE)
                    )
                    with httpx.Client() as client:
                        client.post(
                            _ANTHROPIC_URL,
                            json=req,
                            headers={"x-api-key": "test-key"},
                        )
            finally:
                interceptor.uninstall()

        tool_calls = await storage.query_tool_calls(QueryFilters())
        llm_calls = await storage.query_llm_calls(LLMQueryFilters())

        assert tool_calls[0]["trace_id"] == "shared-trace-123"
        assert llm_calls[0]["trace_id"] == "shared-trace-123"
