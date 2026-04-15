"""GeminiParser — extracts ToolCallEvent and LLMCallEvent from Gemini API responses."""

from __future__ import annotations

import hashlib
import json
import re
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

_GEMINI_URL = "generativelanguage.googleapis.com"

_MODEL_CONTEXT_LIMITS: dict[str, int] = {
    "gemini-2.5-pro": 1_048_576,
    "gemini-2.0-flash": 1_048_576,
    "gemini-2.0-flash-8b": 1_048_576,
    "gemini-1.5-pro": 2_097_152,
    "gemini-1.5-flash": 1_048_576,
    "gemini-1.5-flash-8b": 1_048_576,
    "gemini-1.0-pro": 32_768,
}

_GEMINI_PREFIX = "gemini-"
_GEMINI_DEFAULT_CONTEXT_LIMIT = 1_048_576

_MODEL_RE = re.compile(r"/models/([^/:]+)")


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


def _prompt_hash(contents: list[dict[str, Any]]) -> str:
    """Structural hash of contents list (role + part key names only)."""
    shape = [
        {
            "role": c.get("role", ""),
            "part_keys": sorted(
                {k for part in c.get("parts", []) if isinstance(part, dict) for k in part}
            ),
        }
        for c in contents
    ]
    return hashlib.sha256(json.dumps(shape, sort_keys=True).encode()).hexdigest()


def _model_from_url(url: str) -> str:
    """Extract model name from Gemini URL path, e.g. .../models/gemini-2.0-flash:generateContent."""
    m = _MODEL_RE.search(url)
    return m.group(1) if m else ""


class GeminiParser(BaseParser):
    """Parses Gemini generateContent API responses into LLMCallEvents and ToolCallEvents.

    Every generateContent call produces one LLMCallEvent. Function call
    parts additionally produce one ToolCallEvent each.
    """

    def can_parse(self, url: str) -> bool:
        return _GEMINI_URL in url

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
        usage = response_body.get("usageMetadata", {})
        token_input = usage.get("promptTokenCount", 0)
        token_output = usage.get("candidatesTokenCount", 0)
        # cachedContentTokenCount is a subset of promptTokenCount — the portion
        # of the prompt served from Gemini's implicit context cache (cache_read).
        cache_read = usage.get("cachedContentTokenCount", 0)
        token_usage: TokenUsage | None = None
        llm_token_usage: LLMTokenUsage | None = None
        if usage:
            token_usage = TokenUsage(input=token_input, output=token_output)
            llm_token_usage = LLMTokenUsage(
                input=token_input, output=token_output, cache_read=cache_read
            )

        # ── IDs ───────────────────────────────────────────────────────────────
        trace_id_val = str(uuid4())
        session_id_val = str(uuid4())

        # ── Model ─────────────────────────────────────────────────────────────
        # Prefer modelVersion from response body; fall back to URL extraction
        model: str = response_body.get("modelVersion") or _model_from_url(url)
        context_limit = _MODEL_CONTEXT_LIMITS.get(
            model,
            _GEMINI_DEFAULT_CONTEXT_LIMIT if model.startswith(_GEMINI_PREFIX) else 0,
        )
        context_used = token_input + token_output

        # ── Prompt metadata ───────────────────────────────────────────────────
        contents: list[dict[str, Any]] = request_body.get("contents", [])
        candidates = response_body.get("candidates", [])
        first_candidate: dict[str, Any] = (
            candidates[0] if candidates and isinstance(candidates[0], dict) else {}
        )
        finish_reason: str | None = first_candidate.get("finishReason")

        # ── LLMCallEvent (always emitted) ─────────────────────────────────────
        llm_event = LLMCallEvent(
            model=model,
            latency_ms=latency_ms,
            token_usage=llm_token_usage,
            context_window_used=context_used,
            context_window_limit=context_limit,
            prompt_hash=_prompt_hash(contents) if contents else "",
            messages_count=len(contents),
            finish_reason=finish_reason,
            trace_id=trace_id_val,
            session_id=session_id_val,
        )
        events.append(llm_event)

        # ── ToolCallEvents ────────────────────────────────────────────────────
        parts = first_candidate.get("content", {}).get("parts", [])
        function_calls = [
            p["functionCall"] for p in parts if isinstance(p, dict) and "functionCall" in p
        ]

        if not function_calls and not is_success:
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

        for fc in function_calls:
            if not isinstance(fc, dict):
                continue
            tool_name: str = fc.get("name", "unknown")
            # Gemini args are already a dict — no JSON parsing needed
            raw_args = fc.get("args", {})
            args: dict[str, Any] = raw_args if isinstance(raw_args, dict) else {}
            sanitised_input = _sanitise(args)

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
