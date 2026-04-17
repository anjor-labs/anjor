"""RequestsInterceptor — monkey-patches requests.Session.send to capture API traffic.

Design:
- Wraps requests.Session.send at the class level.  Every call goes through the
  wrapper, which measures latency, reads the response body (caching it so user
  code can still read it), detects SSE streams by content-type, and emits events
  through the same ParserRegistry used by PatchInterceptor.
- Gracefully no-ops at install/uninstall time if requests is not installed.
- Thread-safe and idempotent.

SSE note: accessing response.content on a streaming requests.Response consumes
the raw socket data and caches it in response._content.  Subsequent accesses by
user code (.content, .text, .json(), iter_content()) all read from the cache, so
intercepting here is transparent even when stream=True was used.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable
from typing import Any

import structlog

from anjor.core.pipeline.pipeline import EventPipeline
from anjor.interceptors.base import BaseInterceptor
from anjor.interceptors.parsers.registry import ParserRegistry, build_default_registry
from anjor.interceptors.patch import _body_to_dict, _infer_agent_id
from anjor.interceptors.streaming import build_stream_response_body, parse_sse_events

logger = structlog.get_logger(__name__)

_lock = threading.Lock()


class RequestsInterceptor(BaseInterceptor):
    """Monkey-patches requests.Session.send to capture API traffic.

    Captures every HTTP request/response made through the requests library,
    routes through ParserRegistry, and puts resulting events onto the EventPipeline.

    Thread-safe. Idempotent. Silently skips install if requests is not installed.
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
        self._original_session_send: Callable[..., Any] | None = None

    @property
    def is_installed(self) -> bool:
        return self._installed

    def install(self) -> None:
        """Monkey-patch requests.Session.send. Idempotent. No-op if requests is absent."""
        try:
            import requests
        except ImportError:
            logger.debug("requests_not_installed_skipping_interceptor")
            return

        with _lock:
            if self._installed:
                return
            self._original_session_send = requests.Session.send
            requests.Session.send = self._make_wrapper()  # type: ignore
            self._installed = True
            logger.info("requests_interceptor_installed")

    def uninstall(self) -> None:
        """Restore original requests.Session.send. Idempotent."""
        try:
            import requests
        except ImportError:
            return

        with _lock:
            if not self._installed:
                return
            if self._original_session_send is not None:
                requests.Session.send = self._original_session_send  # type: ignore
            self._installed = False
            logger.info("requests_interceptor_uninstalled")

    def _make_wrapper(self) -> Callable[..., Any]:
        """Return a replacement for requests.Session.send that tees through _process."""
        interceptor = self

        def wrapped_send(session: Any, request: Any, **kwargs: Any) -> Any:
            start = time.monotonic()
            # Call the saved original — looked up dynamically so tests can replace it.
            original = interceptor._original_session_send
            response = original(session, request, **kwargs)  # type: ignore[misc]
            latency_ms = (time.monotonic() - start) * 1000
            interceptor._process(request, response, latency_ms)
            return response

        return wrapped_send

    def _emit_events(
        self,
        url: str,
        request_body: dict[str, Any],
        response_body: dict[str, Any],
        latency_ms: float,
        status_code: int,
    ) -> None:
        """Parse events from req/resp dicts, apply context overrides, enqueue all."""
        events = self._registry.parse(
            url=url,
            request_body=request_body,
            response_body=response_body,
            latency_ms=latency_ms,
            status_code=status_code,
        )

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

    def _process(
        self,
        request: Any,  # requests.PreparedRequest
        response: Any,  # requests.Response
        latency_ms: float,
    ) -> None:
        """Extract events from a completed requests request/response.

        Accesses response.content which — even for stream=True responses — reads
        the body once and caches it transparently inside the Response object.
        """
        try:
            url: str = request.url or ""

            # request.body is bytes | str | None
            body = request.body
            if isinstance(body, str):
                body = body.encode()
            request_body = _body_to_dict(body or b"")

            # Force-read the response body.  For non-streaming calls this is
            # already in memory.  For streaming calls this drains the socket and
            # caches the result — subsequent .content / .json() / iter_content()
            # calls by the caller all read from the cache transparently.
            raw_bytes: bytes = response.content or b""
            status_code: int = response.status_code

            content_type: str = response.headers.get("content-type", "")
            if "text/event-stream" in content_type:
                sse_events = parse_sse_events(raw_bytes)
                response_body = build_stream_response_body(url, sse_events)
                if response_body is None:
                    return
            else:
                response_body = _body_to_dict(raw_bytes)

            self._emit_events(url, request_body, response_body, latency_ms, status_code)
        except Exception as exc:
            logger.warning(
                "requests_interceptor_process_error",
                error=str(exc),
                url=str(getattr(request, "url", "")),
            )
