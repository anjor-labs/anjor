"""BaseEvent — root Pydantic model for all AgentScope events."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, Field


class EventType(StrEnum):
    TOOL_CALL = "tool_call"
    LLM_CALL = "llm_call"
    MEMORY_READ = "memory_read"
    AGENT_DECISION = "agent_decision"
    WORKFLOW = "workflow"


class BaseEvent(BaseModel):
    """Immutable base for all AgentScope events.

    All subclasses are frozen — events are facts, not mutable state.
    """

    # DECISION: frozen=True so events can never be mutated after creation — observability
    # data must be an accurate record of what happened, not what someone later changed it to.
    model_config = {"frozen": True}

    event_type: EventType
    # DECISION: UUID4 defaults so callers never have to think about IDs — zero-friction install.
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str = "default"
    # DECISION: UTC-aware datetime so timestamps are unambiguous across timezones.
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sequence_no: int = Field(default=0, ge=0)
