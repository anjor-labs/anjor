"""Shared pytest fixtures for AgentScope test suite."""

from __future__ import annotations

import pytest

from agentscope.collector.storage.sqlite import SQLiteBackend
from agentscope.core.events.base import BaseEvent, EventType
from agentscope.core.events.tool_call import ToolCallEvent, ToolCallStatus
from agentscope.core.pipeline.pipeline import EventPipeline


@pytest.fixture
def sample_tool_call_event() -> ToolCallEvent:
    """A minimal successful ToolCallEvent for use in tests."""
    return ToolCallEvent(
        tool_name="web_search",
        status=ToolCallStatus.SUCCESS,
        latency_ms=123.0,
        input_payload={"query": "AI news"},
        output_payload={"results": ["result1"]},
        input_schema_hash="input_hash",
        output_schema_hash="output_hash",
    )


@pytest.fixture
def sample_base_event() -> BaseEvent:
    return BaseEvent(event_type=EventType.TOOL_CALL)


@pytest.fixture
async def in_memory_storage() -> SQLiteBackend:  # type: ignore[misc]
    """Connected in-memory SQLiteBackend."""
    storage = SQLiteBackend(db_path=":memory:", batch_size=1, batch_interval_ms=9999)
    await storage.connect()
    yield storage  # type: ignore[misc]
    await storage.close()


@pytest.fixture
def running_pipeline() -> EventPipeline:
    """An EventPipeline instance (not started — use as async context manager)."""
    return EventPipeline()
