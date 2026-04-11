"""AnthropicParser — extracts ToolCallEvent from Anthropic API responses."""

from __future__ import annotations

from fnmatch import fnmatch
from typing import Any
from uuid import uuid4

from agentscope.analysis.drift.fingerprint import fingerprint
from agentscope.core.events.base import BaseEvent
from agentscope.core.events.tool_call import (
    FailureType,
    TokenUsage,
    ToolCallEvent,
    ToolCallStatus,
)
from agentscope.interceptors.parsers.base import BaseParser

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


def _sanitise(payload: dict[str, Any]) -> dict[str, Any]:
    """Recursively redact keys matching sensitive patterns."""
    result: dict[str, Any] = {}
    for k, v in payload.items():
        if any(fnmatch(k.lower(), pat) for pat in _SENSITIVE_PATTERNS):
            result[k] = "[REDACTED]"
        elif isinstance(v, dict):
            result[k] = _sanitise(v)
        elif isinstance(v, list):
            result[k] = [
                _sanitise(item) if isinstance(item, dict) else item for item in v
            ]
        else:
            result[k] = v
    return result


class AnthropicParser(BaseParser):
    """Parses Anthropic messages API responses into ToolCallEvents.

    Handles tool_use blocks in response content. Each tool_use block
    becomes one ToolCallEvent.
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

        # Determine success/failure from status code
        is_success = 200 <= status_code < 300

        # Extract token usage from response
        token_usage: TokenUsage | None = None
        usage = response_body.get("usage", {})
        if usage:
            token_usage = TokenUsage(
                input=usage.get("input_tokens", 0),
                output=usage.get("output_tokens", 0),
            )

        # Extract trace/session IDs from request metadata if present
        metadata = request_body.get("metadata", {})
        trace_id: str = metadata.get("trace_id", "")
        session_id: str = metadata.get("session_id", "")

        # Extract tool_use blocks from response content
        content = response_body.get("content", [])

        if not isinstance(content, list):
            content = []

        tool_use_blocks = [
            block for block in content if block.get("type") == "tool_use"
        ]

        if not tool_use_blocks and is_success:
            # No tool calls in this response
            return []

        if not tool_use_blocks and not is_success:
            # API error with no tool calls — create a single failure event
            sanitised_req = _sanitise(request_body)
            sanitised_resp = _sanitise(response_body)
            event = ToolCallEvent(
                tool_name="unknown",
                status=ToolCallStatus.FAILURE,
                failure_type=FailureType.API_ERROR,
                latency_ms=latency_ms,
                input_payload=sanitised_req,
                output_payload=sanitised_resp,
                input_schema_hash=fingerprint(sanitised_req),
                output_schema_hash=fingerprint(sanitised_resp),
                token_usage=token_usage,
                trace_id=trace_id if trace_id else str(uuid4()),
                session_id=session_id if session_id else str(uuid4()),
            )
            events.append(event)
            return events

        for block in tool_use_blocks:
            tool_name: str = block.get("name", "unknown")
            tool_input: dict[str, Any] = block.get("input", {})

            sanitised_input = _sanitise(tool_input)
            sanitised_req = _sanitise(request_body)

            # Find corresponding tool_result in next request if available
            # (not always present — use empty dict as placeholder)
            tool_output: dict[str, Any] = {}

            input_hash = fingerprint(sanitised_input)
            output_hash = fingerprint(tool_output)

            status = ToolCallStatus.SUCCESS if is_success else ToolCallStatus.FAILURE
            failure_type: FailureType | None = (
                None if is_success else FailureType.API_ERROR
            )

            event = ToolCallEvent(
                tool_name=tool_name,
                status=status,
                failure_type=failure_type,
                latency_ms=latency_ms,
                input_payload=sanitised_input,
                output_payload=tool_output,
                input_schema_hash=input_hash,
                output_schema_hash=output_hash,
                token_usage=token_usage,
                trace_id=trace_id if trace_id else str(uuid4()),
                session_id=session_id if session_id else str(uuid4()),
            )
            events.append(event)

        return events
