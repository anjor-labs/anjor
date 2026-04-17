"""MessageEvent — captures a single conversation turn (user or assistant text)."""

from __future__ import annotations

from typing import Literal

from pydantic import Field

from anjor.core.events.base import BaseEvent, EventType

MessageRole = Literal["user", "assistant"]


class MessageEvent(BaseEvent):
    """A single conversation turn captured from a transcript.

    Only emitted when capture_messages=True in AnjorConfig.
    content_preview is capped at 500 chars — full content is never stored.
    """

    event_type: EventType = EventType.MESSAGE

    role: MessageRole
    content_preview: str = Field(default="", max_length=500)
    turn_index: int = Field(default=0, ge=0)
    token_count: int | None = None
