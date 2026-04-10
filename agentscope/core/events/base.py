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

    model_config = {"frozen": True}

    event_type: EventType
    trace_id: str = Field(default_factory=lambda: str(uuid4()))
    session_id: str = Field(default_factory=lambda: str(uuid4()))
    agent_id: str = "default"
    timestamp: datetime = Field(default_factory=lambda: datetime.now(UTC))
    sequence_no: int = Field(default=0, ge=0)
