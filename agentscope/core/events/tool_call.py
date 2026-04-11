"""ToolCallEvent — Phase 1 primary event for tool call observability."""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, model_validator

from agentscope.core.events.base import BaseEvent, EventType


class ToolCallStatus(StrEnum):
    SUCCESS = "success"
    FAILURE = "failure"


class FailureType(StrEnum):
    TIMEOUT = "timeout"
    SCHEMA_DRIFT = "schema_drift"
    API_ERROR = "api_error"
    UNKNOWN = "unknown"


class TokenUsage(BaseModel):
    """Token counts for a single tool call."""

    model_config = {"frozen": True}

    input: int = Field(ge=0)
    output: int = Field(ge=0)


class SchemaDrift(BaseModel):
    """Schema drift detected between current and reference payload."""

    model_config = {"frozen": True}

    detected: bool
    missing_fields: list[str] = Field(default_factory=list)
    unexpected_fields: list[str] = Field(default_factory=list)
    expected_hash: str


class ToolCallEvent(BaseEvent):
    """Records a single tool call with full observability metadata."""

    event_type: EventType = EventType.TOOL_CALL

    tool_name: str
    status: ToolCallStatus
    failure_type: FailureType | None = None
    latency_ms: float = Field(ge=0)

    # Payloads are sanitised before storage (no secrets)
    input_payload: dict[str, Any] = Field(default_factory=dict)
    output_payload: dict[str, Any] = Field(default_factory=dict)

    input_schema_hash: str = ""
    output_schema_hash: str = ""

    token_usage: TokenUsage | None = None
    schema_drift: SchemaDrift | None = None

    # DECISION: model_validator mode="after" so we see the fully-constructed object
    # and can enforce cross-field contracts that field-level validators can't express.
    @model_validator(mode="after")
    def validate_failure_type_consistency(self) -> ToolCallEvent:
        """Enforce failure_type ↔ status contract.

        - success + failure_type set → ValidationError
        - failure + failure_type None → coerce to UNKNOWN
        """
        if self.status == ToolCallStatus.SUCCESS and self.failure_type is not None:
            raise ValueError(
                f"failure_type must be None when status is success, got {self.failure_type!r}"
            )
        if self.status == ToolCallStatus.FAILURE and self.failure_type is None:
            # DECISION: object.__setattr__ because frozen=True blocks normal attribute setting,
            # but we still need to coerce inside the validator before the object is returned.
            object.__setattr__(self, "failure_type", FailureType.UNKNOWN)
        return self
