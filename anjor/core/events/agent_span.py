"""AgentSpanEvent — Phase 4 multi-agent tracing event."""

from __future__ import annotations

import os
from enum import StrEnum

from pydantic import Field

from anjor.core.events.base import BaseEvent, EventType


def _new_span_id() -> str:
    """Generate a 16-byte hex span ID (W3C traceparent compatible)."""
    return os.urandom(16).hex()


class SpanKind(StrEnum):
    """Role of a span within the agent DAG."""

    ROOT = "root"
    ORCHESTRATOR = "orchestrator"
    SUBAGENT = "subagent"
    TOOL = "tool"


class AgentSpanEvent(BaseEvent):
    """Records a single agent span for multi-agent DAG tracing.

    Phase 4 primary event. One span = one agent's activity within a trace.
    Parent/child links form a DAG (not necessarily a tree — one subagent
    can be called by multiple orchestrators in parallel).
    """

    event_type: EventType = EventType.AGENT_SPAN

    # Span identity
    span_id: str = Field(default_factory=_new_span_id)
    # None for root spans; references span_id of the calling agent
    parent_span_id: str | None = None

    # Agent metadata
    span_kind: SpanKind = SpanKind.ROOT
    agent_name: str = "unknown"
    agent_role: str = ""

    # Timing
    started_at: str = ""
    ended_at: str | None = None

    # Outcome
    status: str = Field(default="ok", pattern="^(ok|error)$")
    failure_type: str | None = None

    # Aggregated counters for this span (filled when span closes)
    token_input: int = Field(default=0, ge=0)
    token_output: int = Field(default=0, ge=0)
    tool_calls_count: int = Field(default=0, ge=0)
    llm_calls_count: int = Field(default=0, ge=0)
