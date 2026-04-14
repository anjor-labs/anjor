"""PatchInterceptor — monkey-patches httpx to capture API traffic."""

from __future__ import annotations

import hashlib
import threading
import time
from collections.abc import Callable
from typing import Any

import httpx
import structlog

from anjor.core.pipeline.pipeline import EventPipeline
from anjor.interceptors.base import BaseInterceptor
from anjor.interceptors.parsers.registry import ParserRegistry, build_default_registry
from anjor.interceptors.traceparent import (
    HEADER as TRACEPARENT_HEADER,
)
from anjor.interceptors.traceparent import (
    make_traceparent,
    new_span_id,
    new_trace_id,
)

logger = structlog.get_logger(__name__)

# DECISION: module-level threading.Lock (not asyncio.Lock) because install/uninstall
# can be called from any thread (e.g. test teardown on a different thread than setup).
_lock = threading.Lock()


def _body_to_dict(content: bytes) -> dict[str, Any]:
    """Safely decode bytes → JSON dict. Returns {} on failure."""
    import json

    try:
        return json.loads(content) if content else {}
    except Exception:
        return {}


def _infer_agent_id(request_body: dict[str, Any]) -> str:
    """Infer a stable agent identifier from the request body.

    Uses the system prompt as a fingerprint — different agents typically have
    different system prompts, so this gives each agent a consistent identity
    without any user instrumentation.

    Returns a short readable prefix + hash, e.g. "You are a web_a1b2c3d4".
    Falls back to the model name if no system prompt is present.
    """
    system = request_body.get("system", "")
    if not system:
        return ""
    # Normalise to string (Anthropic also accepts a list of content blocks)
    if isinstance(system, list):
        system = " ".join(block.get("text", "") for block in system if isinstance(block, dict))
    system = system.strip()
    if not system:
        return ""
    digest = hashlib.sha1(system.encode(), usedforsecurity=False).hexdigest()[:8]
    # Take first few words as a readable prefix (max 24 chars)
    prefix = system[:24].rstrip().replace("\n", " ")
    return f"{prefix}_{digest}"


class PatchInterceptor(BaseInterceptor):
    """Monkey-patches httpx.Client.send and httpx.AsyncClient.send.

    Captures every HTTP request/response, routes through ParserRegistry,
    and puts resulting events onto the EventPipeline.

    Thread-safe. Idempotent install/uninstall.
    """

    def __init__(
        self,
        pipeline: EventPipeline | None = None,
        parser_registry: ParserRegistry | None = None,
        default_trace_id: str = "",
    ) -> None:
        self._pipeline = pipeline or EventPipeline()
        self._registry = parser_registry or build_default_registry()
        self._default_trace_id = default_trace_id
        self._installed = False
        self._original_sync_send: Callable[..., Any] | None = None
        self._original_async_send: Callable[..., Any] | None = None

    @property
    def is_installed(self) -> bool:
        return self._installed

    def install(self) -> None:
        """Monkey-patch httpx. Idempotent."""
        with _lock:
            if self._installed:
                return
            self._original_sync_send = httpx.Client.send
            self._original_async_send = httpx.AsyncClient.send
            httpx.Client.send = self._make_sync_wrapper()  # type: ignore[method-assign]
            httpx.AsyncClient.send = self._make_async_wrapper()  # type: ignore[method-assign]
            self._installed = True
            logger.info("patch_interceptor_installed")

    def uninstall(self) -> None:
        """Restore original httpx methods. Idempotent."""
        with _lock:
            if not self._installed:
                return
            if self._original_sync_send is not None:
                httpx.Client.send = self._original_sync_send  # type: ignore[method-assign]
            if self._original_async_send is not None:
                httpx.AsyncClient.send = self._original_async_send  # type: ignore[method-assign]
            self._installed = False
            logger.info("patch_interceptor_uninstalled")

    def _inject_traceparent(self, request: httpx.Request) -> None:
        """Inject a W3C traceparent header if one is not already present.

        Preserves an existing traceparent (propagated from a parent agent)
        so the full DAG trace_id is maintained end-to-end. When absent,
        starts a new root trace.
        """
        if TRACEPARENT_HEADER in request.headers:
            return
        request.headers[TRACEPARENT_HEADER] = make_traceparent(new_trace_id(), new_span_id())

    def _make_sync_wrapper(self) -> Callable[..., Any]:
        interceptor = self
        original = httpx.Client.send

        def wrapped_send(
            client: httpx.Client, request: httpx.Request, **kwargs: Any
        ) -> httpx.Response:
            interceptor._inject_traceparent(request)
            start = time.monotonic()
            response = original(client, request, **kwargs)
            latency_ms = (time.monotonic() - start) * 1000
            interceptor._process(request, response, latency_ms)
            return response

        return wrapped_send

    def _make_async_wrapper(self) -> Callable[..., Any]:
        interceptor = self
        original = httpx.AsyncClient.send

        async def wrapped_async_send(
            client: httpx.AsyncClient, request: httpx.Request, **kwargs: Any
        ) -> httpx.Response:
            interceptor._inject_traceparent(request)
            start = time.monotonic()
            response = await original(client, request, **kwargs)
            latency_ms = (time.monotonic() - start) * 1000
            interceptor._process(request, response, latency_ms)
            return response

        return wrapped_async_send

    def _process(
        self,
        request: httpx.Request,
        response: httpx.Response,
        latency_ms: float,
    ) -> None:
        """Extract events from the request/response and enqueue them."""
        try:
            url = str(request.url)
            request_body = _body_to_dict(request.content)
            response_body = _body_to_dict(response.content)
            events = self._registry.parse(
                url=url,
                request_body=request_body,
                response_body=response_body,
                latency_ms=latency_ms,
                status_code=response.status_code,
            )

            # Resolve trace_id and agent_id using a three-level priority:
            #   1. anjor.span() context vars  — explicit user annotation (highest)
            #   2. Inferred from request body — auto-detected, zero user changes
            #   3. Parser-assigned default    — whatever the parser set (lowest)
            from anjor.context import get_agent_id, get_trace_id

            ctx_trace = get_trace_id()
            ctx_agent = get_agent_id()

            effective_trace = ctx_trace or self._default_trace_id
            effective_agent = ctx_agent or _infer_agent_id(request_body)

            overrides: dict[str, str] = {}
            if effective_trace:
                overrides["trace_id"] = effective_trace
            if effective_agent:
                overrides["agent_id"] = effective_agent
            if overrides:
                events = [e.model_copy(update=overrides) for e in events]

            for event in events:
                self._pipeline.put(event)
        except Exception as exc:
            # DECISION: swallow all exceptions here — the interceptor sits on the agent's
            # critical path; any unhandled error would crash the agent's HTTP call.
            logger.warning(
                "patch_interceptor_process_error",
                error=str(exc),
                url=str(request.url),
            )


class ProxyInterceptor(BaseInterceptor):
    """ProxyInterceptor — mitmproxy sidecar stub (Phase 1 optional extra)."""

    @property
    def is_installed(self) -> bool:
        return False

    def install(self) -> None:
        # Phase 1 stub — mitmproxy integration is an optional extra
        raise NotImplementedError("ProxyInterceptor requires the [proxy] extra.")

    def uninstall(self) -> None:
        pass
