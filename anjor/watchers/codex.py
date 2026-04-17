"""CodexTranscriptWatcher — transcript watcher for OpenAI Codex CLI sessions.

Codex CLI writes one JSONL file per session to:
  Mac/Linux: ~/.codex/sessions/YYYY/MM/DD/<timestamp>-<session-uuid>.jsonl
  Windows:   %APPDATA%\\Codex\\sessions\\YYYY\\MM\\DD\\<timestamp>-<session-uuid>.jsonl

Each line: {"timestamp": "...", "type": "...", "payload": {...}}

Relevant outer types:

  session_meta     → session UUID (used as trace_id)
  turn_context     → model name for the turn
  event_msg        → token counts (token_count subtype) and context window size
                     (task_started subtype)
  response_item    → function_call (tool invocation) and
                     function_call_output (tool result)

Stateful parsing
----------------
function_call entries are buffered by call_id. When the matching
function_call_output arrives, a ToolCallEvent is emitted with latency =
timestamp delta and status derived from "Process exited with code N"
in the output string (non-zero → FAILURE).

LLMCallEvents are emitted for each event_msg of type token_count that
carries last_token_usage — this fires after each model response and
captures per-call token consumption.

Session ID
----------
Extracted from the filename UUID rather than from session_meta so that
watchers resuming mid-file (saved byte offset) still have the correct
trace_id without needing to re-read the first line.

Confirmed format (Codex CLI v0.115.0-alpha.11, 2026-03-15):
  function_call payload:   name, arguments (JSON string), call_id
  function_call_output:    call_id, output (plain text with exit code line)
  token_count info:        last_token_usage.{input_tokens, cached_input_tokens,
                           output_tokens, reasoning_output_tokens}
"""

from __future__ import annotations

import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from anjor.analysis.drift.fingerprint import fingerprint
from anjor.core.events.base import BaseEvent
from anjor.core.events.llm_call import LLMCallEvent, LLMTokenUsage
from anjor.core.events.message import MessageEvent
from anjor.core.events.tool_call import (
    FailureType,
    ToolCallEvent,
    ToolCallStatus,
)
from anjor.interceptors.parsers.anthropic import _sanitise
from anjor.watchers.base import BaseTranscriptWatcher

logger = structlog.get_logger(__name__)

_EXIT_CODE_RE = re.compile(r"Process exited with code (\d+)")
_SESSION_UUID_RE = re.compile(
    r"([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})", re.IGNORECASE
)

_GC_TIMEOUT_SECONDS = 60
_GC_EVERY_N_CALLS = 10


def _parse_ts(ts_str: str) -> datetime:
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(UTC)


def _exit_code_from_output(output: str) -> int:
    """Extract numeric exit code from Codex function_call_output text."""
    m = _EXIT_CODE_RE.search(output)
    return int(m.group(1)) if m else 0


def _session_id_from_path(path: str) -> str:
    """Extract the session UUID embedded in the Codex filename."""
    m = _SESSION_UUID_RE.search(Path(path).stem)
    return m.group(1) if m else str(uuid4())


class CodexTranscriptWatcher(BaseTranscriptWatcher):
    """Reads OpenAI Codex CLI session JSONL files and emits LLMCallEvents + ToolCallEvents."""

    provider_name = "OpenAI Codex"
    source_tag = "openai_codex"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # call_id → {name, input, ts, session_id}
        self._pending: dict[str, dict[str, Any]] = {}
        self._current_model: str = ""
        self._current_context_window: int = 0
        self._current_session_id: str = ""
        self._gc_counter = 0

    def _project_from_path(self, path: str) -> str:
        # Set the session ID from the filename before any lines are processed.
        # This ensures parse_line() always has a valid session_id even when
        # resuming mid-file (session_meta line already consumed in a prior run).
        self._current_session_id = _session_id_from_path(path)
        return ""

    def default_paths(self) -> list[str]:
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            return [str(Path(appdata) / "Codex" / "sessions" / "**" / "*.jsonl")]
        return [str(Path.home() / ".codex" / "sessions" / "**" / "*.jsonl")]

    def parse_line(self, line: str) -> list[BaseEvent] | None:
        self._gc_counter += 1
        if self._gc_counter >= _GC_EVERY_N_CALLS:
            self._gc_pending()
            self._gc_counter = 0

        try:
            entry: dict[str, Any] = json.loads(line)
        except (json.JSONDecodeError, ValueError):
            return None

        outer_type = entry.get("type", "")
        payload: dict[str, Any] = entry.get("payload") or {}
        ts = _parse_ts(entry.get("timestamp", ""))

        if outer_type == "session_meta":
            session_id = payload.get("id")
            if session_id:
                self._current_session_id = str(session_id)
            return None

        if outer_type == "turn_context":
            model = payload.get("model")
            if model:
                self._current_model = str(model)
            ctx = payload.get("model_context_window")
            if ctx is not None:
                self._current_context_window = int(ctx)
            return None

        if outer_type == "event_msg":
            payload_type = payload.get("type", "")
            if payload_type == "task_started":
                ctx = payload.get("model_context_window")
                if ctx is not None:
                    self._current_context_window = int(ctx)
            elif payload_type == "token_count":
                return self._handle_token_count(payload, ts)
            elif payload_type == "user_message" and self._capture_messages:
                text = str(payload.get("message") or "").strip()
                if text:
                    return [
                        MessageEvent(
                            role="user",
                            content_preview=text[:500],
                            turn_index=0,
                            session_id=self._current_session_id,
                            trace_id=self._current_session_id,
                            timestamp=ts,
                            source=self.source_tag,
                        )
                    ]
            elif payload_type == "agent_message" and self._capture_messages:
                text = str(payload.get("message") or "").strip()
                if text:
                    return [
                        MessageEvent(
                            role="assistant",
                            content_preview=text[:500],
                            turn_index=0,
                            session_id=self._current_session_id,
                            trace_id=self._current_session_id,
                            timestamp=ts,
                            source=self.source_tag,
                        )
                    ]
            return None

        if outer_type == "response_item":
            payload_type = payload.get("type", "")
            if payload_type == "function_call":
                return self._handle_function_call(payload, ts)
            if payload_type == "function_call_output":
                return self._handle_function_call_output(payload, ts)
            return None

        return None

    # ── Tool call handling ─────────────────────────────────────────────────

    def _handle_function_call(self, payload: dict[str, Any], ts: datetime) -> list[BaseEvent]:
        call_id: str = payload.get("call_id") or str(uuid4())
        name: str = payload.get("name", "unknown")
        args_raw: str = payload.get("arguments") or "{}"
        try:
            args: dict[str, Any] = json.loads(args_raw)
        except (json.JSONDecodeError, ValueError):
            args = {"raw": args_raw[:500]}

        self._pending[call_id] = {
            "name": name,
            "input": args,
            "ts": ts,
            "session_id": self._current_session_id,
        }
        return []

    def _handle_function_call_output(
        self, payload: dict[str, Any], ts: datetime
    ) -> list[BaseEvent]:
        call_id: str = payload.get("call_id", "")
        pending = self._pending.pop(call_id, None)
        if pending is None:
            return []

        output: str = payload.get("output") or ""
        exit_code = _exit_code_from_output(output)
        is_failure = exit_code != 0

        start_ts: datetime = pending["ts"]
        latency_ms = max(0.0, (ts - start_ts).total_seconds() * 1000)

        sanitised_input = _sanitise(pending["input"]) if isinstance(pending["input"], dict) else {}
        output_payload: dict[str, Any] = {"text": output[:2000]} if output else {}

        return [
            ToolCallEvent(
                tool_name=pending["name"],
                status=ToolCallStatus.FAILURE if is_failure else ToolCallStatus.SUCCESS,
                failure_type=FailureType.UNKNOWN if is_failure else None,
                latency_ms=latency_ms,
                input_payload=sanitised_input,
                output_payload=output_payload,
                input_schema_hash=fingerprint(sanitised_input),
                output_schema_hash=fingerprint(output_payload),
                trace_id=pending["session_id"],
                session_id=pending["session_id"],
                timestamp=ts,
                source=self.source_tag,
            )
        ]

    # ── LLM token counting ─────────────────────────────────────────────────

    def _handle_token_count(self, payload: dict[str, Any], ts: datetime) -> list[BaseEvent]:
        info: dict[str, Any] = payload.get("info") or {}
        usage: dict[str, Any] = info.get("last_token_usage") or {}

        input_tokens = int(usage.get("input_tokens") or 0)
        cached_tokens = int(usage.get("cached_input_tokens") or 0)
        output_tokens = int(usage.get("output_tokens") or 0)

        if not self._current_model or (input_tokens == 0 and output_tokens == 0):
            return []

        context_used = input_tokens + output_tokens
        return [
            LLMCallEvent(
                model=self._current_model,
                latency_ms=0.0,
                token_usage=LLMTokenUsage(
                    input=input_tokens,
                    output=output_tokens,
                    cache_creation=0,
                    cache_read=cached_tokens,
                ),
                context_window_used=context_used,
                context_window_limit=self._current_context_window,
                trace_id=self._current_session_id,
                session_id=self._current_session_id,
                timestamp=ts,
                source=self.source_tag,
            )
        ]

    # ── Pending GC ────────────────────────────────────────────────────────

    def _gc_pending(self) -> None:
        """Remove _pending entries older than _GC_TIMEOUT_SECONDS."""
        now = datetime.now(UTC)
        stale = [
            k
            for k, v in self._pending.items()
            if (now - v["ts"]).total_seconds() > _GC_TIMEOUT_SECONDS
        ]
        for k in stale:
            del self._pending[k]
