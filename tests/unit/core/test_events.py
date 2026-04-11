"""Unit tests for core event models and registry."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from agentscope.core.events.base import BaseEvent, EventType
from agentscope.core.events.llm_call import LLMCallEvent
from agentscope.core.events.registry import EventTypeRegistry, default_registry
from agentscope.core.events.tool_call import (
    FailureType,
    SchemaDrift,
    TokenUsage,
    ToolCallEvent,
    ToolCallStatus,
)

# ---------------------------------------------------------------------------
# BaseEvent tests
# ---------------------------------------------------------------------------


class TestBaseEvent:
    def test_defaults_are_populated(self) -> None:
        event = BaseEvent(event_type=EventType.TOOL_CALL)
        assert event.trace_id
        assert event.session_id
        assert event.agent_id == "default"
        assert isinstance(event.timestamp, datetime)
        assert event.sequence_no == 0

    def test_timestamp_is_utc(self) -> None:
        event = BaseEvent(event_type=EventType.TOOL_CALL)
        assert event.timestamp.tzinfo is UTC

    def test_trace_id_unique_per_instance(self) -> None:
        e1 = BaseEvent(event_type=EventType.TOOL_CALL)
        e2 = BaseEvent(event_type=EventType.TOOL_CALL)
        assert e1.trace_id != e2.trace_id

    def test_session_id_unique_per_instance(self) -> None:
        e1 = BaseEvent(event_type=EventType.TOOL_CALL)
        e2 = BaseEvent(event_type=EventType.TOOL_CALL)
        assert e1.session_id != e2.session_id

    def test_frozen_prevents_mutation(self) -> None:
        event = BaseEvent(event_type=EventType.TOOL_CALL)
        with pytest.raises(ValidationError):
            event.agent_id = "changed"  # type: ignore[misc]

    def test_sequence_no_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            BaseEvent(event_type=EventType.TOOL_CALL, sequence_no=-1)

    def test_custom_fields(self) -> None:
        event = BaseEvent(
            event_type=EventType.LLM_CALL,
            trace_id="trace-abc",
            session_id="session-xyz",
            agent_id="my-agent",
            sequence_no=5,
        )
        assert event.trace_id == "trace-abc"
        assert event.session_id == "session-xyz"
        assert event.agent_id == "my-agent"
        assert event.sequence_no == 5


# ---------------------------------------------------------------------------
# ToolCallEvent tests
# ---------------------------------------------------------------------------


class TestToolCallEvent:
    def _make_success(self, **kwargs: object) -> ToolCallEvent:
        return ToolCallEvent(
            tool_name="search",
            status=ToolCallStatus.SUCCESS,
            latency_ms=100.0,
            **kwargs,  # type: ignore[arg-type]
        )

    def _make_failure(self, **kwargs: object) -> ToolCallEvent:
        return ToolCallEvent(
            tool_name="search",
            status=ToolCallStatus.FAILURE,
            latency_ms=50.0,
            **kwargs,  # type: ignore[arg-type]
        )

    def test_event_type_is_tool_call(self) -> None:
        event = self._make_success()
        assert event.event_type == EventType.TOOL_CALL

    def test_success_event_has_no_failure_type(self) -> None:
        event = self._make_success()
        assert event.failure_type is None

    def test_failure_without_failure_type_coerces_to_unknown(self) -> None:
        event = self._make_failure()
        assert event.failure_type == FailureType.UNKNOWN

    def test_failure_with_explicit_failure_type(self) -> None:
        event = self._make_failure(failure_type=FailureType.TIMEOUT)
        assert event.failure_type == FailureType.TIMEOUT

    def test_success_with_failure_type_raises(self) -> None:
        with pytest.raises(ValidationError, match="failure_type must be None"):
            self._make_success(failure_type=FailureType.TIMEOUT)

    def test_latency_must_be_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            ToolCallEvent(
                tool_name="t", status=ToolCallStatus.SUCCESS, latency_ms=-1
            )

    def test_frozen(self) -> None:
        event = self._make_success()
        with pytest.raises(ValidationError):
            event.tool_name = "other"  # type: ignore[misc]

    def test_payloads_default_empty(self) -> None:
        event = self._make_success()
        assert event.input_payload == {}
        assert event.output_payload == {}

    def test_token_usage(self) -> None:
        usage = TokenUsage(input=100, output=200)
        event = self._make_success(token_usage=usage)
        assert event.token_usage is not None
        assert event.token_usage.input == 100
        assert event.token_usage.output == 200

    def test_schema_drift(self) -> None:
        drift = SchemaDrift(
            detected=True,
            missing_fields=["count"],
            unexpected_fields=["total"],
            expected_hash="abc123",
        )
        event = self._make_failure(
            failure_type=FailureType.SCHEMA_DRIFT, schema_drift=drift
        )
        assert event.schema_drift is not None
        assert event.schema_drift.detected is True
        assert "count" in event.schema_drift.missing_fields


# ---------------------------------------------------------------------------
# LLMCallEvent tests
# ---------------------------------------------------------------------------


class TestLLMCallEvent:
    def test_event_type_is_llm_call(self) -> None:
        event = LLMCallEvent(model="claude-3-5-sonnet")
        assert event.event_type == EventType.LLM_CALL

    def test_defaults(self) -> None:
        event = LLMCallEvent(model="gpt-4")
        assert event.latency_ms == 0.0
        assert event.context_window_used == 0


# ---------------------------------------------------------------------------
# EventTypeRegistry tests
# ---------------------------------------------------------------------------


class TestEventTypeRegistry:
    def test_default_registry_has_tool_call(self) -> None:
        cls = default_registry.get(EventType.TOOL_CALL)
        assert cls is ToolCallEvent

    def test_default_registry_has_llm_call(self) -> None:
        cls = default_registry.get(EventType.LLM_CALL)
        assert cls is LLMCallEvent

    def test_get_unknown_raises_key_error(self) -> None:
        reg = EventTypeRegistry()
        with pytest.raises(KeyError, match="Unknown EventType"):
            reg.get(EventType.TOOL_CALL)

    def test_duplicate_register_raises(self) -> None:
        reg = EventTypeRegistry()
        reg.register(EventType.TOOL_CALL, ToolCallEvent)
        with pytest.raises(ValueError, match="already registered"):
            reg.register(EventType.TOOL_CALL, ToolCallEvent)

    def test_replace_overwrites(self) -> None:
        reg = EventTypeRegistry()
        reg.register(EventType.TOOL_CALL, ToolCallEvent)
        reg.replace(EventType.TOOL_CALL, LLMCallEvent)
        assert reg.get(EventType.TOOL_CALL) is LLMCallEvent

    def test_all_returns_snapshot(self) -> None:
        reg = EventTypeRegistry()
        reg.register(EventType.TOOL_CALL, ToolCallEvent)
        snapshot = reg.all()
        assert EventType.TOOL_CALL in snapshot
        # Snapshot is a copy — mutations don't affect registry
        snapshot[EventType.LLM_CALL] = LLMCallEvent
        assert EventType.LLM_CALL not in reg.all()

    def test_error_message_lists_registered_types(self) -> None:
        reg = EventTypeRegistry()
        reg.register(EventType.TOOL_CALL, ToolCallEvent)
        with pytest.raises(KeyError, match="tool_call"):
            reg.get(EventType.LLM_CALL)
