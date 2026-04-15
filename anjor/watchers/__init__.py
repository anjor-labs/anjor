"""Provider-agnostic transcript watcher package.

Watches local session files written by AI coding agents (Claude Code,
Gemini CLI, OpenAI Codex, etc.) and emits LLMCallEvents and ToolCallEvents
into the anjor EventPipeline.

Usage:
    from anjor.watchers import WatcherManager
    manager = WatcherManager()
    manager.start()          # auto-detect installed providers
    # ... later ...
    manager.stop()

Or with explicit providers:
    manager.start(providers=["claude", "gemini"])
"""

from anjor.watchers.manager import WatcherManager
from anjor.watchers.registry import build_active_watchers

__all__ = ["WatcherManager", "build_active_watchers"]
