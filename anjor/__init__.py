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
        _interceptor = PatchInterceptor(
            pipeline=resolved_pipeline,
            parser_registry=build_default_registry(),
        )

    if not _interceptor.is_installed:
        _interceptor.install()

    return _interceptor
