"""One-way OTLP/HTTP JSON export adapter.

Converts Anjor events to OTLP spans and ships them to any OTel-compatible
endpoint (Jaeger, Grafana Tempo, Datadog Agent, etc.) using HTTP/JSON.
No new dependencies — uses httpx, which is already a core dependency.

Only ToolCallEvent and LLMCallEvent are exported; other types are skipped.
Export failures are logged and swallowed — observability must never block ingestion.
"""

from __future__ import annotations

import hashlib
import uuid
from typing import TYPE_CHECKING, Any

import httpx
import structlog

if TYPE_CHECKING:
    from anjor.core.events.base import BaseEvent

from anjor.core.events.llm_call import LLMCallEvent
from anjor.core.events.tool_call import ToolCallEvent

logger = structlog.get_logger(__name__)

_NANOS_PER_MS = 1_000_000
_NANOS_PER_S = 1_000_000_000


def _unix_nano(dt: Any) -> str:
    return str(int(dt.timestamp() * _NANOS_PER_S))


def _trace_id_hex(trace_id: str) -> str:
    """32-char hex OTLP trace ID from an Anjor trace_id (UUID or arbitrary string)."""
    try:
        return uuid.UUID(trace_id).hex
    except ValueError:
        return hashlib.md5(trace_id.encode(), usedforsecurity=False).hexdigest()


def _new_span_id() -> str:
    return uuid.uuid4().hex[:16]


def _s(key: str, val: str) -> dict[str, Any]:
    return {"key": key, "value": {"stringValue": val}}


def _i(key: str, val: int) -> dict[str, Any]:
    return {"key": key, "value": {"intValue": str(val)}}


def _f(key: str, val: float) -> dict[str, Any]:
    return {"key": key, "value": {"doubleValue": val}}


def _tool_span(event: ToolCallEvent) -> dict[str, Any]:
    start_ns = _unix_nano(event.timestamp)
    end_ns = str(int(start_ns) + int(event.latency_ms * _NANOS_PER_MS))
    attrs: list[dict[str, Any]] = [
        _s("anjor.tool_name", event.tool_name),
        _s("anjor.status", event.status),
        _s("anjor.session_id", event.session_id),
        _f("anjor.latency_ms", event.latency_ms),
    ]
    if event.failure_type:
        attrs.append(_s("anjor.failure_type", event.failure_type))
    if event.source:
        attrs.append(_s("anjor.source", event.source))
    if event.project:
        attrs.append(_s("anjor.project", event.project))
    return {
        "traceId": _trace_id_hex(event.trace_id),
        "spanId": _new_span_id(),
        "name": f"tool/{event.tool_name}",
        "kind": 1,
        "startTimeUnixNano": start_ns,
        "endTimeUnixNano": end_ns,
        "attributes": attrs,
        "status": {"code": 2 if event.status != "success" else 1},
    }


def _llm_span(event: LLMCallEvent) -> dict[str, Any]:
    start_ns = _unix_nano(event.timestamp)
    end_ns = str(int(start_ns) + int(event.latency_ms * _NANOS_PER_MS))
    attrs: list[dict[str, Any]] = [
        _s("gen_ai.system", "anthropic"),
        _s("gen_ai.request.model", event.model),
        _s("anjor.session_id", event.session_id),
        _f("anjor.latency_ms", event.latency_ms),
    ]
    if event.token_usage is not None:
        attrs += [
            _i("gen_ai.usage.input_tokens", event.token_usage.input),
            _i("gen_ai.usage.output_tokens", event.token_usage.output),
        ]
    if event.context_utilisation:
        attrs.append(_f("anjor.context_utilisation", event.context_utilisation))
    if event.source:
        attrs.append(_s("anjor.source", event.source))
    if event.project:
        attrs.append(_s("anjor.project", event.project))
    return {
        "traceId": _trace_id_hex(event.trace_id),
        "spanId": _new_span_id(),
        "name": f"llm/{event.model}",
        "kind": 1,
        "startTimeUnixNano": start_ns,
        "endTimeUnixNano": end_ns,
        "attributes": attrs,
        "status": {"code": 1},
    }


_RESOURCE = {"attributes": [_s("service.name", "anjor")]}
_SCOPE = {"name": "anjor"}


class OtlpExportHandler:
    """Pipeline handler that exports events as OTLP spans over HTTP/JSON."""

    name: str = "otlp_export"

    def __init__(self, endpoint: str, headers: dict[str, str]) -> None:
        self._url = endpoint.rstrip("/") + "/v1/traces"
        self._client = httpx.AsyncClient(
            headers={"Content-Type": "application/json", **headers},
            timeout=5.0,
        )

    async def handle(self, event: BaseEvent) -> None:
        if isinstance(event, ToolCallEvent):
            span = _tool_span(event)
        elif isinstance(event, LLMCallEvent):
            span = _llm_span(event)
        else:
            return

        payload = {
            "resourceSpans": [
                {
                    "resource": _RESOURCE,
                    "scopeSpans": [{"scope": _SCOPE, "spans": [span]}],
                }
            ]
        }
        try:
            resp = await self._client.post(self._url, json=payload)
            resp.raise_for_status()
        except Exception as exc:  # noqa: BLE001
            logger.warning("otlp_export_failed", url=self._url, error=str(exc))

    async def shutdown(self) -> None:
        await self._client.aclose()
