from unittest.mock import patch

from anjor.watchers.claude import ClaudeTranscriptWatcher
from anjor.watchers.registry import WATCHER_REGISTRY, build_active_watchers


def test_registry_contains_providers():
    assert "claude" in WATCHER_REGISTRY
    assert "gemini" in WATCHER_REGISTRY
    assert "codex" in WATCHER_REGISTRY
    assert "antigravity" in WATCHER_REGISTRY


def test_build_explicit_providers():
    watchers = build_active_watchers(["claude"])
    assert len(watchers) == 1
    assert isinstance(watchers[0], ClaudeTranscriptWatcher)


def test_build_empty_providers():
    watchers = build_active_watchers([])
    assert watchers == []


def test_build_unknown_provider():
    watchers = build_active_watchers(["xyz"])
    assert watchers == []


@patch("glob.glob")
def test_build_auto_detect_none(mock_glob):
    mock_glob.return_value = []
    watchers = build_active_watchers(None)
    assert watchers == []


@patch("glob.glob")
def test_build_auto_detect_claude(mock_glob):
    def side_effect(path, **kwargs):
        return ["/fake/path"] if "claude" in path.lower() or "code" in path.lower() else []

    mock_glob.side_effect = side_effect
    watchers = build_active_watchers(None)

    # Assume the side effect matched at least Claude
    assert len(watchers) > 0
    assert any(isinstance(w, ClaudeTranscriptWatcher) for w in watchers)
