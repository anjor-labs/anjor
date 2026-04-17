"""Unit tests for CodexTranscriptWatcher."""

from __future__ import annotations

import json
from datetime import UTC, datetime

from anjor.core.events.llm_call import LLMCallEvent
from anjor.core.events.tool_call import ToolCallEvent, ToolCallStatus
from anjor.watchers.codex import (
    CodexTranscriptWatcher,
    _exit_code_from_output,
    _session_id_from_path,
)


def _w() -> CodexTranscriptWatcher:
    return CodexTranscriptWatcher(collector_url="http://localhost:7843")


def _line(**kwargs) -> str:  # type: ignore[return]
    base = {"timestamp": "2026-03-15T03:00:00.000Z", "type": "unknown", "payload": {}}
    base.update(kwargs)
    return json.dumps(base)


def _ts(s: str = "2026-03-15T03:00:00.000Z") -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


class TestHelpers:
    def test_exit_code_zero(self) -> None:
        out = "Chunk ID: abc\nWall time: 0.001 seconds\nProcess exited with code 0\nOutput:\n"
        assert _exit_code_from_output(out) == 0

    def test_exit_code_nonzero(self) -> None:
        out = "Process exited with code 1\nOutput:\ncommand not found"
        assert _exit_code_from_output(out) == 1

    def test_exit_code_missing(self) -> None:
        assert _exit_code_from_output("no exit code here") == 0

    def test_session_id_from_path(self) -> None:
        path = "/home/user/.codex/sessions/2026/03/15/rollout-2026-03-15T03-12-46-019cee4d-4141-7a90-a69f-7f2a678a9229.jsonl"
        sid = _session_id_from_path(path)
        assert sid == "019cee4d-4141-7a90-a69f-7f2a678a9229"

    def test_session_id_from_path_no_uuid(self) -> None:
        # Should return a generated UUID (not empty) when no UUID in filename
        sid = _session_id_from_path("/some/path/session.jsonl")
        assert len(sid) > 0


class TestCodexWatcherMetadata:
    def test_provider_name(self) -> None:
        assert _w().provider_name == "OpenAI Codex"

    def test_source_tag(self) -> None:
        assert _w().source_tag == "openai_codex"

    def test_default_paths(self) -> None:
        paths = _w().default_paths()
        assert len(paths) == 1
        assert "codex" in paths[0].lower()
        assert "*.jsonl" in paths[0]

    def test_session_meta_sets_session_id(self) -> None:
        w = _w()
        line = _line(
            type="session_meta",
            payload={"id": "test-session-uuid-1234", "cwd": "/tmp"},
        )
        result = w.parse_line(line)
        assert result is None
        assert w._current_session_id == "test-session-uuid-1234"

    def test_turn_context_sets_model(self) -> None:
        w = _w()
        line = _line(
            type="turn_context",
            payload={"model": "gpt-5.3-codex", "turn_id": "abc", "model_context_window": None},
        )
        w.parse_line(line)
        assert w._current_model == "gpt-5.3-codex"

    def test_task_started_sets_context_window(self) -> None:
        w = _w()
        line = _line(
            type="event_msg",
            payload={"type": "task_started", "model_context_window": 258400},
        )
        w.parse_line(line)
        assert w._current_context_window == 258400

    def test_unknown_line_types_return_none(self) -> None:
        w = _w()
        assert w.parse_line(_line(type="response_item", payload={"type": "summary"})) is None
        assert w.parse_line(_line(type="event_msg", payload={"type": "turn_id"})) is None
        assert w.parse_line("not json") is None

    def test_project_from_path_sets_session_id(self) -> None:
        w = _w()
        path = "/home/user/.codex/sessions/2026/03/15/rollout-2026-03-15T03-12-46-aabbccdd-1234-5678-9abc-def012345678.jsonl"
        w._project_from_path(path)
        assert w._current_session_id == "aabbccdd-1234-5678-9abc-def012345678"


class TestCodexToolCallEvents:
    def _setup(self, w: CodexTranscriptWatcher) -> None:
        w._current_session_id = "session-abc"
        w._current_model = "gpt-5.3-codex"

    def test_function_call_buffered(self) -> None:
        w = _w()
        self._setup(w)
        line = _line(
            type="response_item",
            payload={
                "type": "function_call",
                "name": "exec_command",
                "arguments": '{"cmd": "ls"}',
                "call_id": "call_123",
            },
        )
        events = w.parse_line(line)
        assert events == []
        assert "call_123" in w._pending
        assert w._pending["call_123"]["name"] == "exec_command"

    def test_function_call_output_emits_tool_event(self) -> None:
        w = _w()
        self._setup(w)
        call_id = "call_abc"

        call_line = _line(
            timestamp="2026-03-15T03:00:00.000Z",
            type="response_item",
            payload={
                "type": "function_call",
                "name": "exec_command",
                "arguments": '{"cmd": "ls -la"}',
                "call_id": call_id,
            },
        )
        result_line = _line(
            timestamp="2026-03-15T03:00:01.000Z",  # 1 second later
            type="response_item",
            payload={
                "type": "function_call_output",
                "call_id": call_id,
                "output": "Chunk ID: abc\nWall time: 1.0 seconds\nProcess exited with code 0\nOutput:\nfile.txt\n",
            },
        )

        w.parse_line(call_line)
        events = w.parse_line(result_line) or []

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, ToolCallEvent)
        assert event.tool_name == "exec_command"
        assert event.status == ToolCallStatus.SUCCESS
        assert event.failure_type is None
        assert event.latency_ms == pytest.approx(1000.0, abs=5.0)
        assert event.source == "openai_codex"
        assert event.trace_id == "session-abc"
        assert "cmd" in event.input_payload

    def test_function_call_failure_detected(self) -> None:
        w = _w()
        self._setup(w)
        call_id = "call_fail"

        w.parse_line(
            _line(
                type="response_item",
                payload={
                    "type": "function_call",
                    "name": "exec_command",
                    "arguments": '{"cmd": "bad_command"}',
                    "call_id": call_id,
                },
            )
        )
        events = (
            w.parse_line(
                _line(
                    type="response_item",
                    payload={
                        "type": "function_call_output",
                        "call_id": call_id,
                        "output": "Process exited with code 127\nOutput:\nbad_command: command not found",
                    },
                )
            )
            or []
        )

        assert len(events) == 1
        assert events[0].status == ToolCallStatus.FAILURE
        assert events[0].failure_type is not None

    def test_orphan_output_ignored(self) -> None:
        w = _w()
        self._setup(w)
        events = w.parse_line(
            _line(
                type="response_item",
                payload={"type": "function_call_output", "call_id": "nonexistent", "output": "x"},
            )
        )
        assert events == [] or events is None

    def test_invalid_json_args_handled(self) -> None:
        w = _w()
        self._setup(w)
        call_id = "call_bad_args"
        w.parse_line(
            _line(
                type="response_item",
                payload={
                    "type": "function_call",
                    "name": "tool",
                    "arguments": "not-valid-json",
                    "call_id": call_id,
                },
            )
        )
        assert call_id in w._pending
        assert "raw" in w._pending[call_id]["input"]


class TestCodexLLMEvents:
    def _setup(self, w: CodexTranscriptWatcher) -> None:
        w._current_session_id = "session-abc"
        w._current_model = "gpt-5.3-codex"
        w._current_context_window = 128000

    def test_token_count_emits_llm_event(self) -> None:
        w = _w()
        self._setup(w)
        line = _line(
            type="event_msg",
            payload={
                "type": "token_count",
                "info": {
                    "last_token_usage": {
                        "input_tokens": 16960,
                        "cached_input_tokens": 9088,
                        "output_tokens": 46,
                        "reasoning_output_tokens": 0,
                    }
                },
                "rate_limits": {},
            },
        )
        events = w.parse_line(line) or []

        assert len(events) == 1
        event = events[0]
        assert isinstance(event, LLMCallEvent)
        assert event.model == "gpt-5.3-codex"
        assert event.token_usage is not None
        assert event.token_usage.input == 16960
        assert event.token_usage.output == 46
        assert event.token_usage.cache_read == 9088
        assert event.source == "openai_codex"
        assert event.context_window_limit == 128000

    def test_token_count_null_info_skipped(self) -> None:
        w = _w()
        self._setup(w)
        line = _line(
            type="event_msg",
            payload={"type": "token_count", "info": None, "rate_limits": {}},
        )
        events = w.parse_line(line) or []
        assert events == []

    def test_token_count_zero_tokens_skipped(self) -> None:
        w = _w()
        self._setup(w)
        line = _line(
            type="event_msg",
            payload={
                "type": "token_count",
                "info": {"last_token_usage": {"input_tokens": 0, "output_tokens": 0}},
            },
        )
        events = w.parse_line(line) or []
        assert events == []

    def test_no_model_skips_llm_event(self) -> None:
        w = _w()
        w._current_session_id = "session-abc"
        w._current_model = ""  # no model set yet
        line = _line(
            type="event_msg",
            payload={
                "type": "token_count",
                "info": {"last_token_usage": {"input_tokens": 100, "output_tokens": 10}},
            },
        )
        events = w.parse_line(line) or []
        assert events == []


class TestCodexGC:
    def test_gc_removes_stale_pending(self) -> None:
        w = _w()
        w._current_session_id = "s"
        from datetime import timedelta

        stale_ts = datetime.now(UTC) - timedelta(seconds=120)
        w._pending["old_call"] = {
            "name": "tool",
            "input": {},
            "ts": stale_ts,
            "session_id": "s",
        }
        w._gc_pending()
        assert "old_call" not in w._pending

    def test_gc_keeps_recent_pending(self) -> None:
        w = _w()
        w._current_session_id = "s"
        w._pending["new_call"] = {
            "name": "tool",
            "input": {},
            "ts": datetime.now(UTC),
            "session_id": "s",
        }
        w._gc_pending()
        assert "new_call" in w._pending


# pytest.approx needed for latency assertions
import pytest  # noqa: E402
