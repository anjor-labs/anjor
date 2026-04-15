"""Watcher registry — maps provider keys to watcher classes.

To add a new provider: create its watcher class and add it here.
See docs/adding-a-watcher.md for the full guide.
"""

from __future__ import annotations

import glob

import structlog

from anjor.watchers.antigravity import AntiGravityTranscriptWatcher
from anjor.watchers.base import BaseTranscriptWatcher
from anjor.watchers.claude import ClaudeTranscriptWatcher
from anjor.watchers.codex import CodexTranscriptWatcher
from anjor.watchers.gemini import GeminiTranscriptWatcher

logger = structlog.get_logger(__name__)

WATCHER_REGISTRY: dict[str, type[BaseTranscriptWatcher]] = {
    "claude": ClaudeTranscriptWatcher,
    "gemini": GeminiTranscriptWatcher,
    "codex": CodexTranscriptWatcher,
    "antigravity": AntiGravityTranscriptWatcher,
}


def build_active_watchers(
    providers: list[str] | None = None,
    collector_url: str = "http://localhost:7843",
) -> list[BaseTranscriptWatcher]:
    """Build watcher instances for the specified (or auto-detected) providers.

    providers=None  → auto-detect: check which default_paths() glob patterns
                      match existing files on the current machine.
    providers=[...] → use exactly those keys; log WARNING + skip unknown keys.

    Returns [] (never raises) if nothing is found.
    """
    if providers is not None:
        result: list[BaseTranscriptWatcher] = []
        for key in providers:
            cls = WATCHER_REGISTRY.get(key)
            if cls is None:
                logger.warning("unknown_watcher_provider", key=key)
                continue
            result.append(cls(collector_url=collector_url))
        return result

    # Auto-detect: check which providers have transcript files present.
    detected: list[BaseTranscriptWatcher] = []
    for cls in WATCHER_REGISTRY.values():
        instance = cls(collector_url=collector_url)
        if any(glob.glob(p, recursive=True) for p in instance.default_paths()):
            detected.append(instance)
    return detected
