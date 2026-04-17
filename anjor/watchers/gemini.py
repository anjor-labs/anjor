"""GeminiTranscriptWatcher — transcript watcher for Gemini CLI sessions.

Gemini CLI stores sessions as JSON files (not JSONL) under:
  ~/.gemini/tmp/<project>/chats/<session-id>/<chat-id>.json

Each file has this confirmed structure:
  {
    "sessionId": str,
    "messages": [
      {
        "id": str,
        "type": "user" | "gemini" | "info",
        "timestamp": ISO-8601 str,
        "content": str | list,
        "model": str,                   # on gemini messages
        "tokens": {                     # on gemini messages
          "input": int,
          "output": int,
          "cached": int,
          "thoughts": int,
          "tool": int,
          "total": int,
        },
        "toolCalls": [                  # on gemini messages with tool use
          {
            "id": str,
            "name": str,
            "args": dict,
            "result": [...],
            "status": "success" | "error",
            "timestamp": ISO-8601 str,
          }
        ],
        "thoughts": [...],             # reasoning steps (skip for events)
      }
    ]
  }

Because files are full JSON (not JSONL), this watcher overrides _tail() to
read the whole file on each poll, tracking which message IDs have already
been emitted via _seen_ids (in-memory; old events may re-emit after restart,
which is acceptable for transcript ingestion).

Emits:
- LLMCallEvent for every gemini-type message that has token data.
- ToolCallEvent for each toolCall entry inside a gemini message.
"""

from __future__ import annotations

import json
import os
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

import structlog

from anjor.core.events.base import BaseEvent
from anjor.core.events.llm_call import LLMCallEvent, LLMTokenUsage
from anjor.core.events.message import MessageEvent
from anjor.core.events.tool_call import (
    FailureType,
    ToolCallEvent,
    ToolCallStatus,
)
from anjor.watchers.base import BaseTranscriptWatcher

logger = structlog.get_logger(__name__)

# Context-window sizes by model prefix (best-effort)
_CONTEXT_WINDOW: dict[str, int] = {
    "gemini-2.0-flash": 1_048_576,
    "gemini-2.5": 1_048_576,
    "gemini-3": 1_048_576,
    "gemini-1.5-pro": 2_097_152,
    "gemini-1.5-flash": 1_048_576,
}
_DEFAULT_CONTEXT = 1_048_576


def _context_limit(model: str) -> int:
    for prefix, limit in _CONTEXT_WINDOW.items():
        if model.startswith(prefix):
            return limit
    return _DEFAULT_CONTEXT


def _parse_ts(ts_str: str) -> datetime:
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(UTC)


class GeminiTranscriptWatcher(BaseTranscriptWatcher):
    """Reads ~/.gemini/tmp/**/*.json and emits LLMCallEvents + ToolCallEvents."""

    provider_name = "Gemini CLI"
    source_tag = "gemini_cli"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # Track processed message IDs in memory to avoid re-emission.
        # Keyed by (filepath, message_id).
        self._seen_ids: set[tuple[str, str]] = set()

    # ── Path discovery ─────────────────────────────────────────────────────

    def default_paths(self) -> list[str]:
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            return [str(Path(appdata) / "Gemini" / "tmp" / "**" / "*.json")]
        # macOS/Linux: ~/.gemini/tmp/<project>/chats/<session>/<chat>.json
        return [str(Path.home() / ".gemini" / "tmp" / "**" / "*.json")]

    # ── parse_line not used — we override _tail() instead ─────────────────

    def parse_line(self, line: str) -> list[BaseEvent] | None:  # pragma: no cover
        # Gemini CLI files are JSON, not JSONL. _tail() handles them directly.
        return None

    # ── Override _tail to handle whole-file JSON ───────────────────────────

    def _tail(self, path: str) -> None:
        """Read the whole JSON file; emit events for unseen gemini messages."""
        # Use file size as a cheap change-detector. If unchanged, skip.
        try:
            current_size = Path(path).stat().st_size
        except OSError:
            return

        last_size = self._offsets.get(path, -1)
        if current_size == last_size:
            return  # file hasn't grown since last poll

        try:
            text = Path(path).read_text(encoding="utf-8", errors="replace")
        except (PermissionError, OSError) as exc:
            logger.warning("gemini_watcher_read_error", path=path, error=str(exc))
            return

        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            # File may be mid-write; keep last_size unchanged so we retry
            return

        if not isinstance(data, dict):
            self._offsets[path] = current_size
            return

        session_id = data.get("sessionId", "") or str(uuid4())
        messages = data.get("messages", [])
        if not isinstance(messages, list):
            self._offsets[path] = current_size
            return

        events: list[BaseEvent] = []
        for msg in messages:
            if not isinstance(msg, dict):
                continue
            msg_id = msg.get("id", "")
            key = (path, msg_id)
            if msg_id and key in self._seen_ids:
                continue

            msg_type = msg.get("type")
            if msg_type == "gemini":
                evts = self._handle_gemini_message(msg, session_id)
                events.extend(evts)
            elif msg_type == "user" and self._capture_messages:
                evt = self._handle_user_message(msg, session_id)
                if evt is not None:
                    events.append(evt)

            if msg_id:
                self._seen_ids.add(key)
                # Bound the set to avoid unbounded growth
                if len(self._seen_ids) > 100_000:
                    self._seen_ids = set(list(self._seen_ids)[-50_000:])

        if events:
            self._post_events(events)

        self._offsets[path] = current_size

    # ── Parsing helpers ────────────────────────────────────────────────────

    def _extract_text(self, content: Any) -> str:
        """Extract plain text from Gemini content (string or list of {text} dicts)."""
        if isinstance(content, str):
            return content[:500]
        if isinstance(content, list):
            parts = [
                item.get("text", "")
                for item in content
                if isinstance(item, dict) and item.get("text")
            ]
            return " ".join(parts)[:500]
        return ""

    def _handle_user_message(self, msg: dict[str, Any], session_id: str) -> MessageEvent | None:
        preview = self._extract_text(msg.get("content", ""))
        if not preview.strip():
            return None
        ts = _parse_ts(msg.get("timestamp", ""))
        return MessageEvent(
            role="user",
            content_preview=preview,
            turn_index=0,
            session_id=session_id,
            trace_id=session_id,
            timestamp=ts,
            source=self.source_tag,
        )

    def _handle_gemini_message(self, msg: dict[str, Any], session_id: str) -> list[BaseEvent]:
        """Emit one LLMCallEvent + zero-or-more ToolCallEvents per gemini turn."""
        tokens = msg.get("tokens") or {}
        model: str = msg.get("model", "gemini-cli")
        ts = _parse_ts(msg.get("timestamp", ""))

        token_input = tokens.get("input", 0)
        token_output = tokens.get("output", 0)
        token_cached = tokens.get("cached", 0)
        token_thoughts = tokens.get("thoughts", 0)
        token_total = tokens.get("total", 0)

        events: list[BaseEvent] = []

        # ── LLMCallEvent ───────────────────────────────────────────────────
        if token_total > 0 or token_output > 0:
            ctx_limit = _context_limit(model)
            ctx_used = token_input + token_cached + token_output + token_thoughts
            llm_event = LLMCallEvent(
                model=model,
                latency_ms=0.0,  # not available in session files
                token_usage=LLMTokenUsage(
                    input=token_input,
                    output=token_output,
                    cache_read=token_cached,
                ),
                context_window_used=ctx_used,
                context_window_limit=ctx_limit,
                context_utilisation=ctx_used / ctx_limit if ctx_limit else 0.0,
                finish_reason="stop",
                trace_id=session_id,
                session_id=session_id,
                timestamp=ts,
                source=self.source_tag,
            )
            events.append(llm_event)

        # ── MessageEvent (opt-in) ──────────────────────────────────────────
        if self._capture_messages:
            preview = self._extract_text(msg.get("content", ""))
            if preview.strip():
                events.append(
                    MessageEvent(
                        role="assistant",
                        content_preview=preview,
                        turn_index=0,
                        token_count=token_output or None,
                        session_id=session_id,
                        trace_id=session_id,
                        timestamp=ts,
                        source=self.source_tag,
                    )
                )

        # ── ToolCallEvents (one per toolCall entry) ────────────────────────
        for tc in msg.get("toolCalls", []):
            if not isinstance(tc, dict):
                continue
            evt = self._tool_call_event(tc, session_id, ts)
            if evt is not None:
                events.append(evt)

        return events

    def _tool_call_event(
        self,
        tc: dict[str, Any],
        session_id: str,
        fallback_ts: datetime,
    ) -> ToolCallEvent | None:
        tool_name = tc.get("name", "unknown")
        status_str = tc.get("status", "success")
        is_error = status_str != "success"
        ts = _parse_ts(tc.get("timestamp", "")) if tc.get("timestamp") else fallback_ts

        args = tc.get("args") or {}
        if not isinstance(args, dict):
            args = {}

        # Build a trimmed output from the result field
        raw_result = tc.get("result", [])
        output_text = ""
        if isinstance(raw_result, list):
            for item in raw_result:
                if isinstance(item, dict):
                    fr = item.get("functionResponse", {})
                    resp = fr.get("response", {})
                    out = resp.get("output", "")
                    if out:
                        output_text = str(out)[:2000]
                        break
        elif isinstance(raw_result, str):
            output_text = raw_result[:2000]

        input_payload = {k: str(v)[:500] for k, v in args.items()}
        output_payload = {"text": output_text} if output_text else {}

        return ToolCallEvent(
            tool_name=f"gemini__{tool_name}",
            status=ToolCallStatus.FAILURE if is_error else ToolCallStatus.SUCCESS,
            failure_type=FailureType.UNKNOWN if is_error else None,
            latency_ms=0.0,  # Gemini CLI doesn't record tool latency in session files
            input_payload=input_payload,
            output_payload=output_payload,
            input_schema_hash="",
            output_schema_hash="",
            trace_id=session_id,
            session_id=session_id,
            timestamp=ts,
            source=self.source_tag,
        )
