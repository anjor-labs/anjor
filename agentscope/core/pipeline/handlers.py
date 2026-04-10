"""EventHandler protocol and built-in handler implementations."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from agentscope.core.events.base import BaseEvent

logger = structlog.get_logger(__name__)


# DECISION: Protocol (structural subtyping) instead of ABC so any object with a
# handle() method and name property satisfies the contract — no forced inheritance.
@runtime_checkable
class EventHandler(Protocol):
    """Protocol for all event handlers.

    Handlers are fire-and-forget: exceptions are caught by the pipeline.
    """

    async def handle(self, event: BaseEvent) -> None: ...

    @property
    def name(self) -> str: ...


class NoOpHandler:
    """Discards all events. Useful as a placeholder or in tests."""

    name: str = "noop"

    async def handle(self, event: BaseEvent) -> None:
        pass


class LogHandler:
    """Logs every event at DEBUG level using structlog."""

    name: str = "log"

    async def handle(self, event: BaseEvent) -> None:
        logger.debug(
            "event",
            event_type=event.event_type,
            trace_id=event.trace_id,
            agent_id=event.agent_id,
            sequence_no=event.sequence_no,
        )


class CollectorHandler:
    """POSTs events to the collector REST API over HTTP.

    Uses httpx.AsyncClient. If the collector is unreachable, logs and swallows
    the error — the agent's execution must never be impacted.
    """

    name: str = "collector"

    def __init__(self, collector_url: str) -> None:
        self._url = collector_url.rstrip("/") + "/events"

    async def handle(self, event: BaseEvent) -> None:
        # DECISION: lazy import httpx here so the handler module has no hard dep on httpx
        # at import time — tests that don't need network can avoid importing it.
        import httpx

        payload = event.model_dump(mode="json")
        try:
            # DECISION: short 2s timeout so a slow collector never blocks the handler for long;
            # exceptions are caught below and logged, not raised.
            async with httpx.AsyncClient() as client:
                response = await client.post(self._url, json=payload, timeout=2.0)
                response.raise_for_status()
        except Exception as exc:
            logger.warning(
                "collector_handler_failed",
                url=self._url,
                error=str(exc),
                event_type=event.event_type,
            )
