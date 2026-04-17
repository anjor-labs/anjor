from datetime import UTC, datetime
from pathlib import Path

import pytest

from anjor.core.events.llm_call import LLMCallEvent
from anjor.core.events.message import MessageEvent
from anjor.core.events.tool_call import FailureType, ToolCallEvent, ToolCallStatus
from anjor.watchers.claude import ClaudeTranscriptWatcher, _decode_project_dir


def test_assistant_text_only_emits_llm_event():
    w = ClaudeTranscriptWatcher()
    line = '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"claude","stop_reason":"end_turn","usage":{"input_tokens":3,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":120},"content":[{"type":"text","text":"Hi"}]}}'
    events = w.parse_line(line)
    assert len(events) == 1
    assert isinstance(events[0], LLMCallEvent)


def test_assistant_streaming_chunk_skipped():
    w = ClaudeTranscriptWatcher()
    line = '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"claude","stop_reason":null,"usage":{"input_tokens":3,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":120},"content":[{"type":"text","text":"Hi"}]}}'
    events = w.parse_line(line)
    assert events == []


def test_duplicate_uuid_skipped():
    w = ClaudeTranscriptWatcher()
    line = '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"claude","stop_reason":"end_turn","usage":{"input_tokens":3,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":120},"content":[{"type":"text","text":"Hi"}]}}'
    events = w.parse_line(line)
    assert len(events) == 1

    events2 = w.parse_line(line)
    assert events2 == []


def test_tool_use_buffers_pending():
    w = ClaudeTranscriptWatcher()
    line = '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"claude","stop_reason":"tool_use","usage":{"input_tokens":3,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":120},"content":[{"type":"tool_use","id":"tu_1","name":"Read","input":{}}]}}'
    events = w.parse_line(line)
    assert len(events) == 1  # LLM event
    assert isinstance(events[0], LLMCallEvent)

    assert "tu_1" in w._pending


def test_tool_result_success_completes_event():
    w = ClaudeTranscriptWatcher()
    w.parse_line(
        '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"claude","stop_reason":"tool_use","usage":{"input_tokens":3,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":120},"content":[{"type":"tool_use","id":"tu_1","name":"Read","input":{}}]}}'
    )
    events = w.parse_line(
        '{"type":"user","uuid":"u1","timestamp":"2026-04-15T10:00:03Z","sessionId":"sess-1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":"done","is_error":false}]}}'
    )
    assert len(events) == 1
    tc = events[0]
    assert isinstance(tc, ToolCallEvent)
    assert tc.status == ToolCallStatus.SUCCESS


def test_tool_result_is_error_sets_failure():
    w = ClaudeTranscriptWatcher()
    w.parse_line(
        '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"claude","stop_reason":"tool_use","usage":{"input_tokens":3,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":120},"content":[{"type":"tool_use","id":"tu_1","name":"Read","input":{}}]}}'
    )
    events = w.parse_line(
        '{"type":"user","uuid":"u1","timestamp":"2026-04-15T10:00:03Z","sessionId":"sess-1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":"fail","is_error":true}]}}'
    )
    tc = events[0]
    assert tc.status == ToolCallStatus.FAILURE
    assert tc.failure_type == FailureType.UNKNOWN


def test_latency_is_timestamp_delta():
    w = ClaudeTranscriptWatcher()
    w.parse_line(
        '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"claude","stop_reason":"tool_use","usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0},"content":[{"type":"tool_use","id":"tu_1","name":"Read","input":{}}]}}'
    )
    events = w.parse_line(
        '{"type":"user","uuid":"u1","timestamp":"2026-04-15T10:00:03Z","sessionId":"sess-1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":"done","is_error":false}]}}'
    )
    tc = events[0]
    assert tc.latency_ms == pytest.approx(2000.0)


def test_two_tool_use_blocks_two_events():
    w = ClaudeTranscriptWatcher()
    w.parse_line(
        '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"claude","stop_reason":"tool_use","usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0},"content":[{"type":"tool_use","id":"tu_1","name":"Read","input":{}},{"type":"tool_use","id":"tu_2","name":"Write","input":{}}]}}'
    )
    e1 = w.parse_line(
        '{"type":"user","uuid":"u1","timestamp":"2026-04-15T10:00:02Z","sessionId":"sess-1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":"done","is_error":false}]}}'
    )
    e2 = w.parse_line(
        '{"type":"user","uuid":"u2","timestamp":"2026-04-15T10:00:03Z","sessionId":"sess-1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_2","content":"done","is_error":false}]}}'
    )
    assert len(e1) == 1
    assert len(e2) == 1
    assert e1[0].tool_name == "Read"
    assert e2[0].tool_name == "Write"


def test_unmatched_tool_result_skipped():
    w = ClaudeTranscriptWatcher()
    events = w.parse_line(
        '{"type":"user","uuid":"u1","timestamp":"2026-04-15T10:00:03Z","sessionId":"sess-1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_xyz","content":"done","is_error":false}]}}'
    )
    assert events == []


def test_source_tag_on_llm_event():
    w = ClaudeTranscriptWatcher()
    events = w.parse_line(
        '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"claude","stop_reason":"end_turn","usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0},"content":[{"type":"text","text":"Hi"}]}}'
    )
    assert events[0].source == "claude_code"


def test_source_tag_on_tool_event():
    w = ClaudeTranscriptWatcher()
    w.parse_line(
        '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"c","stop_reason":"tool_use","usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0},"content":[{"type":"tool_use","id":"tu_1","name":"Read","input":{}}]}}'
    )
    events = w.parse_line(
        '{"type":"user","uuid":"u1","timestamp":"2026-04-15T10:00:03Z","sessionId":"sess-1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":"","is_error":false}]}}'
    )
    assert events[0].source == "claude_code"


def test_session_id_and_trace_id_equal_session_id():
    w = ClaudeTranscriptWatcher()
    events = w.parse_line(
        '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"ABC-123","message":{"model":"claude","stop_reason":"end_turn","usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0},"content":[{"type":"text","text":"Hi"}]}}'
    )
    assert events[0].session_id == "ABC-123"
    assert events[0].trace_id == "ABC-123"


def test_non_json_line_returns_none():
    w = ClaudeTranscriptWatcher()
    assert w.parse_line("hello") is None


def test_unknown_outer_type_returns_none():
    w = ClaudeTranscriptWatcher()
    assert w.parse_line('{"type":"something-else","uuid":"xyz"}') is None


def test_queue_operation_skipped():
    w = ClaudeTranscriptWatcher()
    assert w.parse_line('{"type":"queue-operation","uuid":"xyz"}') is None


def test_file_history_snapshot_skipped():
    w = ClaudeTranscriptWatcher()
    assert w.parse_line('{"type":"file-history-snapshot","uuid":"xyz"}') is None


def test_gc_clears_old_pending():
    w = ClaudeTranscriptWatcher()
    # Mock time and GC counter
    w._pending["tu_old"] = {
        "ts": datetime(2000, 1, 1, tzinfo=UTC),
        "name": "x",
        "input": {},
        "session_id": "y",
    }
    w._gc_counter = 9999

    # Just force the GC method
    w._gc_pending()
    assert "tu_old" not in w._pending


def test_tool_result_content_string():
    w = ClaudeTranscriptWatcher()
    w.parse_line(
        '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"c","stop_reason":"tool_use","usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0},"content":[{"type":"tool_use","id":"tu_1","name":"Read","input":{}}]}}'
    )
    events = w.parse_line(
        '{"type":"user","uuid":"u1","timestamp":"2026-04-15T10:00:03Z","sessionId":"sess-1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":"string content","is_error":false}]}}'
    )
    assert events[0].output_payload.get("text") == "string content"


def test_tool_result_content_list():
    w = ClaudeTranscriptWatcher()
    w.parse_line(
        '{"type":"assistant","uuid":"a1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-1","message":{"model":"c","stop_reason":"tool_use","usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0},"content":[{"type":"tool_use","id":"tu_1","name":"Read","input":{}}]}}'
    )
    events = w.parse_line(
        '{"type":"user","uuid":"u1","timestamp":"2026-04-15T10:00:03Z","sessionId":"sess-1","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_1","content":[{"type":"text","text":"list content"}],"is_error":false}]}}'
    )
    assert events[0].output_payload.get("text") == "list content"


def test_full_fixture(tmp_path):
    w = ClaudeTranscriptWatcher()
    fixture = Path(__file__).parent / "fixtures" / "claude_session.jsonl"
    lines = fixture.read_text().splitlines()

    emitted = []
    for line in lines:
        out = w.parse_line(line)
        if out:
            emitted.extend(out)

    llm_events = [e for e in emitted if isinstance(e, LLMCallEvent)]
    tool_events = [e for e in emitted if isinstance(e, ToolCallEvent)]

    assert len(llm_events) == 3
    assert len(tool_events) == 3


# ── _decode_project_dir ────────────────────────────────────────────────────


def test_decode_project_dir_simple():
    # /Users/anjistic/code/anjor → "-Users-anjistic-code-anjor" → "anjor"
    assert _decode_project_dir("-Users-anjistic-code-anjor") == "anjor"


def test_decode_project_dir_with_spaces():
    # /Users/anjistic/Desktop/personal projects/anjor → "-Users-anjistic-Desktop-personal projects-anjor"
    assert _decode_project_dir("-Users-anjistic-Desktop-personal projects-anjor") == "anjor"


def test_decode_project_dir_empty():
    assert _decode_project_dir("") == ""


def test_decode_project_dir_only_dashes():
    assert _decode_project_dir("---") == ""


def test_project_from_path_claude_watcher(tmp_path):
    # Simulate the Claude Code path structure
    project_dir = tmp_path / "-Users-anjistic-code-myproject"
    project_dir.mkdir()
    session_file = project_dir / "session.jsonl"
    session_file.write_text("")
    w = ClaudeTranscriptWatcher()
    assert w._project_from_path(str(session_file)) == "myproject"


def test_project_override_takes_precedence_over_auto(tmp_path):
    project_dir = tmp_path / "-Users-anjistic-code-myproject"
    project_dir.mkdir()
    session_file = project_dir / "session.jsonl"
    session_file.write_text("")
    # Explicit override
    w = ClaudeTranscriptWatcher(project="override")
    assert w._project == "override"
    # The base _tail logic uses self._project if set, skipping auto-detection


# ---------------------------------------------------------------------------
# Conversation capture (capture_messages=True)
# ---------------------------------------------------------------------------

_ASSISTANT_LINE = '{"type":"assistant","uuid":"cap1","timestamp":"2026-04-15T10:00:01Z","sessionId":"sess-cap","message":{"model":"claude","stop_reason":"end_turn","usage":{"input_tokens":10,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":42},"content":[{"type":"text","text":"Hello, how can I help?"}]}}'
_USER_STR_LINE = '{"type":"user","uuid":"u-str","timestamp":"2026-04-15T10:00:02Z","sessionId":"sess-cap","message":{"role":"user","content":"Please list the files"}}'
_USER_LIST_LINE = '{"type":"user","uuid":"u-lst","timestamp":"2026-04-15T10:00:03Z","sessionId":"sess-cap","message":{"role":"user","content":[{"type":"text","text":"Explain this code"}]}}'


def test_capture_off_no_message_events():
    w = ClaudeTranscriptWatcher(capture_messages=False)
    events = w.parse_line(_ASSISTANT_LINE)
    assert not any(isinstance(e, MessageEvent) for e in events)


def test_capture_on_assistant_emits_message_event():
    w = ClaudeTranscriptWatcher(capture_messages=True)
    events = w.parse_line(_ASSISTANT_LINE)
    msg_events = [e for e in events if isinstance(e, MessageEvent)]
    assert len(msg_events) == 1
    msg = msg_events[0]
    assert msg.role == "assistant"
    assert "Hello" in msg.content_preview
    assert msg.token_count == 42


def test_capture_on_user_string_emits_message_event():
    w = ClaudeTranscriptWatcher(capture_messages=True)
    events = w.parse_line(_USER_STR_LINE)
    msg_events = [e for e in events if isinstance(e, MessageEvent)]
    assert len(msg_events) == 1
    assert msg_events[0].role == "user"
    assert "files" in msg_events[0].content_preview


def test_capture_on_user_list_text_block_emits_message_event():
    w = ClaudeTranscriptWatcher(capture_messages=True)
    events = w.parse_line(_USER_LIST_LINE)
    msg_events = [e for e in events if isinstance(e, MessageEvent)]
    assert len(msg_events) == 1
    assert msg_events[0].role == "user"
    assert "Explain" in msg_events[0].content_preview


def test_capture_on_user_tool_result_only_no_extra_message_event():
    # Tool result turns should not emit MessageEvents
    w = ClaudeTranscriptWatcher(capture_messages=True)
    w.parse_line(
        '{"type":"assistant","uuid":"ax","timestamp":"2026-04-15T10:00:01Z","sessionId":"s","message":{"model":"claude","stop_reason":"tool_use","usage":{"input_tokens":0,"cache_creation_input_tokens":0,"cache_read_input_tokens":0,"output_tokens":0},"content":[{"type":"tool_use","id":"tu_x","name":"Bash","input":{}}]}}'
    )
    events = w.parse_line(
        '{"type":"user","uuid":"ux","timestamp":"2026-04-15T10:00:03Z","sessionId":"s","message":{"role":"user","content":[{"type":"tool_result","tool_use_id":"tu_x","content":"done","is_error":false}]}}'
    )
    assert not any(isinstance(e, MessageEvent) for e in events)


def test_content_preview_truncated_at_500():
    long_text = "x" * 600
    line = f'{{"type":"user","uuid":"u-long","timestamp":"2026-04-15T10:00:01Z","sessionId":"s","message":{{"role":"user","content":"{long_text}"}}}}'
    w = ClaudeTranscriptWatcher(capture_messages=True)
    events = w.parse_line(line)
    msg_events = [e for e in events if isinstance(e, MessageEvent)]
    assert len(msg_events) == 1
    assert len(msg_events[0].content_preview) == 500
