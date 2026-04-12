"""Anjor — observability and reliability for agentic AI systems.

Public API:
    patch()                — install the in-process httpx interceptor
    configure()            — set config programmatically
    get_pipeline()         — access the global event pipeline
    ContextWindowTracker   — track context usage across turns per trace
    ContextHogDetector     — identify tools with oversized outputs
    PromptDriftDetector    — detect system prompt changes per agent
    FailureClusterer       — cluster historical failures into patterns (Phase 3)
    TokenOptimizer         — identify context-bloating tools (Phase 3)
    CostEstimator          — estimate cost savings for optimizations (Phase 3)
    QualityScorer          — per-tool and per-run quality scores (Phase 3)
"""

from __future__ import annotations

import asyncio
import threading

from anjor.analysis.context.hog_detector import ContextHogDetector
from anjor.analysis.context.tracker import ContextWindowTracker
from anjor.analysis.intelligence.failure_clustering import FailureClusterer
from anjor.analysis.intelligence.quality_scorer import QualityScorer
from anjor.analysis.intelligence.token_optimizer import CostEstimator, TokenOptimizer
from anjor.analysis.prompt.detector import PromptDriftDetector
from anjor.core.config import AnjorConfig
from anjor.core.pipeline.pipeline import EventPipeline
from anjor.interceptors.parsers.registry import build_default_registry
from anjor.interceptors.patch import PatchInterceptor

__version__ = "0.3.0"
__all__ = [
    "patch",
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
) -> PatchInterceptor:
    """Install the in-process httpx interceptor.

    One-line install: import anjor; anjor.patch()

    Args:
        config: Optional config override.
        pipeline: Optional pipeline override. Defaults to get_pipeline().

    Returns:
        The installed PatchInterceptor (idempotent — safe to call multiple times).
    """
    global _interceptor, _config

    if config is not None:
        _config = config
    if _config is None:
        _config = AnjorConfig()

    resolved_pipeline = pipeline or get_pipeline()

    if _interceptor is None:
        from anjor.core.pipeline.handlers import CollectorHandler

        # Wire the CollectorHandler so events are forwarded to the collector REST API.
        collector_url = f"http://{_config.host}:{_config.collector_port}"
        resolved_pipeline.add_handler(CollectorHandler(collector_url))

        # The pipeline worker is async; start it inside a long-lived background event loop
        # so the agent's synchronous call stack is never blocked.
        loop = _ensure_background_loop()
        asyncio.run_coroutine_threadsafe(resolved_pipeline.start(), loop).result(timeout=5)

        _interceptor = PatchInterceptor(
            pipeline=resolved_pipeline,
            parser_registry=build_default_registry(),
        )

    if not _interceptor.is_installed:
        _interceptor.install()

    return _interceptor
