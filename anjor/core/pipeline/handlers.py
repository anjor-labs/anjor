"""EventHandler protocol and built-in handler implementations."""

from __future__ import annotations

import asyncio
import re
from collections import deque
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

import structlog

if TYPE_CHECKING:
    from anjor.core.config import AlertConfig
    from anjor.core.events.base import BaseEvent

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


_COND_RE = re.compile(r"""^(\w+)\s*(>|>=|<|<=|==)\s*["']?([^"'\s]+)["']?$""")


def _compare(actual: float, op: str, threshold: float) -> bool:
    if op == ">":
        return actual > threshold
    if op == ">=":
        return actual >= threshold
    if op == "<":
        return actual < threshold
    if op == "<=":
        return actual <= threshold
    return actual == threshold


def _event_cost_usd(event_data: dict[str, Any]) -> float:
    from anjor.analysis.cost import estimate_cost_usd

    model = str(event_data.get("model") or "")
    usage: dict[str, Any] = event_data.get("token_usage") or {}
    return estimate_cost_usd(
        model=model,
        token_input=int(usage.get("input", 0)),
        token_output=int(usage.get("output", 0)),
        cache_read=int(usage.get("cache_read", 0)),
        cache_write=int(usage.get("cache_creation", 0)),
    )


class AlertHandler:
    """Evaluates configured alert conditions on each ingested event dict.

    Maintains per-condition rolling buffers and cost accumulators.
    Fires webhooks in a background task — never blocks the ingestion path.
    """

    name: str = "alert"

    def __init__(self, alerts: list[AlertConfig]) -> None:
        self._alerts = alerts
        self._buffers: dict[str, deque[float]] = {
            a.name: deque(maxlen=a.window_calls) for a in alerts
        }
        self._daily_cost: dict[str, float] = {}
        self._session_cost: dict[str, float] = {}
        self._today: str = ""

    async def handle_dict(self, event_data: dict[str, Any]) -> None:
        if not self._alerts:
            return
        fires = self._evaluate(event_data)
        if fires:
            asyncio.create_task(self._fire_all(fires))

    def _evaluate(self, event_data: dict[str, Any]) -> list[dict[str, Any]]:
        today = datetime.now(tz=UTC).date().isoformat()
        if today != self._today:
            self._today = today
            self._daily_cost = {}

        event_type = str(event_data.get("event_type") or "")
        fires: list[dict[str, Any]] = []

        for alert in self._alerts:
            m = _COND_RE.match(alert.condition.strip())
            if not m:
                logger.warning("alert_bad_condition", name=alert.name, cond=alert.condition)
                continue
            metric, op, raw_val = m.group(1), m.group(2), m.group(3)
            buf = self._buffers[alert.name]
            fire = self._check_condition(alert, metric, op, raw_val, buf, event_type, event_data)
            if fire is not None:
                fires.append(fire)

        return fires

    def _check_condition(
        self,
        alert: AlertConfig,
        metric: str,
        op: str,
        raw_val: str,
        buf: deque[float],
        event_type: str,
        event_data: dict[str, Any],
    ) -> dict[str, Any] | None:
        actual: float = 0.0
        threshold: float = 0.0
        triggered = False

        if metric == "failure_rate" and event_type == "tool_call":
            buf.append(1.0 if event_data.get("status") == "failure" else 0.0)
            if len(buf) >= alert.window_calls:
                actual = sum(buf) / len(buf)
                threshold = float(raw_val)
                triggered = _compare(actual, op, threshold)

        elif metric == "p95_latency" and event_type == "tool_call":
            latency = event_data.get("latency_ms")
            if latency is not None:
                buf.append(float(latency))
            if len(buf) >= 2:
                sorted_l = sorted(buf)
                idx = min(int(len(sorted_l) * 0.95), len(sorted_l) - 1)
                actual = sorted_l[idx]
                threshold = float(raw_val)
                triggered = _compare(actual, op, threshold)

        elif metric == "context_utilisation" and event_type == "llm_call":
            ctx = event_data.get("context_utilisation")
            if ctx is not None:
                actual = float(ctx)
                threshold = float(raw_val)
                triggered = _compare(actual, op, threshold)

        elif metric in ("daily_cost_usd", "session_cost_usd") and event_type == "llm_call":
            cost = _event_cost_usd(event_data)
            if metric == "daily_cost_usd":
                self._daily_cost[alert.name] = self._daily_cost.get(alert.name, 0.0) + cost
                actual = self._daily_cost[alert.name]
            else:
                self._session_cost[alert.name] = self._session_cost.get(alert.name, 0.0) + cost
                actual = self._session_cost[alert.name]
            threshold = float(raw_val)
            triggered = _compare(actual, op, threshold)

        elif metric == "error_type" and event_type == "tool_call":
            if event_data.get("status") == "failure":
                actual_type = str(event_data.get("failure_type") or "")
                if actual_type == raw_val:
                    triggered = True
                    actual = 1.0

        if not triggered:
            return None
        return {
            "name": alert.name,
            "webhook": alert.webhook,
            "metric": metric,
            "value": actual,
            "threshold": threshold,
        }

    async def _fire_all(self, fires: list[dict[str, Any]]) -> None:
        import httpx

        ts = datetime.now(tz=UTC).isoformat()
        for fire in fires:
            name: str = fire["name"]
            metric: str = fire["metric"]
            value: float = fire["value"]
            threshold: float = fire["threshold"]
            webhook: str = fire["webhook"]

            if "hooks.slack.com" in webhook:
                payload: dict[str, Any] = {
                    "text": (
                        f"anjor alert: {name} — "
                        f"{metric}={value:.4g} (threshold {threshold:.4g})"
                    )
                }
            else:
                payload = {
                    "alert": name,
                    "metric": metric,
                    "value": value,
                    "threshold": threshold,
                    "timestamp": ts,
                }

            try:
                async with httpx.AsyncClient() as client:
                    await client.post(webhook, json=payload, timeout=5.0)
            except Exception as exc:
                logger.warning("alert_webhook_failed", name=name, error=str(exc))


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
