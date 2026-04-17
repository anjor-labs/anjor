"""AntiGravityTranscriptWatcher — REMOVED from default registry.

AntiGravity is a code editor (VS Code fork), not an AI coding agent.
Its ~/.antigravity directory contains IDE extensions and configuration,
not AI session transcripts. There are no JSONL files to watch.

This class is kept to avoid breaking any code that imports it directly,
but it will never produce events and is not registered in WATCHER_REGISTRY.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import structlog

from anjor.core.events.base import BaseEvent
from anjor.watchers.base import BaseTranscriptWatcher

logger = structlog.get_logger(__name__)


class AntiGravityTranscriptWatcher(BaseTranscriptWatcher):
    provider_name = "AntiGravity"
    source_tag = "antigravity"

    def __init__(self, **kwargs: Any) -> None:
        super().__init__(**kwargs)
        logger.warning(
            "antigravity_watcher_not_available",
            reason="AntiGravity is an IDE, not an AI coding agent — no session transcripts exist",
        )

    def default_paths(self) -> list[str]:
        if sys.platform == "win32":
            appdata = os.environ.get("APPDATA", "")
            return [str(Path(appdata) / "AntiGravity" / "**" / "*.jsonl")]
        return [str(Path.home() / ".antigravity" / "**" / "*.jsonl")]

    def parse_line(self, line: str) -> list[BaseEvent] | None:
        return None
