"""Integration test: OpenAIParser emits LLMCallEvent + ToolCallEvent end-to-end."""

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

_OPENAI_URL = "https://api.openai.com/v1/chat/completions"

_REQUEST_BODY = {
    "model": "gpt-4o",
    "messages": [
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "Search for recent AI news"},
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
                            "name": "web_search",
                            "arguments": '{"query": "recent AI news"}',
                        },
                    }
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 150, "completion_tokens": 40, "total_tokens": 190},
}


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


class TestOpenAIFlow:
    async def test_tool_call_stores_both_events(self, storage: SQLiteBackend) -> None:
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline,
                parser_registry=build_default_registry(),
            )
            interceptor.install()
            try:
                with respx.mock:
                    respx.post(_OPENAI_URL).mock(
                        return_value=httpx.Response(200, json=_TOOL_RESPONSE)
                    )
                    async with httpx.AsyncClient() as client:
                        await client.post(_OPENAI_URL, json=_REQUEST_BODY)
            finally:
                interceptor.uninstall()

        await storage.flush()
        tool_calls = await storage.query_tool_calls(QueryFilters(limit=10))
        llm_calls = await storage.query_llm_calls(LLMQueryFilters(limit=10))

        assert len(tool_calls) == 1
        assert tool_calls[0]["tool_name"] == "web_search"
        assert tool_calls[0]["status"] == "success"

        assert len(llm_calls) == 1
        assert llm_calls[0]["model"] == "gpt-4o-2024-08-06"
        assert llm_calls[0]["token_input"] == 150
        assert llm_calls[0]["token_output"] == 40
        assert llm_calls[0]["finish_reason"] == "tool_calls"

    async def test_text_only_stores_llm_event_only(self, storage: SQLiteBackend) -> None:
        text_response = {
            "id": "chatcmpl-002",
            "model": "gpt-4o",
            "choices": [
                {
                    "message": {"role": "assistant", "content": "Here is the answer."},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 80, "completion_tokens": 20, "total_tokens": 100},
        }
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline,
                parser_registry=build_default_registry(),
            )
            interceptor.install()
            try:
                with respx.mock:
                    respx.post(_OPENAI_URL).mock(
                        return_value=httpx.Response(200, json=text_response)
                    )
                    async with httpx.AsyncClient() as client:
                        await client.post(_OPENAI_URL, json=_REQUEST_BODY)
            finally:
                interceptor.uninstall()

        await storage.flush()
        tool_calls = await storage.query_tool_calls(QueryFilters(limit=10))
        llm_calls = await storage.query_llm_calls(LLMQueryFilters(limit=10))

        assert len(tool_calls) == 0
        assert len(llm_calls) == 1
        assert llm_calls[0]["finish_reason"] == "stop"
