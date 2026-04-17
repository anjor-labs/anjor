"""Tests for GeminiTranscriptWatcher — full JSON session file format."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

from anjor.watchers.gemini import GeminiTranscriptWatcher


FIXTURE = Path(__file__).parent / "fixtures" / "gemini_session.json"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _watcher(tmp_path: Path) -> GeminiTranscriptWatcher:
    w = GeminiTranscriptWatcher(collector_url="http://localhost:9999")
    w._OFFSETS_PATH = tmp_path / "offsets.json"  # type: ignore[attr-defined]
    return w


def _make_session(messages: list[dict]) -> dict:
    return {
        "sessionId": "test-sess-1",
        "messages": messages,
    }


def _gemini_msg(
    msg_id: str = "msg-1",
    model: str = "gemini-2.0-flash",
    tokens: dict | None = None,
    tool_calls: list | None = None,
    ts: str = "2026-04-15T10:00:00.000Z",
) -> dict:
    return {
        "id": msg_id,
        "type": "gemini",
        "timestamp": ts,
        "content": "",
        "model": model,
        "tokens": tokens
        or {"input": 100, "output": 50, "cached": 0, "thoughts": 0, "tool": 0, "total": 150},
        "toolCalls": tool_calls or [],
    }


def _tool_call_entry(
    tc_id: str = "tc-1",
    name: str = "list_directory",
    args: dict | None = None,
    status: str = "success",
    output: str = "file.txt",
) -> dict:
    return {
        "id": tc_id,
        "name": name,
        "args": args or {"path": "."},
        "result": [
            {"functionResponse": {"id": tc_id, "name": name, "response": {"output": output}}}
        ],
        "status": status,
        "timestamp": "2026-04-15T10:00:01.500Z",
    }


# ---------------------------------------------------------------------------
# Core parsing tests
# ---------------------------------------------------------------------------


class TestGeminiWatcherBasics:
    def test_provider_name(self, tmp_path: Path) -> None:
        w = _watcher(tmp_path)
        assert w.provider_name == "Gemini CLI"

    def test_source_tag(self, tmp_path: Path) -> None:
        w = _watcher(tmp_path)
        assert w.source_tag == "gemini_cli"

    def test_default_paths_non_empty(self, tmp_path: Path) -> None:
        w = _watcher(tmp_path)
        paths = w.default_paths()
        assert isinstance(paths, list)
        assert len(paths) >= 1
        assert all(".gemini" in p or "Gemini" in p for p in paths)

    def test_parse_line_returns_none(self, tmp_path: Path) -> None:
        w = _watcher(tmp_path)
        assert w.parse_line('{"x": 1}') is None


# ---------------------------------------------------------------------------
# _tail() tests
# ---------------------------------------------------------------------------


class TestGeminiTail:
    def _run_tail(self, tmp_path: Path, session_data: dict) -> list:
        """Write session JSON, run _tail(), capture events posted."""
        w = _watcher(tmp_path)
        session_file = tmp_path / "chat.json"
        session_file.write_text(json.dumps(session_data), encoding="utf-8")

        posted: list = []

        def fake_post(url: str, json: dict, **kwargs) -> None:  # noqa: A002
            posted.append(json)

        with patch.object(w._client, "post", side_effect=fake_post):
            w._tail(str(session_file))

        return posted

    def test_llm_event_emitted_for_gemini_message(self, tmp_path: Path) -> None:
        session = _make_session([_gemini_msg()])
        posted = self._run_tail(tmp_path, session)
        assert len(posted) == 1
        assert posted[0]["event_type"] == "llm_call"

    def test_llm_event_model_set(self, tmp_path: Path) -> None:
        session = _make_session([_gemini_msg(model="gemini-2.0-flash")])
        posted = self._run_tail(tmp_path, session)
        assert posted[0]["model"] == "gemini-2.0-flash"

    def test_llm_event_source_tag(self, tmp_path: Path) -> None:
        session = _make_session([_gemini_msg()])
        posted = self._run_tail(tmp_path, session)
        assert posted[0]["source"] == "gemini_cli"

    def test_llm_event_token_counts(self, tmp_path: Path) -> None:
        tokens = {
            "input": 500,
            "output": 80,
            "cached": 100,
            "thoughts": 10,
            "tool": 0,
            "total": 690,
        }
        session = _make_session([_gemini_msg(tokens=tokens)])
        posted = self._run_tail(tmp_path, session)
        usage = posted[0]["token_usage"]
        assert usage["input"] == 500
        assert usage["output"] == 80
        assert usage["cache_read"] == 100

    def test_llm_event_session_and_trace_id(self, tmp_path: Path) -> None:
        session = _make_session([_gemini_msg()])
        session["sessionId"] = "my-session"
        posted = self._run_tail(tmp_path, session)
        assert posted[0]["trace_id"] == "my-session"
        assert posted[0]["session_id"] == "my-session"

    def test_tool_call_event_emitted(self, tmp_path: Path) -> None:
        tc = _tool_call_entry()
        session = _make_session([_gemini_msg(tool_calls=[tc])])
        posted = self._run_tail(tmp_path, session)
        # 1 LLM event + 1 tool call event
        assert len(posted) == 2
        tool_events = [p for p in posted if p["event_type"] == "tool_call"]
        assert len(tool_events) == 1

    def test_tool_call_event_name_prefixed(self, tmp_path: Path) -> None:
        tc = _tool_call_entry(name="run_shell")
        session = _make_session([_gemini_msg(tool_calls=[tc])])
        posted = self._run_tail(tmp_path, session)
        tool_events = [p for p in posted if p["event_type"] == "tool_call"]
        assert tool_events[0]["tool_name"] == "gemini__run_shell"

    def test_tool_call_error_status(self, tmp_path: Path) -> None:
        tc = _tool_call_entry(status="error")
        session = _make_session([_gemini_msg(tool_calls=[tc])])
        posted = self._run_tail(tmp_path, session)
        tool_events = [p for p in posted if p["event_type"] == "tool_call"]
        assert tool_events[0]["status"] == "failure"

    def test_tool_call_success_status(self, tmp_path: Path) -> None:
        tc = _tool_call_entry(status="success")
        session = _make_session([_gemini_msg(tool_calls=[tc])])
        posted = self._run_tail(tmp_path, session)
        tool_events = [p for p in posted if p["event_type"] == "tool_call"]
        assert tool_events[0]["status"] == "success"

    def test_tool_call_output_extracted(self, tmp_path: Path) -> None:
        tc = _tool_call_entry(output="file1.py\nfile2.py")
        session = _make_session([_gemini_msg(tool_calls=[tc])])
        posted = self._run_tail(tmp_path, session)
        tool_events = [p for p in posted if p["event_type"] == "tool_call"]
        assert "file1.py" in tool_events[0]["output_payload"]["text"]

    def test_two_tool_calls_in_one_message(self, tmp_path: Path) -> None:
        tc1 = _tool_call_entry(tc_id="tc-1", name="read_file")
        tc2 = _tool_call_entry(tc_id="tc-2", name="write_file")
        session = _make_session([_gemini_msg(tool_calls=[tc1, tc2])])
        posted = self._run_tail(tmp_path, session)
        tool_events = [p for p in posted if p["event_type"] == "tool_call"]
        assert len(tool_events) == 2

    def test_user_and_info_messages_skipped(self, tmp_path: Path) -> None:
        session = _make_session(
            [
                {
                    "id": "u1",
                    "type": "user",
                    "timestamp": "2026-04-15T10:00:00Z",
                    "content": [{"text": "hi"}],
                },
                {
                    "id": "i1",
                    "type": "info",
                    "timestamp": "2026-04-15T10:00:01Z",
                    "content": "info",
                },
            ]
        )
        posted = self._run_tail(tmp_path, session)
        assert posted == []

    def test_zero_token_gemini_message_skipped(self, tmp_path: Path) -> None:
        tokens = {"input": 0, "output": 0, "cached": 0, "thoughts": 0, "tool": 0, "total": 0}
        session = _make_session([_gemini_msg(tokens=tokens)])
        posted = self._run_tail(tmp_path, session)
        assert posted == []

    def test_file_unchanged_skips_second_read(self, tmp_path: Path) -> None:
        w = _watcher(tmp_path)
        session_file = tmp_path / "chat.json"
        session_file.write_text(json.dumps(_make_session([_gemini_msg()])), encoding="utf-8")

        posted: list = []
        with patch.object(
            w._client, "post", side_effect=lambda url, json, **kw: posted.append(json)
        ):  # noqa: A002
            w._tail(str(session_file))
            w._tail(str(session_file))  # size unchanged — should not re-post

        assert len(posted) == 1

    def test_duplicate_msg_id_not_reemitted(self, tmp_path: Path) -> None:
        w = _watcher(tmp_path)
        session_file = tmp_path / "chat.json"
        data = _make_session([_gemini_msg(msg_id="dup-1")])
        session_file.write_text(json.dumps(data), encoding="utf-8")

        posted: list = []
        with patch.object(
            w._client, "post", side_effect=lambda url, json, **kw: posted.append(json)
        ):  # noqa: A002
            w._tail(str(session_file))
            # Simulate file growing (append whitespace to change size)
            session_file.write_text(json.dumps(data) + " ", encoding="utf-8")
            w._tail(str(session_file))

        # First call: 1 event. Second call: file changed but same message IDs → 0 new events.
        assert len(posted) == 1

    def test_missing_file_silently_skipped(self, tmp_path: Path) -> None:
        w = _watcher(tmp_path)
        w._tail(str(tmp_path / "nonexistent.json"))  # must not raise

    def test_invalid_json_silently_skipped(self, tmp_path: Path) -> None:
        w = _watcher(tmp_path)
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("{not valid json", encoding="utf-8")
        w._tail(str(bad_file))  # must not raise, offset not advanced

    def test_non_dict_json_silently_skipped(self, tmp_path: Path) -> None:
        w = _watcher(tmp_path)
        f = tmp_path / "list.json"
        f.write_text("[1, 2, 3]", encoding="utf-8")
        w._tail(str(f))  # must not raise


# ---------------------------------------------------------------------------
# Fixture integration test
# ---------------------------------------------------------------------------


class TestGeminiFixture:
    """Feed the realistic fixture through _tail() and verify expected counts."""

    def test_fixture_emits_correct_events(self, tmp_path: Path) -> None:
        assert FIXTURE.exists(), "gemini_session.json fixture missing"
        w = _watcher(tmp_path)

        posted: list = []
        with patch.object(
            w._client, "post", side_effect=lambda url, json, **kw: posted.append(json)
        ):  # noqa: A002
            w._tail(str(FIXTURE))

        llm_events = [p for p in posted if p["event_type"] == "llm_call"]
        tool_events = [p for p in posted if p["event_type"] == "tool_call"]

        # Fixture has 3 gemini messages, all with tokens > 0 → 3 LLM events
        assert len(llm_events) == 3, f"Expected 3 LLM events, got {len(llm_events)}"
        # Fixture has 1 success tool call + 1 error tool call → 2 tool events
        assert len(tool_events) == 2, f"Expected 2 tool events, got {len(tool_events)}"

        # Source tags
        assert all(e["source"] == "gemini_cli" for e in posted)

        # Tool names have gemini__ prefix
        names = {e["tool_name"] for e in tool_events}
        assert "gemini__list_directory" in names
        assert "gemini__run_command" in names

        # Error tool call
        err_events = [e for e in tool_events if e["status"] == "failure"]
        assert len(err_events) == 1


# ---------------------------------------------------------------------------
# Message capture tests (capture_messages=True)
# ---------------------------------------------------------------------------


def _watcher_capture(tmp_path: Path) -> GeminiTranscriptWatcher:
    w = GeminiTranscriptWatcher(collector_url="http://localhost:9999", capture_messages=True)
    w._OFFSETS_PATH = tmp_path / "offsets.json"  # type: ignore[attr-defined]
    return w


class TestGeminiMessageCapture:
    def _run_tail(self, tmp_path: Path, session_data: dict) -> list:
        w = _watcher_capture(tmp_path)
        session_file = tmp_path / "chat.json"
        session_file.write_text(json.dumps(session_data), encoding="utf-8")
        posted: list = []
        with patch.object(
            w._client, "post", side_effect=lambda url, json, **kw: posted.append(json)
        ):  # noqa: A002
            w._tail(str(session_file))
        return posted

    def test_user_message_captured(self, tmp_path: Path) -> None:
        session = _make_session(
            [
                {
                    "id": "u1",
                    "type": "user",
                    "timestamp": "2026-04-15T10:00:00Z",
                    "content": [{"text": "List files please"}],
                },
            ]
        )
        posted = self._run_tail(tmp_path, session)
        msg_events = [p for p in posted if p["event_type"] == "message"]
        assert len(msg_events) == 1
        assert msg_events[0]["role"] == "user"
        assert "List files" in msg_events[0]["content_preview"]

    def test_user_message_string_content(self, tmp_path: Path) -> None:
        session = _make_session(
            [
                {
                    "id": "u1",
                    "type": "user",
                    "timestamp": "2026-04-15T10:00:00Z",
                    "content": "Hello there",
                },
            ]
        )
        posted = self._run_tail(tmp_path, session)
        msg_events = [p for p in posted if p["event_type"] == "message"]
        assert len(msg_events) == 1
        assert msg_events[0]["content_preview"] == "Hello there"

    def test_assistant_message_captured(self, tmp_path: Path) -> None:
        msg = _gemini_msg(msg_id="g1")
        msg["content"] = "Here are the files."
        session = _make_session([msg])
        posted = self._run_tail(tmp_path, session)
        msg_events = [p for p in posted if p["event_type"] == "message"]
        assert len(msg_events) == 1
        assert msg_events[0]["role"] == "assistant"
        assert "Here are the files" in msg_events[0]["content_preview"]

    def test_assistant_empty_content_not_captured(self, tmp_path: Path) -> None:
        msg = _gemini_msg(msg_id="g1")
        msg["content"] = ""
        session = _make_session([msg])
        posted = self._run_tail(tmp_path, session)
        msg_events = [p for p in posted if p["event_type"] == "message"]
        assert len(msg_events) == 0

    def test_user_empty_content_not_captured(self, tmp_path: Path) -> None:
        session = _make_session(
            [
                {"id": "u1", "type": "user", "timestamp": "2026-04-15T10:00:00Z", "content": []},
            ]
        )
        posted = self._run_tail(tmp_path, session)
        msg_events = [p for p in posted if p["event_type"] == "message"]
        assert len(msg_events) == 0

    def test_no_messages_without_capture_flag(self, tmp_path: Path) -> None:
        msg = _gemini_msg(msg_id="g1")
        msg["content"] = "Some text"
        session = _make_session(
            [
                {
                    "id": "u1",
                    "type": "user",
                    "timestamp": "2026-04-15T10:00:00Z",
                    "content": [{"text": "hi"}],
                },
                msg,
            ]
        )
        w = _watcher(tmp_path)  # capture_messages=False
        session_file = tmp_path / "chat.json"
        session_file.write_text(json.dumps(session), encoding="utf-8")
        posted: list = []
        with patch.object(
            w._client, "post", side_effect=lambda url, json, **kw: posted.append(json)
        ):  # noqa: A002
            w._tail(str(session_file))
        assert not any(p["event_type"] == "message" for p in posted)
