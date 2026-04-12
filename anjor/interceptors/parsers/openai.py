"""OpenAIParser — extracts ToolCallEvent and LLMCallEvent from OpenAI API responses."""

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

_SENSITIVE_PATTERNS = [
    "*api_key*",
    "*secret*",
    "*password*",
    "*token*",
    "*auth*",
    "*bearer*",
]

_OPENAI_CHAT_URL = "api.openai.com/v1/chat/completions"

_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gpt-4o": 128_000,
    "gpt-4o-mini": 128_000,
    "gpt-4-turbo": 128_000,
    "gpt-4": 8_192,
    "gpt-3.5-turbo": 16_385,
    "o1": 200_000,
    "o1-mini": 128_000,
    "o3-mini": 200_000,
}


def _sanitise(payload: dict[str, Any]) -> dict[str, Any]:
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
    """Structural hash of the messages list (roles + content types only)."""
    shape = [
        {"role": m.get("role", ""), "content_type": type(m.get("content")).__name__}
        for m in messages
    ]
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()


def _parse_tool_arguments(arguments: Any) -> dict[str, Any]:
    """Parse tool call arguments — OpenAI sends them as a JSON string."""
    if isinstance(arguments, dict):
        return arguments
    if isinstance(arguments, str):
        if not arguments.strip():
            return {}
        try:
            result = json.loads(arguments)
            return result if isinstance(result, dict) else {"value": result}
        except (json.JSONDecodeError, ValueError):
            return {"raw": arguments}
    return {}


class OpenAIParser(BaseParser):
    """Parses OpenAI chat completions API responses into ToolCallEvents and LLMCallEvents.

    Every /v1/chat/completions call produces one LLMCallEvent. Tool call
    blocks additionally produce one ToolCallEvent per function call.
    """

    def can_parse(self, url: str) -> bool:
        return _OPENAI_CHAT_URL in url

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

        # ── Token usage ───────────────────────────────────────────────────────
        usage = response_body.get("usage", {})
        token_input = usage.get("prompt_tokens", 0)
        token_output = usage.get("completion_tokens", 0)
        token_usage: TokenUsage | None = None
        llm_token_usage: LLMTokenUsage | None = None
        if usage:
            token_usage = TokenUsage(input=token_input, output=token_output)
            llm_token_usage = LLMTokenUsage(input=token_input, output=token_output)

        # ── IDs ───────────────────────────────────────────────────────────────
        trace_id_val = str(uuid4())
        session_id_val = str(uuid4())

        # ── Model + context window ────────────────────────────────────────────
        # Prefer the model from the response (may be versioned, e.g. gpt-4o-2024-08-06)
        model: str = response_body.get("model") or request_body.get("model", "")
        # Strip versioned suffix for limit lookup (gpt-4o-2024-08-06 → gpt-4o)
        model_key = model.split("-20")[0] if "-20" in model else model
        context_limit = _MODEL_CONTEXT_LIMITS.get(model_key) or _MODEL_CONTEXT_LIMITS.get(model, 0)
        context_used = token_input + token_output

        # ── Prompt metadata ───────────────────────────────────────────────────
        messages: list[dict[str, Any]] = request_body.get("messages", [])
        first_choice: dict[str, Any] = {}
        choices = response_body.get("choices", [])
        if choices and isinstance(choices, list):
            first_choice = choices[0] if isinstance(choices[0], dict) else {}

        finish_reason: str | None = first_choice.get("finish_reason")

        # ── LLMCallEvent (always emitted) ─────────────────────────────────────
        llm_event = LLMCallEvent(
            model=model,
            latency_ms=latency_ms,
            token_usage=llm_token_usage,
            context_window_used=context_used,
            context_window_limit=context_limit,
            prompt_hash=_prompt_hash(messages) if messages else "",
            messages_count=len(messages),
            finish_reason=finish_reason,
            trace_id=trace_id_val,
            session_id=session_id_val,
        )
        events.append(llm_event)

        # ── ToolCallEvents ────────────────────────────────────────────────────
        message = first_choice.get("message", {})
        tool_calls = message.get("tool_calls") if isinstance(message, dict) else None

        if not tool_calls and not is_success:
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

        for tc in tool_calls or []:
            if not isinstance(tc, dict):
                continue
            func = tc.get("function", {})
            tool_name: str = func.get("name", "unknown")
            raw_args = func.get("arguments", {})
            parsed_args = _parse_tool_arguments(raw_args)
            sanitised_input = _sanitise(parsed_args)

            status = ToolCallStatus.SUCCESS if is_success else ToolCallStatus.FAILURE
            failure_type: FailureType | None = None if is_success else FailureType.API_ERROR

            event = ToolCallEvent(
                tool_name=tool_name,
                status=status,
                failure_type=failure_type,
                latency_ms=latency_ms,
                input_payload=sanitised_input,
                output_payload={},
                input_schema_hash=fingerprint(sanitised_input),
                output_schema_hash=fingerprint({}),
                token_usage=token_usage,
                trace_id=trace_id_val,
                session_id=session_id_val,
            )
            events.append(event)

        return events
