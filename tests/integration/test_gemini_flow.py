"""Integration test: GeminiParser emits LLMCallEvent + ToolCallEvent end-to-end."""

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

_GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent"
)

_REQUEST_BODY = {
    "contents": [
        {"role": "user", "parts": [{"text": "Find recent AI papers"}]},
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
                            "name": "arxiv_search",
                            "args": {"query": "recent AI papers"},
                        }
                    }
                ],
            },
            "finishReason": "STOP",
        }
    ],
    "usageMetadata": {"promptTokenCount": 140, "candidatesTokenCount": 35},
}


class StorageWritingHandler:
    name = "storage_writer"

    def __init__(self, storage: SQLiteBackend) -> None:
        self.storage = storage

    async def handle(self, event: BaseEvent) -> None:
        await self.storage.write_event(event.model_dump(mode="json"))


@pytest.fixture
async def storage() -> SQLiteBackend:  # type: ignore[misc]
    s = SQLiteBackend(db_path=":memory:", batch_size=1, batch_interval_ms=9999)
    await s.connect()
    yield s
    await s.close()


class TestGeminiFlow:
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
                    respx.post(_GEMINI_URL).mock(
                        return_value=httpx.Response(200, json=_TOOL_RESPONSE)
                    )
                    async with httpx.AsyncClient() as client:
                        await client.post(_GEMINI_URL, json=_REQUEST_BODY)
            finally:
                interceptor.uninstall()

        tool_calls = await storage.query_tool_calls(QueryFilters(limit=10))
        llm_calls = await storage.query_llm_calls(LLMQueryFilters(limit=10))

        assert len(tool_calls) == 1
        assert tool_calls[0]["tool_name"] == "arxiv_search"
        assert tool_calls[0]["status"] == "success"

        assert len(llm_calls) == 1
        assert llm_calls[0]["model"] == "gemini-2.0-flash"
        assert llm_calls[0]["token_input"] == 140
        assert llm_calls[0]["token_output"] == 35
        assert llm_calls[0]["finish_reason"] == "STOP"

    async def test_text_only_stores_llm_event_only(self, storage: SQLiteBackend) -> None:
        text_response = {
            "modelVersion": "gemini-2.0-flash",
            "candidates": [
                {
                    "content": {"role": "model", "parts": [{"text": "Here is the answer."}]},
                    "finishReason": "STOP",
                }
            ],
            "usageMetadata": {"promptTokenCount": 90, "candidatesTokenCount": 25},
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
                    respx.post(_GEMINI_URL).mock(
                        return_value=httpx.Response(200, json=text_response)
                    )
                    async with httpx.AsyncClient() as client:
                        await client.post(_GEMINI_URL, json=_REQUEST_BODY)
            finally:
                interceptor.uninstall()

        tool_calls = await storage.query_tool_calls(QueryFilters(limit=10))
        llm_calls = await storage.query_llm_calls(LLMQueryFilters(limit=10))

        assert len(tool_calls) == 0
        assert len(llm_calls) == 1
        assert llm_calls[0]["finish_reason"] == "STOP"
