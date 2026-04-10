"""LLMCallEvent — Phase 2 stub. Minimal, importable, not yet implemented."""

from __future__ import annotations

from pydantic import Field

from agentscope.core.events.base import BaseEvent, EventType


class LLMCallEvent(BaseEvent):
    """Stub for Phase 2 LLM call tracing. Do not implement until Phase 2."""

    event_type: EventType = EventType.LLM_CALL

    model: str
    token_usage_input: int = Field(default=0, ge=0)
    token_usage_output: int = Field(default=0, ge=0)
    token_usage_cache_read: int = Field(default=0, ge=0)
    latency_ms: float = Field(default=0.0, ge=0)
    context_window_used: int = Field(default=0, ge=0)
    context_window_limit: int = Field(default=0, ge=0)
