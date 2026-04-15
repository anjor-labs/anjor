from datetime import UTC, datetime
from pathlib import Path

import pytest

from anjor.core.events.llm_call import LLMCallEvent
from anjor.core.events.tool_call import FailureType, ToolCallEvent, ToolCallStatus
from anjor.watchers.claude import ClaudeTranscriptWatcher


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
