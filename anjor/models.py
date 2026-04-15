"""Public Pydantic models for programmatic access to anjor data.

These are the stable, typed return values of :class:`anjor.Client`.
Import them directly::

    from anjor.models import ToolSummary, FailurePattern, ToolQualityScore

All models are frozen (immutable after construction) and fully serialisable
via :meth:`~pydantic.BaseModel.model_dump` and
:meth:`~pydantic.BaseModel.model_dump_json`.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

__all__ = [
    "ToolSummary",
    "ToolCallRecord",
    "FailurePattern",
    "OptimizationSuggestion",
    "ToolQualityScore",
    "RunQualityScore",
]


class ToolSummary(BaseModel):
    """Aggregate statistics for a single tool, computed across all its call history."""

    model_config = {"frozen": True}

    tool_name: str
    call_count: int
    success_count: int
    failure_count: int
    #: Fraction of calls that succeeded (0.0–1.0).
    success_rate: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float


class ToolCallRecord(BaseModel):
    """A single raw tool call event as stored in the database."""

    model_config = {"frozen": True}

    tool_name: str
    #: ``"success"`` or ``"failure"``
    status: str
    failure_type: str | None = None
    latency_ms: float
    trace_id: str
    session_id: str
    agent_id: str
    timestamp: str
    input_schema_hash: str = ""
    output_schema_hash: str = ""
    #: ``True`` if a schema drift event was detected on this call.
    drift_detected: bool | None = None


class FailurePattern(BaseModel):
    """A clustered failure pattern derived from historical tool call data."""

    model_config = {"frozen": True}

    tool_name: str
    failure_type: str
    occurrence_count: int
    total_calls: int
    #: Fraction of calls that failed with this pattern (0.0–1.0).
    failure_rate: float
    avg_latency_ms: float
    pattern_description: str
    suggestion: str
    example_trace_ids: list[str] = Field(default_factory=list)


class OptimizationSuggestion(BaseModel):
    """A token optimisation opportunity for a context-bloating tool."""

    model_config = {"frozen": True}

    tool_name: str
    avg_output_tokens: float
    #: Average fraction of the context window consumed by this tool's output.
    avg_context_fraction: float
    waste_score: float
    estimated_savings_tokens_per_call: float
    estimated_savings_usd_per_1k_calls: float
    suggestion_text: str
    sample_models: list[str] = Field(default_factory=list)


class ToolQualityScore(BaseModel):
    """Quality score for a single tool across reliability, schema stability, and latency."""

    model_config = {"frozen": True}

    tool_name: str
    call_count: int
    reliability_score: float
    schema_stability_score: float
    latency_consistency_score: float
    overall_score: float
    #: Letter grade: ``"A"`` (≥0.9) through ``"F"`` (<0.4).
    grade: str


class RunQualityScore(BaseModel):
    """Quality score for a single agent run (identified by trace_id)."""

    model_config = {"frozen": True}

    trace_id: str
    llm_call_count: int
    tool_call_count: int
    context_efficiency_score: float
    failure_recovery_score: float
    tool_diversity_score: float
    overall_score: float
    #: Letter grade: ``"A"`` (≥0.9) through ``"F"`` (<0.4).
    grade: str
