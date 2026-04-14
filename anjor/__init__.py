"""Anjor — observability and reliability for agentic AI systems.

Public API:
    patch()                — install the in-process httpx interceptor
    span()                 — context manager: stamp events with trace/agent context,
                             auto-emit AgentSpanEvent on exit
    configure()            — set config programmatically
    get_pipeline()         — access the global event pipeline
    ContextWindowTracker   — track context usage across turns per trace
    ContextHogDetector     — identify tools with oversized outputs
    PromptDriftDetector    — detect system prompt changes per agent
    FailureClusterer       — cluster historical failures into patterns
    TokenOptimizer         — identify context-bloating tools
    CostEstimator          — estimate cost savings for optimizations
    QualityScorer          — per-tool and per-run quality scores
"""

from __future__ import annotations

import asyncio
import subprocess
import sys
import threading
import time
import urllib.request

from anjor.analysis.context.hog_detector import ContextHogDetector
from anjor.analysis.context.tracker import ContextWindowTracker
from anjor.analysis.intelligence.failure_clustering import FailureClusterer
from anjor.analysis.intelligence.quality_scorer import QualityScorer
from anjor.analysis.intelligence.token_optimizer import CostEstimator, TokenOptimizer
from anjor.analysis.prompt.detector import PromptDriftDetector
from anjor.context import span
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.pipeline import EventPipeline
from anjor.interceptors.parsers.registry import build_default_registry
from anjor.interceptors.patch import PatchInterceptor
from anjor.interceptors.requests_patch import RequestsInterceptor as _RequestsInterceptor

__version__ = "0.5.1"
__all__ = [
    "patch",
    "span",
    "configure",
    "get_pipeline",
    "ContextWindowTracker",
    "ContextHogDetector",
    "PromptDriftDetector",
    "FailureClusterer",
    "TokenOptimizer",
    "CostEstimator",
    "QualityScorer",
    "__version__",
]

# Module-level singletons — lazily initialised
_config: AnjorConfig | None = None
_pipeline: EventPipeline | None = None
_interceptor: PatchInterceptor | None = None
_bg_loop: asyncio.AbstractEventLoop | None = None
_bg_thread: threading.Thread | None = None
_session_trace_id: str | None = None  # auto-generated at patch() time

_requests_interceptor: _RequestsInterceptor | None = None


def _ensure_background_loop() -> asyncio.AbstractEventLoop:
    """Return (creating if needed) a background event loop running in a daemon thread.

    The loop is used to run the pipeline worker so it processes events without
    blocking the agent's own thread — which may have no event loop at all.
    """
    global _bg_loop, _bg_thread
    if _bg_loop is not None and _bg_loop.is_running():
        return _bg_loop
    loop = asyncio.new_event_loop()
    t = threading.Thread(target=loop.run_forever, daemon=True, name="anjor-pipeline")
    t.start()
    _bg_loop = loop
    _bg_thread = t
    return loop


def _collector_running(host: str, port: int) -> bool:
    """Return True if the collector responds with HTTP 200 at /health.

    Retries up to 3 times with 200 ms between attempts to tolerate slow startup.
    Uses urllib (stdlib) intentionally — avoids routing through the patched httpx
    client and keeps this function dependency-free.
    """
    url = f"http://{host}:{port}/health"
    for _ in range(3):
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:  # noqa: S310
                if resp.status == 200:
                    return True
        except Exception:  # noqa: S110, BLE001
            pass
        time.sleep(0.2)
    return False


def _start_collector_subprocess(host: str, port: int) -> None:
    """Spawn the collector as a background sidecar process.

    Uses start_new_session=True so the child is detached from the parent's
    process group and outlives the parent on exit (sidecar pattern).
    """
    subprocess.Popen(  # noqa: S603
        [sys.executable, "-m", "anjor.cli", "start", "--host", host, "--port", str(port)],
        start_new_session=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    display_host = "localhost" if host == "127.0.0.1" else host
    print(f"anjor: collector started on http://{display_host}:{port}/ui/", file=sys.stderr)


def configure(config: AnjorConfig | None = None, **kwargs: object) -> AnjorConfig:
    """Set global Anjor configuration.

    Args:
        config: An AnjorConfig instance. If None, built from kwargs.
        **kwargs: Passed to AnjorConfig if config is None.

    Returns:
        The active configuration.
    """
    global _config
    if config is not None:
        _config = config
    elif kwargs:
        _config = AnjorConfig(**kwargs)  # type: ignore[arg-type]
    else:
        _config = AnjorConfig()
    return _config


def get_pipeline() -> EventPipeline:
    """Return the global event pipeline (creating it if needed)."""
    global _pipeline
    if _pipeline is None:
        _pipeline = EventPipeline()
    return _pipeline


def patch(
    config: AnjorConfig | None = None,
    pipeline: EventPipeline | None = None,
    auto_start: bool = True,
) -> PatchInterceptor:
    """Install the in-process httpx interceptor.

    One-line install: import anjor; anjor.patch()

    Args:
        config: Optional config override.
        pipeline: Optional pipeline override. Defaults to get_pipeline().
        auto_start: If True (default), automatically start the collector as a
            background subprocess when it is not already running.  Set to False
            to disable this behaviour and manage the collector manually.

    Returns:
        The installed PatchInterceptor (idempotent — safe to call multiple times).
    """
    global _interceptor, _config, _session_trace_id, _requests_interceptor

    if config is not None:
        _config = config
    if _config is None:
        _config = AnjorConfig()

    if auto_start and _interceptor is None:
        if not _collector_running(_config.host, _config.collector_port):
            _start_collector_subprocess(_config.host, _config.collector_port)

    resolved_pipeline = pipeline or get_pipeline()

    if _interceptor is None:
        from anjor.core.pipeline.handlers import CollectorHandler
        from anjor.interceptors.traceparent import new_trace_id

        # Wire the CollectorHandler so events are forwarded to the collector REST API.
        collector_url = f"http://{_config.host}:{_config.collector_port}"
        resolved_pipeline.add_handler(CollectorHandler(collector_url))

        # The pipeline worker is async; start it inside a long-lived background event loop
        # so the agent's synchronous call stack is never blocked.
        loop = _ensure_background_loop()
        asyncio.run_coroutine_threadsafe(resolved_pipeline.start(), loop).result(timeout=5)

        # Generate a session-level trace_id so all calls in this process are grouped
        # under one trace automatically — no anjor.span() required.
        _session_trace_id = new_trace_id()

        _interceptor = PatchInterceptor(
            pipeline=resolved_pipeline,
            parser_registry=build_default_registry(),
            default_trace_id=_session_trace_id,
        )

    if not _interceptor.is_installed:
        _interceptor.install()

    # Also intercept the requests library if it is installed.  Both interceptors
    # share the same pipeline so all events flow to the same collector.
    if _requests_interceptor is None:
        _requests_interceptor = _RequestsInterceptor(
            pipeline=resolved_pipeline,
            parser_registry=build_default_registry(),
            default_trace_id=_session_trace_id or "",
        )
    if not _requests_interceptor.is_installed:
        _requests_interceptor.install()  # silent no-op when requests is absent

    return _interceptor
