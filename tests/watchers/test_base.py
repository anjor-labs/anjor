import json
from datetime import UTC, datetime
from unittest.mock import patch

from anjor.core.events.tool_call import ToolCallEvent, ToolCallStatus
from anjor.watchers.base import BaseTranscriptWatcher


class _SimpleWatcher(BaseTranscriptWatcher):
    provider_name = "Simple"
    source_tag = "simple"

    def default_paths(self):
        return ["*.jsonl"]

    def parse_line(self, line: str):
        try:
            json.loads(line)
            return [
                ToolCallEvent(
                    tool_name="test",
                    status=ToolCallStatus.SUCCESS,
                    trace_id="1",
                    session_id="1",
                    timestamp=datetime.now(UTC),
                    latency_ms=0.0,
                )
            ]
        except Exception:
            return None


def test_start_and_stop():
    w = _SimpleWatcher()
    assert not w.is_running
    w.start()
    assert w.is_running
    w.stop()
    assert not w.is_running


def test_stop_idempotent():
    w = _SimpleWatcher()
    w.start()
    w.stop()
    w.stop()
    assert not w.is_running


def test_start_idempotent():
    w = _SimpleWatcher()
    w.start()
    w.start()
    assert w.is_running
    w.stop()


@patch("anjor.watchers.base.httpx.Client.post")
def test_new_lines_picked_up(mock_post, tmp_path, monkeypatch):
    monkeypatch.setattr(BaseTranscriptWatcher, "_OFFSETS_PATH", tmp_path / "offsets.json")

    # Create temp file
    tf = tmp_path / "test.jsonl"
    tf.write_text('{"a":1}\n{"b":2}\n')

    w = _SimpleWatcher()
    w.default_paths = lambda: [str(tf)]
    w.start()

    # Wait a bit or explicitly call _tail() if we want to run synchronously
    w.stop()

    # Since start() creates a thread, it's racy in tests.
    # Let's test the synchronous methods instead.
    w._tail(str(tf))
    assert mock_post.call_count >= 2


def test_safe_parse_line_swallows_exception():
    class _BrokenWatcher(_SimpleWatcher):
        def parse_line(self, line):
            raise ValueError("broken")

    w = _BrokenWatcher()
    # Should not raise exception
    assert w._safe_parse_line("abc") == []


@patch("anjor.watchers.base.httpx.Client.post")
def test_byte_offsets(mock_post, tmp_path, monkeypatch):
    offset_file = tmp_path / "offsets.json"
    monkeypatch.setattr(BaseTranscriptWatcher, "_OFFSETS_PATH", offset_file)

    tf = tmp_path / "test.jsonl"
    tf.write_text('{"a":1}\n{"b":2}\n{"c":3}\n')

    w = _SimpleWatcher()
    w.default_paths = lambda: [str(tf)]

    # Read first 3 lines
    w._tail(str(tf))
    assert mock_post.call_count == 3

    # Appending 1 line
    tf.write_text('{"a":1}\n{"b":2}\n{"c":3}\n{"d":4}\n')
    mock_post.reset_mock()

    # Second poll should read only 1 line
    w._tail(str(tf))
    assert mock_post.call_count == 1


def test_missing_file_skipped():
    w = _SimpleWatcher()
    w.default_paths = lambda: ["/tmp/nonexistent_xyz_123.jsonl"]
    w._tail("/tmp/nonexistent_xyz_123.jsonl")  # should not raise


def test_save_load_offsets(tmp_path, monkeypatch):
    offset_file = tmp_path / "offsets.json"
    monkeypatch.setattr(BaseTranscriptWatcher, "_OFFSETS_PATH", offset_file)

    w1 = _SimpleWatcher()
    w1._offsets["/a/b"] = 123
    w1._save_offsets()

    w2 = _SimpleWatcher()
    w2._load_offsets()
    assert w2._offsets.get("/a/b") == 123
