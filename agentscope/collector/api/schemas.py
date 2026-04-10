"""Pydantic response models for the Collector REST API.

These are separate from domain models — API schema can evolve independently.
"""

from __future__ import annotations

from datetime import datetime

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


class EventIngestRequest(BaseModel):
    """Incoming event payload. Validated before storage."""

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
    input_payload: dict = Field(default_factory=dict)
    output_payload: dict = Field(default_factory=dict)
    input_schema_hash: str = ""
    output_schema_hash: str = ""
    token_usage: dict | None = None
    schema_drift: dict | None = None
