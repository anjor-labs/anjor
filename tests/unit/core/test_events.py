"""Unit tests for core event models and registry."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from pydantic import ValidationError

from anjor.core.events.base import BaseEvent, EventType
from anjor.core.events.llm_call import LLMCallEvent, LLMTokenUsage
from anjor.core.events.registry import EventTypeRegistry, default_registry
from anjor.core.events.tool_call import (
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
    def _make(self, **kwargs: object) -> LLMCallEvent:
        return LLMCallEvent(model="claude-3-5-sonnet-20241022", latency_ms=500.0, **kwargs)  # type: ignore[arg-type]

    def test_event_type_is_llm_call(self) -> None:
        assert self._make().event_type == EventType.LLM_CALL

    def test_inherits_base_event_fields(self) -> None:
        event = self._make()
        assert event.trace_id
        assert event.timestamp

    def test_defaults(self) -> None:
        event = self._make()
        assert event.latency_ms == 500.0
        assert event.context_window_used == 0
        assert event.context_window_limit == 0
        assert event.context_utilisation == 0.0
        assert event.token_usage is None
        assert event.prompt_hash == ""
        assert event.system_prompt_hash is None
        assert event.messages_count == 0
        assert event.finish_reason is None

    def test_context_utilisation_computed(self) -> None:
        event = self._make(context_window_used=50_000, context_window_limit=200_000)
        assert event.context_utilisation == pytest.approx(0.25)

    def test_context_utilisation_capped_at_one(self) -> None:
        # over-limit edge case — still 1.0, not > 1
        event = self._make(context_window_used=250_000, context_window_limit=200_000)
        assert event.context_utilisation == 1.0

    def test_context_utilisation_zero_when_limit_unknown(self) -> None:
        event = self._make(context_window_used=1000, context_window_limit=0)
        assert event.context_utilisation == 0.0

    def test_token_usage(self) -> None:
        usage = LLMTokenUsage(input=1000, output=250, cache_read=500)
        event = self._make(token_usage=usage)
        assert event.token_usage is not None
        assert event.token_usage.input == 1000
        assert event.token_usage.output == 250
        assert event.token_usage.cache_read == 500

    def test_token_usage_cache_read_defaults_zero(self) -> None:
        usage = LLMTokenUsage(input=100, output=50)
        assert usage.cache_read == 0

    def test_prompt_hash(self) -> None:
        event = self._make(
            prompt_hash="abc123",
            system_prompt_hash="def456",
        )
        assert event.prompt_hash == "abc123"
        assert event.system_prompt_hash == "def456"

    def test_finish_reason(self) -> None:
        for reason in ("end_turn", "tool_use", "max_tokens", "stop_sequence"):
            event = self._make(finish_reason=reason)
            assert event.finish_reason == reason

    def test_frozen(self) -> None:
        event = self._make()
        with pytest.raises(ValidationError):
            event.model = "other"  # type: ignore[misc]

    def test_latency_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            LLMCallEvent(model="claude", latency_ms=-1.0)

    def test_messages_count_non_negative(self) -> None:
        with pytest.raises(ValidationError):
            self._make(messages_count=-1)

    def test_serialises_to_dict(self) -> None:
        event = self._make(
            context_window_used=10_000,
            context_window_limit=200_000,
            token_usage=LLMTokenUsage(input=100, output=50),
        )
        d = event.model_dump()
        assert d["model"] == "claude-3-5-sonnet-20241022"
        assert d["context_utilisation"] == pytest.approx(0.05)


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
