"""BaseTranscriptWatcher — ABC for all AI coding agent transcript watchers.

Subclasses implement three provider-specific methods: default_paths(),
parse_line(), provider_name, source_tag. Everything else — file discovery,
tailing, byte-offset state, state persistence, HTTP event posting, and
error handling — is implemented here once and shared by all providers.

Threading model
---------------
Each watcher runs in a single daemon thread started by start(). The thread
polls default_paths() every poll_interval seconds, reads any new bytes from
each matched file, and calls parse_line() on each new line.

State persistence
-----------------
Byte offsets per file are persisted to ~/.anjor/watcher_offsets.json so
that watcher restarts do not re-emit historical events.

parse_line() contract
---------------------
Called on the SAME instance for consecutive lines from the same file, in
file order. Concrete classes MAY keep instance state between calls (e.g.
ClaudeTranscriptWatcher buffers tool_use blocks and completes them when a
matching tool_result arrives). The base class guarantees call ordering.

parse_line() MUST NEVER RAISE. The base class wraps every call in
try/except and logs + swallows any exception.
"""

from __future__ import annotations

import glob
import json
import threading
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any, ClassVar

import httpx
import structlog

from anjor.core.events.base import BaseEvent

logger = structlog.get_logger(__name__)

_DEFAULT_OFFSETS_PATH = Path.home() / ".anjor" / "watcher_offsets.json"


class BaseTranscriptWatcher(ABC):
    # Overridable in tests to avoid writing to the real home directory.
    _OFFSETS_PATH: ClassVar[Path] = _DEFAULT_OFFSETS_PATH

    def __init__(
        self,
        collector_url: str = "http://localhost:7843",
        poll_interval: float = 2.0,
        project: str = "",
    ) -> None:
        self._collector_url = collector_url.rstrip("/")
        self._poll_interval = poll_interval
        self._project = project
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._offsets: dict[str, int] = {}
        self._client = httpx.Client(timeout=5.0)

    # ── Project extraction ─────────────────────────────────────────────────

    def _project_from_path(self, path: str) -> str:
        """Extract a project name from a transcript file path.

        Returns "" by default (no project). Subclasses override for providers
        whose path encodes the working directory (e.g. Claude Code).
        """
        return ""

    # ── Abstract interface ─────────────────────────────────────────────────

    @abstractmethod
    def default_paths(self) -> list[str]:
        """Glob patterns for transcript files. Patterns may not match anything
        on the current machine — handled gracefully."""

    @abstractmethod
    def parse_line(self, line: str) -> list[BaseEvent] | None:
        """Parse one non-empty JSONL line into zero or more events.

        Return None or [] if the line is not relevant.
        MUST NEVER RAISE — all exceptions are caught by _safe_parse_line().
        """

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Human-readable provider name, e.g. 'Claude Code'."""

    @property
    @abstractmethod
    def source_tag(self) -> str:
        """Short tag stored on emitted events, e.g. 'claude_code'."""

    # ── Lifecycle ──────────────────────────────────────────────────────────

    def start(self) -> None:
        """Start the background polling thread. Idempotent."""
        if self._thread is not None and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._load_offsets()
        self._thread = threading.Thread(
            target=self._run,
            name=f"anjor-watcher-{self.source_tag}",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "transcript_watcher_started",
            provider=self.provider_name,
            paths=self.default_paths(),
        )

    def stop(self, timeout: float = 5.0) -> None:
        """Signal stop, join thread, persist final offsets. Idempotent."""
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        self._save_offsets()
        try:
            self._client.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("watcher_client_close_error", error=str(exc))

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    # ── Private: polling loop ──────────────────────────────────────────────

    def _run(self) -> None:
        """Thread main: scan → sleep → repeat until stop_event is set."""
        while not self._stop_event.is_set():
            try:
                self._scan()
                self._save_offsets()
            except Exception as exc:
                logger.warning(
                    "watcher_scan_error",
                    provider=self.provider_name,
                    error=str(exc),
                )
            self._stop_event.wait(timeout=self._poll_interval)

    def _scan(self) -> None:
        """Glob all default_paths() and tail each matched file."""
        for pattern in self.default_paths():
            for filepath in glob.glob(pattern, recursive=True):
                self._tail(filepath)

    def _tail(self, path: str) -> None:
        """Read new lines from path since last recorded byte offset."""
        # Resolve project once per file: explicit override wins, else auto-detect.
        project = self._project or self._project_from_path(path)
        offset = self._offsets.get(path, 0)
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                fh.seek(offset)
                for raw_line in fh:
                    line = raw_line.strip()
                    if line:
                        events = self._safe_parse_line(line)
                        if events:
                            if project:
                                events = [e.model_copy(update={"project": project}) for e in events]
                            self._post_events(events)
                self._offsets[path] = fh.tell()
        except FileNotFoundError:
            pass  # file deleted between glob and open — benign
        except PermissionError:
            logger.warning("watcher_permission_error", path=path)
        except OSError as exc:
            logger.warning("watcher_io_error", path=path, error=str(exc))

    def _safe_parse_line(self, line: str) -> list[BaseEvent]:
        """Call parse_line(), catching and logging any exception."""
        try:
            result = self.parse_line(line)
            return result or []
        except Exception as exc:
            logger.warning(
                "parse_line_error",
                provider=self.provider_name,
                error=str(exc),
                line_preview=line[:120],
            )
            return []

    def _post_events(self, events: list[BaseEvent]) -> None:
        """POST each event to the collector. Logs on failure, never raises."""
        for event in events:
            try:
                self._client.post(
                    f"{self._collector_url}/events",
                    json=event.model_dump(mode="json"),
                )
            except Exception as exc:
                logger.warning(
                    "watcher_post_error",
                    provider=self.provider_name,
                    error=str(exc),
                )

    # ── State persistence ──────────────────────────────────────────────────

    def _load_offsets(self) -> None:
        """Load byte offsets from the shared state file."""
        try:
            if self._OFFSETS_PATH.exists():
                data: dict[str, Any] = json.loads(self._OFFSETS_PATH.read_text())
                for path, offset in data.items():
                    if isinstance(offset, int):
                        self._offsets[path] = offset
        except Exception as exc:
            logger.debug("watcher_offsets_load_error", error=str(exc))

    def _save_offsets(self) -> None:
        """Merge our offsets into the shared state file and write it."""
        try:
            self._OFFSETS_PATH.parent.mkdir(parents=True, exist_ok=True)
            existing: dict[str, Any] = {}
            if self._OFFSETS_PATH.exists():
                try:
                    existing = json.loads(self._OFFSETS_PATH.read_text())
                except Exception as exc:  # noqa: BLE001
                    logger.debug("watcher_offsets_read_error", error=str(exc))
            existing.update(self._offsets)
            self._OFFSETS_PATH.write_text(json.dumps(existing, indent=2))
        except Exception as exc:
            logger.debug("watcher_offsets_save_error", error=str(exc))
