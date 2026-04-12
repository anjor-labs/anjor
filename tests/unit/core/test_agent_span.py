"""Unit tests for AgentSpanEvent and SpanKind."""

from __future__ import annotations

import pytest
from pydantic import ValidationError
from pydantic_core import ValidationError as CoreValidationError

from anjor.core.events.agent_span import AgentSpanEvent, SpanKind
from anjor.core.events.base import EventType
from anjor.core.events.registry import default_registry


class TestSpanKind:
    def test_all_values(self) -> None:
        assert SpanKind.ROOT == "root"
        assert SpanKind.ORCHESTRATOR == "orchestrator"
        assert SpanKind.SUBAGENT == "subagent"
        assert SpanKind.TOOL == "tool"


class TestAgentSpanEvent:
    def test_defaults(self) -> None:
        span = AgentSpanEvent()
        assert span.event_type == EventType.AGENT_SPAN
        assert len(span.span_id) == 32  # 16-byte hex
        assert span.parent_span_id is None
        assert span.span_kind == SpanKind.ROOT
        assert span.agent_name == "unknown"
        assert span.status == "ok"
        assert span.token_input == 0
        assert span.token_output == 0
        assert span.tool_calls_count == 0
        assert span.llm_calls_count == 0

    def test_span_id_unique_per_instance(self) -> None:
        s1 = AgentSpanEvent()
        s2 = AgentSpanEvent()
        assert s1.span_id != s2.span_id

    def test_parent_child_link(self) -> None:
        parent = AgentSpanEvent(span_kind=SpanKind.ORCHESTRATOR, agent_name="planner")
        child = AgentSpanEvent(
            span_kind=SpanKind.SUBAGENT,
            agent_name="researcher",
            parent_span_id=parent.span_id,
            trace_id=parent.trace_id,
        )
        assert child.parent_span_id == parent.span_id
        assert child.trace_id == parent.trace_id

    def test_invalid_status(self) -> None:
        with pytest.raises(ValidationError):
            AgentSpanEvent(status="unknown")

    def test_negative_counters_rejected(self) -> None:
        with pytest.raises(ValidationError):
            AgentSpanEvent(token_input=-1)
        with pytest.raises(ValidationError):
            AgentSpanEvent(tool_calls_count=-1)

    def test_frozen(self) -> None:
        span = AgentSpanEvent()
        with pytest.raises((ValidationError, CoreValidationError, TypeError)):
            span.agent_name = "mutated"  # type: ignore[misc]

    def test_all_span_kinds(self) -> None:
        for kind in SpanKind:
            span = AgentSpanEvent(span_kind=kind)
            assert span.span_kind == kind

    def test_with_full_fields(self) -> None:
        span = AgentSpanEvent(
            span_kind=SpanKind.SUBAGENT,
            agent_name="summariser",
            agent_role="Summarises research output",
            parent_span_id="a" * 32,
            started_at="2026-04-12T10:00:00+00:00",
            ended_at="2026-04-12T10:00:02+00:00",
            status="error",
            failure_type="timeout",
            token_input=1200,
            token_output=300,
            tool_calls_count=3,
            llm_calls_count=2,
        )
        assert span.status == "error"
        assert span.failure_type == "timeout"
        assert span.token_input == 1200


class TestRegistryIncludesAgentSpan:
    def test_agent_span_registered(self) -> None:
        cls = default_registry.get(EventType.AGENT_SPAN)
        assert cls is AgentSpanEvent
