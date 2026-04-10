"""Integration test: PatchInterceptor → ParserRegistry → Pipeline → SQLiteBackend."""

from __future__ import annotations

import httpx
import pytest
import respx

from agentscope.collector.storage.base import QueryFilters
from agentscope.collector.storage.sqlite import SQLiteBackend
from agentscope.core.events.base import BaseEvent
from agentscope.core.pipeline.pipeline import EventPipeline
from agentscope.interceptors.patch import PatchInterceptor
from agentscope.interceptors.parsers.registry import build_default_registry

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
    "usage": {"input_tokens": 200, "output_tokens": 80},
}

_REQUEST_BODY = {
    "model": "claude-3-5-sonnet-20241022",
    "max_tokens": 1024,
    "messages": [{"role": "user", "content": "Search for AI research"}],
}


class StorageWritingHandler:
    """Handler that writes events to storage."""

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


class TestPatchToStorage:
    async def test_sync_request_captured_and_stored(
        self, storage: SQLiteBackend
    ) -> None:
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
        # Pipeline stopped (drained) — handler was called

        results = await storage.query_tool_calls(QueryFilters())
        assert len(results) == 1
        assert results[0]["tool_name"] == "web_search"

    async def test_async_request_captured_and_stored(
        self, storage: SQLiteBackend
    ) -> None:
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
                    async with httpx.AsyncClient() as client:
                        await client.post(
                            _ANTHROPIC_URL,
                            json=_REQUEST_BODY,
                            headers={"x-api-key": "test-key"},
                        )
            finally:
                interceptor.uninstall()

        results = await storage.query_tool_calls(QueryFilters())
        assert len(results) == 1
        assert results[0]["tool_name"] == "web_search"

    async def test_non_anthropic_url_not_stored(
        self, storage: SQLiteBackend
    ) -> None:
        handler = StorageWritingHandler(storage)
        async with EventPipeline(handlers=[handler]) as pipeline:
            interceptor = PatchInterceptor(
                pipeline=pipeline,
                parser_registry=build_default_registry(),
            )
            interceptor.install()
            try:
                with respx.mock:
                    respx.get("https://example.com/api").mock(
                        return_value=httpx.Response(200, json={"ok": True})
                    )
                    with httpx.Client() as client:
                        client.get("https://example.com/api")
            finally:
                interceptor.uninstall()

        results = await storage.query_tool_calls(QueryFilters())
        assert results == []

    async def test_api_error_stored_as_failure(
        self, storage: SQLiteBackend
    ) -> None:
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
                        return_value=httpx.Response(
                            429,
                            json={"error": {"type": "rate_limit", "message": "too many"}},
                        )
                    )
                    with httpx.Client() as client:
                        client.post(
                            _ANTHROPIC_URL,
                            json=_REQUEST_BODY,
                            headers={"x-api-key": "test"},
                        )
            finally:
                interceptor.uninstall()

        results = await storage.query_tool_calls(QueryFilters())
        assert len(results) == 1
        assert results[0]["status"] == "failure"
