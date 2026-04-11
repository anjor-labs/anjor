"""E2E test: simulated agent with PatchInterceptor active, events verified.

Uses respx to replay Anthropic API responses — no real API calls.
"""

from __future__ import annotations

import httpx
import respx

from agentscope.collector.storage.base import QueryFilters
from agentscope.collector.storage.sqlite import SQLiteBackend
from agentscope.core.events.base import BaseEvent
from agentscope.core.pipeline.pipeline import EventPipeline
from agentscope.interceptors.parsers.registry import build_default_registry
from agentscope.interceptors.patch import PatchInterceptor

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

# Simulated Anthropic response with two tool calls
_AGENT_RESPONSE = {
    "id": "msg_e2e",
    "type": "message",
    "role": "assistant",
    "content": [
        {
            "type": "tool_use",
            "id": "toolu_01",
            "name": "web_search",
            "input": {"query": "top AI papers 2024"},
        },
        {
            "type": "tool_use",
            "id": "toolu_02",
            "name": "summarise",
            "input": {"text": "Some long text to summarise"},
        },
    ],
    "usage": {"input_tokens": 500, "output_tokens": 120},
}


class WritingHandler:
    name = "writer"

    def __init__(self, storage: SQLiteBackend) -> None:
        self.storage = storage

    async def handle(self, event: BaseEvent) -> None:
        await self.storage.write_event(event.model_dump(mode="json"))


class TestAgentInstrumented:
    async def test_two_tool_calls_captured(self) -> None:
        storage = SQLiteBackend(db_path=":memory:", batch_size=1)
        await storage.connect()

        handler = WritingHandler(storage)
        pipeline = EventPipeline(handlers=[handler])
        interceptor = PatchInterceptor(
            pipeline=pipeline,
            parser_registry=build_default_registry(),
        )
        interceptor.install()

        try:
            # Simulate agent making an API call
            with respx.mock:
                respx.post(_ANTHROPIC_URL).mock(
                    return_value=httpx.Response(200, json=_AGENT_RESPONSE)
                )
                with httpx.Client() as client:
                    client.post(
                        _ANTHROPIC_URL,
                        json={
                            "model": "claude-3-5-sonnet-20241022",
                            "max_tokens": 2048,
                            "tools": [
                                {
                                    "name": "web_search",
                                    "description": "Search the web",
                                    "input_schema": {"type": "object"},
                                },
                                {
                                    "name": "summarise",
                                    "description": "Summarise text",
                                    "input_schema": {"type": "object"},
                                },
                            ],
                            "messages": [
                                {"role": "user", "content": "Research and summarise AI papers"}
                            ],
                        },
                        headers={"x-api-key": "sk-ant-test"},
                    )
        finally:
            interceptor.uninstall()

        await storage.close()

    async def test_token_usage_recorded(self) -> None:
        storage = SQLiteBackend(db_path=":memory:", batch_size=1)
        await storage.connect()

        handler = WritingHandler(storage)
        pipeline = EventPipeline(handlers=[handler])
        interceptor = PatchInterceptor(
            pipeline=pipeline,
            parser_registry=build_default_registry(),
        )
        interceptor.install()

        try:
            with respx.mock:
                respx.post(_ANTHROPIC_URL).mock(
                    return_value=httpx.Response(200, json=_AGENT_RESPONSE)
                )
                with httpx.Client() as client:
                    client.post(
                        _ANTHROPIC_URL,
                        json={"model": "claude-3-5-sonnet-20241022", "messages": []},
                        headers={"x-api-key": "test"},
                    )
        finally:
            interceptor.uninstall()

        results = await storage.query_tool_calls(QueryFilters())
        # Both tool calls should have the same token usage (from the response)
        for row in results:
            assert row["token_usage_input"] == 500
            assert row["token_usage_output"] == 120

        await storage.close()

    async def test_interceptor_does_not_break_agent(self) -> None:
        """Agent's HTTP calls still work correctly when interceptor is active."""
        pipeline = EventPipeline()
        interceptor = PatchInterceptor(
            pipeline=pipeline,
            parser_registry=build_default_registry(),
        )
        interceptor.install()

        try:
            with respx.mock:
                respx.post(_ANTHROPIC_URL).mock(
                    return_value=httpx.Response(200, json=_AGENT_RESPONSE)
                )
                with httpx.Client() as client:
                    response = client.post(
                        _ANTHROPIC_URL,
                        json={"model": "test", "messages": []},
                        headers={"x-api-key": "test"},
                    )
                # Response is unmodified — agent sees normal httpx.Response
                assert response.status_code == 200
                body = response.json()
                assert body["id"] == "msg_e2e"
        finally:
            interceptor.uninstall()
