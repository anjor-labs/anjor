"""Unit tests for anjor.context — span() context manager and context vars."""

from __future__ import annotations

import json
from unittest.mock import patch

import httpx
import pytest

from anjor.context import (
    get_agent_id,
    get_parent_span_id,
    get_span_id,
    get_trace_id,
    span,
)
from anjor.core.events.base import BaseEvent
from anjor.core.pipeline.pipeline import EventPipeline


class CapturingPipeline(EventPipeline):
    def __init__(self) -> None:
        super().__init__()
        self.captured: list[BaseEvent] = []

    def put(self, event: BaseEvent) -> bool:
        self.captured.append(event)
        return True


# ── Context var tests ──────────────────────────────────────────────────────────


class TestContextVarDefaults:
    def test_trace_id_default_empty(self) -> None:
        assert get_trace_id() == ""

    def test_agent_id_default_empty(self) -> None:
        assert get_agent_id() == ""

    def test_span_id_default_empty(self) -> None:
        assert get_span_id() == ""

    def test_parent_span_id_default_empty(self) -> None:
        assert get_parent_span_id() == ""


# ── span() context manager tests ──────────────────────────────────────────────


class TestSpanContextManager:
    def test_sets_trace_id_inside_block(self) -> None:
        with span("test_agent", trace_id="trace-001"):
            assert get_trace_id() == "trace-001"

    def test_sets_agent_id_inside_block(self) -> None:
        with span("my_agent", trace_id="t"):
            assert get_agent_id() == "my_agent"

    def test_sets_span_id_inside_block(self) -> None:
        with span("agent", trace_id="t"):
            assert get_span_id() != ""

    def test_resets_after_block(self) -> None:
        with span("agent", trace_id="trace-999"):
            pass
        assert get_trace_id() == ""
        assert get_agent_id() == ""
        assert get_span_id() == ""
        assert get_parent_span_id() == ""

    def test_resets_after_exception(self) -> None:
        with pytest.raises(ValueError):
            with span("agent", trace_id="trace-exc"):
                raise ValueError("boom")
        assert get_trace_id() == ""
        assert get_agent_id() == ""

    def test_auto_generates_trace_id_when_omitted(self) -> None:
        with span("agent") as resolved:
            assert get_trace_id() != ""
            assert resolved != ""

    def test_yields_resolved_trace_id(self) -> None:
        with span("agent", trace_id="explicit-id") as resolved:
            assert resolved == "explicit-id"

    def test_nested_spans_restore_outer(self) -> None:
        with span("outer", trace_id="outer-trace"):
            with span("inner", trace_id="inner-trace"):
                assert get_trace_id() == "inner-trace"
                assert get_agent_id() == "inner"
            # After inner exits, outer context is restored
            assert get_trace_id() == "outer-trace"
            assert get_agent_id() == "outer"

    def test_parent_span_id_set(self) -> None:
        with span("outer", trace_id="t") as _:
            outer_span = get_span_id()
            with span("inner", trace_id="t", parent_span_id=outer_span):
                assert get_parent_span_id() == outer_span

    def test_emits_agent_span_event_on_exit(self) -> None:
        pipeline = CapturingPipeline()
        with patch("anjor._pipeline", pipeline):
            with span("test_agent", trace_id="emit-trace"):
                pass
        from anjor.core.events.agent_span import AgentSpanEvent

        assert len(pipeline.captured) == 1
        event = pipeline.captured[0]
        assert isinstance(event, AgentSpanEvent)
        assert event.trace_id == "emit-trace"
        assert event.agent_name == "test_agent"
        assert event.status == "ok"

    def test_emits_error_status_on_exception(self) -> None:
        pipeline = CapturingPipeline()
        with patch("anjor._pipeline", pipeline):
            with pytest.raises(RuntimeError):
                with span("failing_agent", trace_id="err-trace"):
                    raise RuntimeError("test error")

        from anjor.core.events.agent_span import AgentSpanEvent

        assert len(pipeline.captured) == 1
        event = pipeline.captured[0]
        assert isinstance(event, AgentSpanEvent)
        assert event.status == "error"
        assert event.failure_type == "unknown"

    def test_no_emit_when_pipeline_none(self) -> None:
        with patch("anjor._pipeline", None):
            # Should not raise
            with span("agent", trace_id="no-pipeline"):
                pass


# ── PatchInterceptor context var override tests ───────────────────────────────


class TestPatchInterceptorContextOverride:
    """Ensure PatchInterceptor stamps events with context var values."""

    _ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
    _TOOL_RESPONSE = {
        "content": [{"type": "tool_use", "id": "tu_01", "name": "search", "input": {"q": "x"}}],
        "usage": {"input_tokens": 10, "output_tokens": 5},
    }
    _REQUEST_BODY = {"model": "claude-3-5-sonnet-20241022", "max_tokens": 512, "messages": []}

    def _make_request(self) -> httpx.Request:
        return httpx.Request(
            "POST",
            self._ANTHROPIC_URL,
            content=json.dumps(self._REQUEST_BODY).encode(),
            headers={"content-type": "application/json"},
        )

    def _make_response(self) -> httpx.Response:
        return httpx.Response(
            status_code=200,
            content=json.dumps(self._TOOL_RESPONSE).encode(),
            headers={"content-type": "application/json"},
        )

    def test_context_trace_id_stamped_on_events(self) -> None:
        from anjor.interceptors.patch import PatchInterceptor

        pipeline = CapturingPipeline()
        interceptor = PatchInterceptor(pipeline=pipeline)

        with span("ctx_agent", trace_id="ctx-trace-001"):
            interceptor._process(self._make_request(), self._make_response(), 50.0)

        assert all(e.trace_id == "ctx-trace-001" for e in pipeline.captured)
        assert all(e.agent_id == "ctx_agent" for e in pipeline.captured)

    def test_default_trace_id_used_when_no_span(self) -> None:
        from anjor.interceptors.patch import PatchInterceptor

        pipeline = CapturingPipeline()
        interceptor = PatchInterceptor(pipeline=pipeline, default_trace_id="session-abc")

        # Outside any span — default_trace_id should be applied
        interceptor._process(self._make_request(), self._make_response(), 50.0)

        assert len(pipeline.captured) > 0
        assert all(e.trace_id == "session-abc" for e in pipeline.captured)

    def test_span_overrides_default_trace_id(self) -> None:
        from anjor.interceptors.patch import PatchInterceptor

        pipeline = CapturingPipeline()
        interceptor = PatchInterceptor(pipeline=pipeline, default_trace_id="session-abc")

        with span("my_agent", trace_id="explicit-trace"):
            interceptor._process(self._make_request(), self._make_response(), 50.0)

        # span() wins over the default
        assert all(e.trace_id == "explicit-trace" for e in pipeline.captured)
        assert all(e.agent_id == "my_agent" for e in pipeline.captured)

    def test_agent_id_inferred_from_system_prompt(self) -> None:
        from anjor.interceptors.patch import PatchInterceptor

        pipeline = CapturingPipeline()
        interceptor = PatchInterceptor(pipeline=pipeline, default_trace_id="t")

        body_with_system = {**self._REQUEST_BODY, "system": "You are a web researcher."}
        request = httpx.Request(
            "POST",
            self._ANTHROPIC_URL,
            content=json.dumps(body_with_system).encode(),
            headers={"content-type": "application/json"},
        )
        interceptor._process(request, self._make_response(), 50.0)

        assert len(pipeline.captured) > 0
        # agent_id should contain part of the system prompt + a hash
        for event in pipeline.captured:
            assert "You are a web res" in event.agent_id
            assert len(event.agent_id) > 20  # prefix + _ + hash

    def test_no_agent_id_inferred_without_system_prompt(self) -> None:
        from anjor.interceptors.patch import PatchInterceptor

        pipeline = CapturingPipeline()
        interceptor = PatchInterceptor(pipeline=pipeline, default_trace_id="t")

        # _REQUEST_BODY has no system field
        interceptor._process(self._make_request(), self._make_response(), 50.0)

        # agent_id falls back to whatever the parser set (model name or empty string)
        assert len(pipeline.captured) > 0
