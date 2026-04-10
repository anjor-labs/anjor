"""Unit tests for EventPipeline and handlers."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import pytest

from agentscope.core.events.base import BaseEvent, EventType
from agentscope.core.pipeline.handlers import CollectorHandler, EventHandler, LogHandler, NoOpHandler
from agentscope.core.pipeline.pipeline import EventPipeline

if TYPE_CHECKING:
    pass


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_event(**kwargs: object) -> BaseEvent:
    return BaseEvent(event_type=EventType.TOOL_CALL, **kwargs)  # type: ignore[arg-type]


class CapturingHandler:
    """Records all handled events for test assertions."""

    name: str = "capturing"

    def __init__(self) -> None:
        self.handled: list[BaseEvent] = []

    async def handle(self, event: BaseEvent) -> None:
        self.handled.append(event)


class BrokenHandler:
    """Always raises — used to verify isolation."""

    name: str = "broken"

    async def handle(self, event: BaseEvent) -> None:
        raise RuntimeError("handler exploded")


# ---------------------------------------------------------------------------
# Handler tests
# ---------------------------------------------------------------------------


class TestNoOpHandler:
    def test_is_event_handler_protocol(self) -> None:
        assert isinstance(NoOpHandler(), EventHandler)

    async def test_handle_does_nothing(self) -> None:
        handler = NoOpHandler()
        event = make_event()
        await handler.handle(event)  # must not raise


class TestLogHandler:
    def test_is_event_handler_protocol(self) -> None:
        assert isinstance(LogHandler(), EventHandler)

    async def test_handle_does_not_raise(self) -> None:
        handler = LogHandler()
        event = make_event()
        await handler.handle(event)  # must not raise


class TestCollectorHandler:
    def test_is_event_handler_protocol(self) -> None:
        assert isinstance(CollectorHandler("http://localhost:7843"), EventHandler)

    async def test_handle_logs_on_connection_error(self) -> None:
        handler = CollectorHandler("http://localhost:19999")  # nothing listening
        event = make_event()
        # Must not raise even when collector is unreachable
        await handler.handle(event)


# ---------------------------------------------------------------------------
# EventPipeline tests
# ---------------------------------------------------------------------------


class TestEventPipeline:
    async def test_put_returns_true_when_enqueued(self) -> None:
        pipeline = EventPipeline()
        event = make_event()
        result = pipeline.put(event)
        assert result is True
        assert pipeline.stats.enqueued == 1

    async def test_put_returns_false_when_full(self) -> None:
        pipeline = EventPipeline(max_queue_size=1)
        e1 = make_event()
        e2 = make_event()
        pipeline.put(e1)
        result = pipeline.put(e2)
        assert result is False
        assert pipeline.stats.dropped == 1

    async def test_put_never_raises(self) -> None:
        pipeline = EventPipeline(max_queue_size=1)
        for _ in range(100):
            pipeline.put(make_event())  # no exception

    async def test_dispatch_calls_all_handlers(self) -> None:
        h1 = CapturingHandler()
        h2 = CapturingHandler()
        pipeline = EventPipeline(handlers=[h1, h2])
        event = make_event()
        await pipeline._dispatch(event)
        assert len(h1.handled) == 1
        assert len(h2.handled) == 1

    async def test_broken_handler_does_not_affect_others(self) -> None:
        good = CapturingHandler()
        broken = BrokenHandler()
        pipeline = EventPipeline(handlers=[broken, good])
        event = make_event()
        await pipeline._dispatch(event)
        # Good handler still ran despite broken one
        assert len(good.handled) == 1
        assert pipeline.stats.handler_errors == 1

    async def test_handler_errors_are_counted(self) -> None:
        pipeline = EventPipeline(handlers=[BrokenHandler(), BrokenHandler()])
        await pipeline._dispatch(make_event())
        assert pipeline.stats.handler_errors == 2

    async def test_start_stop_lifecycle(self) -> None:
        pipeline = EventPipeline()
        await pipeline.start()
        assert pipeline._running is True
        await pipeline.stop()
        assert pipeline._running is False

    async def test_events_dispatched_after_start(self) -> None:
        handler = CapturingHandler()
        async with EventPipeline(handlers=[handler]) as pipeline:
            pipeline.put(make_event())
            await asyncio.sleep(0.05)  # let worker tick
        assert len(handler.handled) == 1

    async def test_queue_drained_on_stop(self) -> None:
        handler = CapturingHandler()
        pipeline = EventPipeline(handlers=[handler])
        await pipeline.start()
        for _ in range(5):
            pipeline.put(make_event())
        await pipeline.stop()
        assert len(handler.handled) == 5

    async def test_context_manager(self) -> None:
        handler = CapturingHandler()
        async with EventPipeline(handlers=[handler]) as pipeline:
            pipeline.put(make_event())
            await asyncio.sleep(0.05)
        assert len(handler.handled) == 1

    async def test_add_handler(self) -> None:
        pipeline = EventPipeline()
        handler = CapturingHandler()
        pipeline.add_handler(handler)
        await pipeline._dispatch(make_event())
        assert len(handler.handled) == 1

    async def test_stats_dispatched_increments(self) -> None:
        pipeline = EventPipeline(handlers=[NoOpHandler()])
        await pipeline._dispatch(make_event())
        assert pipeline.stats.dispatched == 1

    async def test_no_handlers_dispatch_is_noop(self) -> None:
        pipeline = EventPipeline(handlers=[])
        # Should not raise
        await pipeline._dispatch(make_event())
        assert pipeline.stats.dispatched == 0
