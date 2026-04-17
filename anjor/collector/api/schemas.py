"""Pydantic response models for the Collector REST API.

These are separate from domain models — API schema can evolve independently.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str = "ok"
    anjor_version: str = ""
    uptime_seconds: float
    queue_depth: int
    db_path: str


class ToolListItem(BaseModel):
    tool_name: str
    call_count: int
    failure_count: int = 0
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


class FlushResponse(BaseModel):
    flushed: int


class LLMSummaryItem(BaseModel):
    """Aggregate stats for a single model."""

    model: str
    call_count: int
    avg_latency_ms: float
    avg_token_input: float
    avg_token_output: float
    avg_context_utilisation: float
    total_token_input: int = 0
    total_token_output: int = 0
    total_cache_read: int = 0
    total_cache_write: int = 0
    source: str = ""


class DailyUsageItem(BaseModel):
    """Token usage for a single model on a single day."""

    date: str
    model: str
    tokens_in: int
    tokens_out: int
    cache_read: int
    cache_write: int
    calls: int


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


class SpanNodeItem(BaseModel):
    """A single span node as returned by GET /traces/{trace_id}/graph."""

    span_id: str
    parent_span_id: str | None
    agent_name: str
    span_kind: str
    depth: int
    status: str
    token_input: int
    token_output: int
    tool_calls_count: int
    llm_calls_count: int
    started_at: str
    ended_at: str | None
    duration_ms: float | None


class TraceGraphResponse(BaseModel):
    """Response for GET /traces/{trace_id}/graph."""

    trace_id: str
    node_count: int
    has_cycle: bool
    nodes: list[SpanNodeItem]
    edges: list[tuple[str, str]]


class TraceSummaryItem(BaseModel):
    """One row from GET /traces."""

    trace_id: str
    root_agent_name: str
    span_count: int
    total_token_input: int
    total_token_output: int
    started_at: str
    status: str


class AgentAttributionItem(BaseModel):
    """Per-agent token and failure attribution from GET /intelligence/attribution."""

    agent_name: str
    span_count: int
    token_input: int
    token_output: int
    token_total: int
    token_share_pct: float
    tool_calls_count: int
    llm_calls_count: int
    failure_count: int
    failure_rate: float


class MCPServerItem(BaseModel):
    """Aggregate stats for one MCP server returned by GET /mcp."""

    server_name: str
    tool_count: int
    call_count: int
    success_count: int
    success_rate: float
    avg_latency_ms: float


class MCPToolItem(BaseModel):
    """Aggregate stats for one MCP tool returned by GET /mcp."""

    tool_name: str  # full name, e.g. mcp__github__create_pr
    server_name: str  # e.g. github
    short_name: str  # e.g. create_pr
    call_count: int
    success_count: int
    success_rate: float
    avg_latency_ms: float


class MCPResponse(BaseModel):
    """Response for GET /mcp — server list + tool list."""

    servers: list[MCPServerItem]
    tools: list[MCPToolItem]


class ProjectSummaryItem(BaseModel):
    """Per-project aggregated stats from GET /projects."""

    project: str
    tool_call_count: int
    llm_call_count: int
    total_token_input: int
    total_token_output: int
    first_seen: str
    last_seen: str


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


class SetProjectRequest(BaseModel):
    project: str


class SessionItem(BaseModel):
    session_id: str
    message_count: int
    archived: bool = False
    first_seen: str
    last_seen: str
    project: str = ""
    source: str = ""


class ReplayTurn(BaseModel):
    kind: str  # "user" | "assistant" | "tool"
    timestamp: str
    content_preview: str | None = None
    token_count: int | None = None
    tool_name: str | None = None
    status: str | None = None
    latency_ms: float | None = None
    source: str = ""


class ReplayResponse(BaseModel):
    session_id: str
    turn_count: int
    turns: list[ReplayTurn]
