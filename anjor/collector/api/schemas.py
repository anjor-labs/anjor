"""Pydantic response models for the Collector REST API.

These are separate from domain models — API schema can evolve independently.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    uptime_seconds: float
    queue_depth: int
    db_path: str


class ToolListItem(BaseModel):
    tool_name: str
    call_count: int
    success_rate: float
    avg_latency_ms: float


class ToolDetailResponse(BaseModel):
    tool_name: str
    call_count: int
    success_count: int
    failure_count: int
    success_rate: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float


class EventIngestResponse(BaseModel):
    accepted: bool = True
    message: str = "Event accepted"


class LLMSummaryItem(BaseModel):
    """Aggregate stats for a single model."""

    model: str
    call_count: int
    avg_latency_ms: float
    avg_token_input: float
    avg_token_output: float
    avg_context_utilisation: float


class LLMDetailItem(BaseModel):
    """A single LLM call row as returned by GET /llm/trace/{trace_id}."""

    trace_id: str = ""
    session_id: str = ""
    agent_id: str = "default"
    model: str = ""
    latency_ms: float = 0.0
    token_input: int | None = None
    token_output: int | None = None
    token_cache_read: int | None = None
    context_window_used: int | None = None
    context_window_limit: int | None = None
    context_utilisation: float | None = None
    prompt_hash: str | None = None
    system_prompt_hash: str | None = None
    messages_count: int | None = None
    finish_reason: str | None = None
    timestamp: str = ""


class FailureClusterItem(BaseModel):
    """A single failure pattern cluster returned by GET /intelligence/failures."""

    tool_name: str
    failure_type: str
    occurrence_count: int
    total_calls: int
    failure_rate: float
    avg_latency_ms: float
    pattern_description: str
    suggestion: str
    example_trace_ids: list[str] = Field(default_factory=list)


class OptimizationSuggestionItem(BaseModel):
    """A token optimization suggestion returned by GET /intelligence/optimization."""

    tool_name: str
    avg_output_tokens: float
    avg_context_fraction: float
    waste_score: float
    estimated_savings_tokens_per_call: float
    estimated_savings_usd_per_1k_calls: float
    suggestion_text: str
    sample_models: list[str] = Field(default_factory=list)


class ToolQualityScoreItem(BaseModel):
    """Per-tool quality score returned by GET /intelligence/quality/tools."""

    tool_name: str
    call_count: int
    reliability_score: float
    schema_stability_score: float
    latency_consistency_score: float
    overall_score: float
    grade: str


class AgentRunQualityScoreItem(BaseModel):
    """Per-run quality score returned by GET /intelligence/quality/runs."""

    trace_id: str
    llm_call_count: int
    tool_call_count: int
    context_efficiency_score: float
    failure_recovery_score: float
    tool_diversity_score: float
    overall_score: float
    grade: str


class EventIngestRequest(BaseModel):
    """Incoming event payload. Validated before storage.

    extra="allow" so Phase 2 LLM-specific fields (model, context_window_used, etc.)
    pass through without being listed here — avoids a separate schema per event type.
    """

    # DECISION: extra="allow" instead of a separate LLMIngestRequest — the routing
    # to the right table happens in SQLiteBackend.write_event() based on event_type.
    model_config = {"extra": "allow"}

    event_type: str
    tool_name: str = ""
    trace_id: str = ""
    session_id: str = ""
    agent_id: str = "default"
    timestamp: str = ""
    sequence_no: int = Field(default=0, ge=0)
    status: str = ""
    failure_type: str | None = None
    latency_ms: float = Field(default=0.0, ge=0)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)
    input_schema_hash: str = ""
    output_schema_hash: str = ""
    token_usage: dict[str, Any] | None = None
    schema_drift: dict[str, Any] | None = None
