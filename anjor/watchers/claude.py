"""ClaudeTranscriptWatcher — extracts events from Claude Code JSONL session files.

Claude Code writes one JSONL file per session to:
  Mac/Linux: ~/.claude/projects/<encoded-project-path>/<session-uuid>.jsonl
  Windows:   %APPDATA%\\Claude\\projects\\<encoded-project-path>\\<session-uuid>.jsonl

Each line is a JSON object (one conversation turn). Relevant outer types:

  "assistant"  — Claude's response. Final state has stop_reason != null.
                 Contains token usage and optionally tool_use blocks.
  "user"       — Human or tool turn. May contain tool_result blocks.

Lines with stop_reason=null are streaming intermediate chunks — skipped.
Lines of type "file-history-snapshot", "queue-operation", etc. — skipped.

Stateful parsing
----------------
tool_use blocks (in assistant turns) are buffered by tool_use_id. When the
matching tool_result arrives in a user turn, the ToolCallEvent is emitted
with latency = timestamp delta and status from is_error.

UUID deduplication
------------------
Claude Code writes the same uuid multiple times for streaming. Once a uuid
is processed (stop_reason not null), it is added to _seen_uuids to prevent
double-emission if the file is re-scanned.

Confirmed format (Claude Code v2.1.89, 2026-04-15):
  - top-level: type, uuid, timestamp, sessionId, parentUuid, message
  - message.usage: input_tokens, cache_creation_input_tokens,
                   cache_read_input_tokens, output_tokens
  - tool_result.content: plain string OR list[{type, text}]
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


def _decode_project_dir(encoded: str) -> str:
    """Extract a human-readable project name from a Claude Code encoded directory name.

    Claude Code stores transcripts at ~/.claude/projects/<encoded>/<session>.jsonl
    where <encoded> is the absolute working-directory path with every '/' replaced
    by '-' (spaces and other characters are left as-is).

    Strategy: split on '-' and take the last non-empty segment.  This gives the
    final path component (the project directory name) for the common case.
    Projects whose names contain hyphens will be truncated — users should use
    --project to set an explicit name in that case.
    """
    parts = [p for p in encoded.split("-") if p]
    return parts[-1] if parts else ""


_GC_TIMEOUT_SECONDS = 60
_GC_EVERY_N_CALLS = 10
_SEEN_UUIDS_MAX = 10_000
_SEEN_UUIDS_TRIM = 5_000


def _extract_result_text(content: Any) -> str:
    """tool_result content is a plain string or list[{type, text}]."""
    if isinstance(content, str):
        return content[:2000]
    if isinstance(content, list):
        parts = [
            b.get("text", "") for b in content if isinstance(b, dict) and b.get("type") == "text"
        ]
        return " ".join(parts)[:2000]
    return ""


def _parse_ts(ts_str: str) -> datetime:
    try:
        return datetime.fromisoformat(ts_str.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.now(UTC)


class ClaudeTranscriptWatcher(BaseTranscriptWatcher):
    """Reads Claude Code session JSONL files and emits LLMCallEvents + ToolCallEvents."""

    provider_name = "Claude Code"
    source_tag = "claude_code"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        # tool_use_id → {name, input, ts, session_id}
        self._pending: dict[str, dict[str, Any]] = {}
        self._seen_uuids: set[str] = set()
        self._gc_counter = 0

    def _project_from_path(self, path: str) -> str:
        """Extract project name from a Claude Code transcript file path."""
        return _decode_project_dir(Path(path).parent.name)

    def default_paths(self) -> list[str]:
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            base = Path(appdata) / "Claude" / "projects"
        else:
            base = Path.home() / ".claude" / "projects"
        return [str(base / "**" / "*.jsonl")]

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
        if outer_type == "assistant":
            return self._handle_assistant(entry)
        if outer_type == "user":
            return self._handle_user(entry)
        return None

    # ── Assistant turn ─────────────────────────────────────────────────────

    def _handle_assistant(self, entry: dict[str, Any]) -> list[BaseEvent]:
        message: dict[str, Any] = entry.get("message") or {}
        stop_reason = message.get("stop_reason")

        # Skip streaming intermediate chunks — only process final state.
        if stop_reason is None:
            return []

        uuid: str = entry.get("uuid", "")
        if uuid:
            if uuid in self._seen_uuids:
                return []
            self._seen_uuids.add(uuid)
            # Prevent unbounded growth in very long sessions.
            if len(self._seen_uuids) > _SEEN_UUIDS_MAX:
                self._seen_uuids = set(list(self._seen_uuids)[-_SEEN_UUIDS_TRIM:])

        session_id: str = entry.get("sessionId", "") or str(uuid4())
        ts = _parse_ts(entry.get("timestamp", ""))
        usage = message.get("usage") or {}
        events: list[BaseEvent] = []

        # ── LLMCallEvent ───────────────────────────────────────────────────
        model: str = message.get("model", "")
        token_input = int(usage.get("input_tokens") or 0)
        token_output = int(usage.get("output_tokens") or 0)
        cache_creation = int(usage.get("cache_creation_input_tokens") or 0)
        cache_read = int(usage.get("cache_read_input_tokens") or 0)

        # Emit when there is a model name or meaningful output — skips empty
        # accounting-only lines that have zero output and no model.
        if model or token_output > 0:
            context_used = token_input + cache_creation + cache_read + token_output
            context_limit = 200_000 if model.startswith("claude-") else 0
            llm_event = LLMCallEvent(
                model=model,
                latency_ms=0.0,  # not available from transcript
                token_usage=LLMTokenUsage(
                    input=token_input,
                    output=token_output,
                    cache_creation=cache_creation,
                    cache_read=cache_read,
                ),
                context_window_used=context_used,
                context_window_limit=context_limit,
                finish_reason=stop_reason,
                trace_id=session_id,
                session_id=session_id,
                timestamp=ts,
                source=self.source_tag,
            )
            events.append(llm_event)

        content_blocks = message.get("content") or []

        # ── Buffer tool_use blocks ─────────────────────────────────────────
        for block in content_blocks:
            if not isinstance(block, dict) or block.get("type") != "tool_use":
                continue
            tool_id: str = block.get("id") or str(uuid4())
            self._pending[tool_id] = {
                "name": block.get("name", "unknown"),
                "input": block.get("input") or {},
                "ts": ts,
                "session_id": session_id,
            }

        # ── MessageEvent (opt-in) ──────────────────────────────────────────
        if self._capture_messages:
            text_parts = [
                b.get("text", "")
                for b in content_blocks
                if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
            ]
            preview = " ".join(text_parts)[:500]
            if preview:
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

        return events

    # ── User turn (tool results) ───────────────────────────────────────────

    def _handle_user(self, entry: dict[str, Any]) -> list[BaseEvent]:
        message: dict[str, Any] = entry.get("message") or {}
        content = message.get("content")
        session_id: str = entry.get("sessionId", "") or str(uuid4())
        ts = _parse_ts(entry.get("timestamp", ""))
        events: list[BaseEvent] = []

        # ── MessageEvent for plain text user turns (opt-in) ───────────────
        if self._capture_messages:
            if isinstance(content, str) and content.strip():
                events.append(
                    MessageEvent(
                        role="user",
                        content_preview=content[:500],
                        turn_index=0,
                        session_id=session_id,
                        trace_id=session_id,
                        timestamp=ts,
                        source=self.source_tag,
                    )
                )
            elif isinstance(content, list):
                text_parts = [
                    b.get("text", "")
                    for b in content
                    if isinstance(b, dict) and b.get("type") == "text" and b.get("text")
                ]
                preview = " ".join(text_parts)[:500]
                if preview:
                    events.append(
                        MessageEvent(
                            role="user",
                            content_preview=preview,
                            turn_index=0,
                            session_id=session_id,
                            trace_id=session_id,
                            timestamp=ts,
                            source=self.source_tag,
                        )
                    )

        # ── Tool results ──────────────────────────────────────────────────
        if not isinstance(content, list):
            return events

        for block in content:
            if not isinstance(block, dict) or block.get("type") != "tool_result":
                continue
            tool_id: str = block.get("tool_use_id", "")
            pending = self._pending.pop(tool_id, None)
            if pending is None:
                # Watcher started mid-session — no matching tool_use buffered.
                continue

            is_error: bool = bool(block.get("is_error", False))
            result_text = _extract_result_text(block.get("content", ""))
            start_ts: datetime = pending["ts"]
            latency_ms = max(0.0, (ts - start_ts).total_seconds() * 1000)

            raw_input: dict[str, Any] = pending["input"]
            sanitised_input = _sanitise(raw_input) if isinstance(raw_input, dict) else {}
            output_payload: dict[str, Any] = {"text": result_text} if result_text else {}

            event = ToolCallEvent(
                tool_name=pending["name"],
                status=ToolCallStatus.FAILURE if is_error else ToolCallStatus.SUCCESS,
                failure_type=FailureType.UNKNOWN if is_error else None,
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
            events.append(event)

        return events

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
