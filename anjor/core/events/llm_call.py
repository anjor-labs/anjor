"""LLMCallEvent — Phase 2 LLM call tracing event."""

from __future__ import annotations

from pydantic import BaseModel, Field, model_validator

from anjor.core.events.base import BaseEvent, EventType


class LLMTokenUsage(BaseModel):
    """Token counts for a single LLM call.

    cache_read is optional — only Anthropic models with prompt caching return it.
    """

    model_config = {"frozen": True}

    input: int = Field(ge=0)
    output: int = Field(ge=0)
    # DECISION: cache_read separate from input so cost calculations can distinguish
    # cached vs fresh tokens. Cached tokens are billed at a lower rate.
    cache_read: int = Field(default=0, ge=0)


class LLMCallEvent(BaseEvent):
    """Records a single LLM call with context window and prompt metadata.

    Phase 2 primary event. Emitted for every /v1/messages call regardless
    of whether tool calls are present.
    """

    event_type: EventType = EventType.LLM_CALL

    # Model identifier as returned by the API (e.g. "claude-3-5-sonnet-20241022")
    model: str

    # Token usage — None if the response was an error with no usage block
    token_usage: LLMTokenUsage | None = None

    latency_ms: float = Field(ge=0)

    # Context window state for this call
    context_window_used: int = Field(default=0, ge=0)
    context_window_limit: int = Field(default=0, ge=0)
    # DECISION: derived field computed by validator so callers never have to
    # compute it themselves, and it's always consistent with used/limit.
    context_utilisation: float = Field(default=0.0, ge=0.0, le=1.0)

    # Structural hashes of prompt inputs (values stripped, structure only)
    prompt_hash: str = ""
    system_prompt_hash: str | None = None

    # Request metadata
    messages_count: int = Field(default=0, ge=0)
    finish_reason: str | None = None

    @model_validator(mode="after")
    def compute_utilisation(self) -> LLMCallEvent:
        """Derive context_utilisation from used/limit when limit is known."""
        if self.context_window_limit > 0:
            utilisation = self.context_window_used / self.context_window_limit
            object.__setattr__(self, "context_utilisation", round(min(utilisation, 1.0), 6))
        return self
