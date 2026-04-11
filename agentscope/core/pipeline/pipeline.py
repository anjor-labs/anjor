"""EventPipeline — async queue with concurrent handler dispatch."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog

if TYPE_CHECKING:
    from agentscope.core.events.base import BaseEvent
    from agentscope.core.pipeline.handlers import EventHandler

logger = structlog.get_logger(__name__)


@dataclass
class PipelineStats:
    """Counters for pipeline health monitoring."""

    enqueued: int = 0
    dispatched: int = 0
    dropped: int = 0
    handler_errors: int = 0


class EventPipeline:
    """Async event pipeline with backpressure and concurrent handler dispatch.

    Contract:
    - put() is non-blocking, never raises. Returns True if enqueued, False if dropped.
    - Dropped events increment stats.dropped.
    - _dispatch() runs all handlers concurrently via asyncio.gather(return_exceptions=True).
    - Handler exceptions are logged and swallowed — never propagated to the caller.
    - Graceful shutdown drains the queue before cancelling.
    """

    def __init__(
        self,
        handlers: list[EventHandler] | None = None,
        max_queue_size: int = 1000,
    ) -> None:
        self._handlers: list[EventHandler] = handlers or []
        self._queue: asyncio.Queue[BaseEvent] = asyncio.Queue(maxsize=max_queue_size)
        self._stats = PipelineStats()
        self._worker_task: asyncio.Task[None] | None = None
        self._running = False

    @property
    def stats(self) -> PipelineStats:
        return self._stats

    def add_handler(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def put(self, event: BaseEvent) -> bool:
        """Enqueue an event. Non-blocking. Returns False if queue is full."""
        try:
            # DECISION: put_nowait (non-blocking) so the agent's call stack never stalls
            # waiting for queue space — observability must have zero impact on agent latency.
            self._queue.put_nowait(event)
            self._stats.enqueued += 1
            return True
        except asyncio.QueueFull:
            # DECISION: drop + log instead of blocking or raising — a full queue means the
            # collector is behind; losing events is better than slowing or crashing the agent.
            self._stats.dropped += 1
            logger.warning(
                "event_dropped_queue_full",
                event_type=event.event_type,
                trace_id=event.trace_id,
                queue_size=self._queue.qsize(),
            )
            return False

    async def _dispatch(self, event: BaseEvent) -> None:
        """Dispatch event to all handlers concurrently."""
        if not self._handlers:
            return

        # DECISION: asyncio.gather(return_exceptions=True) so one bad handler never kills
        # the others — each handler is independent; a crash in logging must not stop storage.
        results = await asyncio.gather(
            *[h.handle(event) for h in self._handlers],
            return_exceptions=True,
        )
        for handler, result in zip(self._handlers, results, strict=False):
            if isinstance(result, BaseException):
                self._stats.handler_errors += 1
                logger.error(
                    "handler_exception",
                    handler=getattr(handler, "name", type(handler).__name__),
                    event_type=event.event_type,
                    trace_id=event.trace_id,
                    error=str(result),
                )
        self._stats.dispatched += 1

    async def _worker(self) -> None:
        """Background worker that consumes the queue."""
        while self._running:
            try:
                # DECISION: 0.1s timeout so the worker checks _running frequently enough
                # to respond to stop() without holding up shutdown for long.
                event = await asyncio.wait_for(self._queue.get(), timeout=0.1)
                await self._dispatch(event)
                self._queue.task_done()
            except TimeoutError:
                continue
            except asyncio.CancelledError:
                break

    async def start(self) -> None:
        """Start the background worker."""
        self._running = True
        self._worker_task = asyncio.create_task(self._worker())

    async def stop(self) -> None:
        """Drain the queue then stop the worker."""
        self._running = False
        # Drain remaining events
        while not self._queue.empty():
            try:
                event = self._queue.get_nowait()
                await self._dispatch(event)
                self._queue.task_done()
            except asyncio.QueueEmpty:
                break

        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
            self._worker_task = None

    async def __aenter__(self) -> EventPipeline:
        await self.start()
        return self

    async def __aexit__(self, *_: object) -> None:
        await self.stop()
