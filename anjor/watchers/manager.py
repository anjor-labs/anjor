"""WatcherManager — runs multiple provider watchers concurrently.

Single entry point for all transcript watching. Each provider runs in its
own daemon thread managed by its BaseTranscriptWatcher instance.
"""

from __future__ import annotations

import structlog

from anjor.watchers.base import BaseTranscriptWatcher
from anjor.watchers.registry import build_active_watchers

logger = structlog.get_logger(__name__)


class WatcherManager:
    """Starts and stops all active transcript watchers.

    Usage:
        manager = WatcherManager()
        manager.start()                         # auto-detect providers
        manager.start(providers=["claude"])     # explicit providers
        manager.active_providers()              # ["claude_code"]
        manager.stop()
    """

    def __init__(
        self,
        collector_url: str = "http://localhost:7843",
        poll_interval: float = 2.0,
        project: str = "",
    ) -> None:
        self._collector_url = collector_url
        self._poll_interval = poll_interval
        self._project = project
        self._watchers: list[BaseTranscriptWatcher] = []

    def start(self, providers: list[str] | None = None) -> None:
        """Build and start watchers. Auto-detects providers when providers=None."""
        self._watchers = build_active_watchers(
            providers, self._collector_url, self._poll_interval, self._project
        )
        if not self._watchers:
            logger.info("anjor_no_transcript_paths_found")
            print("anjor: no AI coding agent transcript paths found on this machine")
            return
        for watcher in self._watchers:
            watcher.start()

    def stop(self) -> None:
        """Stop all running watchers. Blocks until each thread joins."""
        for watcher in self._watchers:
            watcher.stop()
        self._watchers = []

    def active_providers(self) -> list[str]:
        """Return the source_tag of each currently running watcher."""
        return [w.source_tag for w in self._watchers if w.is_running]
