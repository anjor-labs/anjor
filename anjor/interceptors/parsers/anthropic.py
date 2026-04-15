"""AnthropicParser — extracts ToolCallEvent and LLMCallEvent from Anthropic API responses."""

from __future__ import annotations

import hashlib
import json
from fnmatch import fnmatch
from typing import Any
from uuid import uuid4

from anjor.analysis.drift.fingerprint import fingerprint
from anjor.core.events.base import BaseEvent
from anjor.core.events.llm_call import LLMCallEvent, LLMTokenUsage
from anjor.core.events.tool_call import (
    FailureType,
    TokenUsage,
    ToolCallEvent,
    ToolCallStatus,
)
from anjor.interceptors.parsers.base import BaseParser

# Sensitive key patterns — matched case-insensitively
_SENSITIVE_PATTERNS = [
    "*api_key*",
    "*secret*",
    "*password*",
    "*token*",
    "*auth*",
    "*bearer*",
]

_ANTHROPIC_MESSAGES_URL = "api.anthropic.com/v1/messages"

# Known Anthropic model context window limits (tokens)
# DECISION: hardcoded map rather than API call — keeps the interceptor sync and zero-latency.
# Unknown models fall back to 0 (reported as "unknown" in context utilisation).
_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "claude-3-5-sonnet-20241022": 200_000,
    "claude-3-5-haiku-20241022": 200_000,
    "claude-3-opus-20240229": 200_000,
    "claude-3-sonnet-20240229": 200_000,
    "claude-3-haiku-20240307": 200_000,
    # Claude 3.7
    "claude-3-7-sonnet-20250219": 200_000,
    "claude-opus-4-5": 200_000,
    "claude-sonnet-4-5": 200_000,
    "claude-haiku-4-5": 200_000,
    # Claude 4.x models
    "claude-opus-4-6": 200_000,
    "claude-sonnet-4-6": 200_000,
    "claude-haiku-4-5-20251001": 200_000,
}

_CLAUDE_PREFIX = "claude-"
_CLAUDE_DEFAULT_CONTEXT_LIMIT = 200_000


def _sanitise(payload: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact keys matching sensitive patterns."""
    result: dict[str, Any] = {}
    for k, v in payload.items():
        if any(fnmatch(k.lower(), pat) for pat in _SENSITIVE_PATTERNS):
            result[k] = "[REDACTED]"
        elif isinstance(v, dict):
            result[k] = _sanitise(v)
        elif isinstance(v, list):
            result[k] = [_sanitise(item) if isinstance(item, dict) else item for item in v]
        else:
            result[k] = v
    return result


def _prompt_hash(messages: list[dict[str, Any]]) -> str:
    """Structural hash of the messages list (types + roles, not content values)."""
    shape = [
        {"role": m.get("role", ""), "content_type": type(m.get("content")).__name__}
        for m in messages
    ]
    canonical = json.dumps(shape, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


def _system_prompt_hash(system: str | list[Any] | None) -> str | None:
    """SHA-256 hash of the system prompt string or structured content."""
    if system is None:
        return None
    if isinstance(system, str):
        canonical = system
    else:
        canonical = json.dumps(system, sort_keys=True)
    return hashlib.sha256(canonical.encode()).hexdigest()


class AnthropicParser(BaseParser):
    """Parses Anthropic messages API responses into ToolCallEvents and LLMCallEvents.

    Every /v1/messages call produces one LLMCallEvent. Tool use blocks additionally
    produce one ToolCallEvent per block.
    """

    def can_parse(self, url: str) -> bool:
        return _ANTHROPIC_MESSAGES_URL in url

    def parse(
        self,
        url: str,
        request_body: dict[str, Any],
        response_body: dict[str, Any],
        latency_ms: float,
        status_code: int,
    ) -> list[BaseEvent]:
        events: list[BaseEvent] = []

        is_success = 200 <= status_code < 300

        # ── Extract shared fields ──────────────────────────────────────────────
        usage = response_body.get("usage", {})
        token_usage: TokenUsage | None = None
        llm_token_usage: LLMTokenUsage | None = None
        if usage:
            token_usage = TokenUsage(
                input=usage.get("input_tokens", 0),
                output=usage.get("output_tokens", 0),
            )
            llm_token_usage = LLMTokenUsage(
                input=usage.get("input_tokens", 0),
                output=usage.get("output_tokens", 0),
                cache_creation=usage.get("cache_creation_input_tokens", 0),
                cache_read=usage.get("cache_read_input_tokens", 0),
            )

        metadata = request_body.get("metadata", {})
        trace_id: str = metadata.get("trace_id", "") if isinstance(metadata, dict) else ""
        session_id: str = metadata.get("session_id", "") if isinstance(metadata, dict) else ""
        # Fall back to UUID if not supplied in request metadata
        trace_id_val = trace_id if trace_id else str(uuid4())
        session_id_val = session_id if session_id else str(uuid4())

        messages: list[dict[str, Any]] = request_body.get("messages", [])
        system = request_body.get("system")
        model: str = request_body.get("model", "")
        context_limit = _MODEL_CONTEXT_LIMITS.get(
            model,
            _CLAUDE_DEFAULT_CONTEXT_LIMIT if model.startswith(_CLAUDE_PREFIX) else 0,
        )
        context_used = (
            (usage.get("input_tokens", 0) + usage.get("output_tokens", 0)) if usage else 0
        )

        # ── Build LLMCallEvent (always emitted) ───────────────────────────────
        llm_event = LLMCallEvent(
            model=model,
            latency_ms=latency_ms,
            token_usage=llm_token_usage,
            context_window_used=context_used,
            context_window_limit=context_limit,
            prompt_hash=_prompt_hash(messages) if messages else "",
            system_prompt_hash=_system_prompt_hash(system),
            messages_count=len(messages),
            finish_reason=response_body.get("stop_reason"),
            trace_id=trace_id_val,
            session_id=session_id_val,
        )
        events.append(llm_event)

        # ── Build ToolCallEvents (one per tool_use block) ─────────────────────
        content = response_body.get("content", [])
        if not isinstance(content, list):
            content = []

        tool_use_blocks = [b for b in content if b.get("type") == "tool_use"]

        if not tool_use_blocks and not is_success:
            sanitised_req = _sanitise(request_body)
            sanitised_resp = _sanitise(response_body)
            error_event = ToolCallEvent(
                tool_name="unknown",
                status=ToolCallStatus.FAILURE,
                failure_type=FailureType.API_ERROR,
                latency_ms=latency_ms,
                input_payload=sanitised_req,
                output_payload=sanitised_resp,
                input_schema_hash=fingerprint(sanitised_req),
                output_schema_hash=fingerprint(sanitised_resp),
                token_usage=token_usage,
                trace_id=trace_id_val,
                session_id=session_id_val,
            )
            events.append(error_event)
            return events

        for block in tool_use_blocks:
            tool_name: str = block.get("name", "unknown")
            tool_input: dict[str, Any] = block.get("input", {})

            sanitised_input = _sanitise(tool_input)
            tool_output: dict[str, Any] = {}

            status = ToolCallStatus.SUCCESS if is_success else ToolCallStatus.FAILURE
            failure_type: FailureType | None = None if is_success else FailureType.API_ERROR

            event = ToolCallEvent(
                tool_name=tool_name,
                status=status,
                failure_type=failure_type,
                latency_ms=latency_ms,
                input_payload=sanitised_input,
                output_payload=tool_output,
                input_schema_hash=fingerprint(sanitised_input),
                output_schema_hash=fingerprint(tool_output),
                token_usage=token_usage,
                trace_id=trace_id_val,
                session_id=session_id_val,
            )
            events.append(event)

        return events
