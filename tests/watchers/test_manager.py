from unittest.mock import patch

from anjor.watchers.claude import ClaudeTranscriptWatcher
from anjor.watchers.manager import WatcherManager


def test_manager_start_no_paths():
    manager = WatcherManager()
    with patch("anjor.watchers.manager.build_active_watchers", return_value=[]):
        manager.start()

    assert manager.active_providers() == []


@patch("anjor.watchers.registry.build_active_watchers")
def test_manager_start_and_stop(mock_build):
    watcher_mock = ClaudeTranscriptWatcher()
    watcher_mock.start = lambda: None
    watcher_mock.stop = lambda: None
    watcher_mock._is_running = True

    mock_build.return_value = [watcher_mock]
    manager = WatcherManager()
    manager.start(["claude"])

    assert "claude_code" in manager.active_providers()
    manager.stop()
    assert manager.active_providers() == []


@patch("anjor.watchers.registry.build_active_watchers")
def test_manager_stop_idempotent(mock_build):
    watcher_mock = ClaudeTranscriptWatcher()
    watcher_mock.start = lambda: None
    watcher_mock.stop = lambda: None
    watcher_mock._is_running = True

    mock_build.return_value = [watcher_mock]
    manager = WatcherManager()
    manager.start(["claude"])
    manager.stop()
    manager.stop()
