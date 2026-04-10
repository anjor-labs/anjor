"""PatchInterceptor — monkey-patches httpx to capture API traffic."""

from __future__ import annotations

import asyncio
import io
import time
import threading
from typing import Any, Callable

import httpx
import structlog

from agentscope.core.pipeline.pipeline import EventPipeline
from agentscope.interceptors.base import BaseInterceptor
from agentscope.interceptors.parsers.registry import ParserRegistry, build_default_registry

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
    ) -> None:
        self._pipeline = pipeline or EventPipeline()
        self._registry = parser_registry or build_default_registry()
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

    def _make_sync_wrapper(self) -> Callable[..., Any]:
        interceptor = self
        original = httpx.Client.send

        def wrapped_send(
            client: httpx.Client, request: httpx.Request, **kwargs: Any
        ) -> httpx.Response:
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
