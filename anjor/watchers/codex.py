"""CodexTranscriptWatcher — transcript watcher for OpenAI Codex sessions.

Format TBD — implement parse_line() when format is confirmed.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import structlog

from anjor.core.events.base import BaseEvent
from anjor.watchers.base import BaseTranscriptWatcher

logger = structlog.get_logger(__name__)


class CodexTranscriptWatcher(BaseTranscriptWatcher):
    provider_name = "OpenAI Codex"
    source_tag = "openai_codex"

    def default_paths(self) -> list[str]:
        # PATH UNCONFIRMED — verify against actual install before 0.8.0 release
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            return [str(Path(appdata) / "Codex" / "sessions" / "**" / "*.jsonl")]
        return [str(Path.home() / ".codex" / "sessions" / "**" / "*.jsonl")]

    def parse_line(self, line: str) -> list[BaseEvent] | None:
        logger.debug("codex_transcript_parse_not_implemented", line_preview=line[:80])
        return None
