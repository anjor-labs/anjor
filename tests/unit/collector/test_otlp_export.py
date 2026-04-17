"""Tests for OtlpExportHandler and span-building helpers."""

from __future__ import annotations

from datetime import UTC, datetime
from unittest.mock import MagicMock, patch

import pytest

from anjor.collector.export.otlp import (
    OtlpExportHandler,
    _llm_span,
    _new_span_id,
    _tool_span,
    _trace_id_hex,
    _unix_nano,
)
from anjor.core.events.agent_span import AgentSpanEvent
from anjor.core.events.llm_call import LLMCallEvent, LLMTokenUsage
from anjor.core.events.tool_call import ToolCallEvent


def _tool_event(**overrides: object) -> ToolCallEvent:
    defaults: dict[str, object] = {
        "tool_name": "bash",
        "trace_id": "00000000-0000-0000-0000-000000000001",
        "session_id": "00000000-0000-0000-0000-000000000002",
        "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
        "latency_ms": 100.0,
        "status": "success",
        "failure_type": None,
        "input_payload": {},
        "output_payload": {},
        "input_schema_hash": "",
        "output_schema_hash": "",
        "sequence_no": 0,
        "agent_id": "default",
    }
    defaults.update(overrides)
    return ToolCallEvent(**defaults)  # type: ignore


def _llm_event(**overrides: object) -> LLMCallEvent:
    defaults: dict[str, object] = {
        "model": "claude-3-5-sonnet-20241022",
        "trace_id": "00000000-0000-0000-0000-000000000003",
        "session_id": "00000000-0000-0000-0000-000000000004",
        "timestamp": datetime(2025, 1, 1, 12, 0, 0, tzinfo=UTC),
        "latency_ms": 500.0,
        "token_usage": LLMTokenUsage(input=100, output=50),
        "sequence_no": 0,
        "agent_id": "default",
    }
    defaults.update(overrides)
    return LLMCallEvent(**defaults)  # type: ignore


class TestHelpers:
    def test_trace_id_hex_from_uuid(self) -> None:
        hex_id = _trace_id_hex("00000000-0000-0000-0000-000000000001")
        assert len(hex_id) == 32
        assert hex_id == "00000000000000000000000000000001"

    def test_trace_id_hex_from_arbitrary_string(self) -> None:
        hex_id = _trace_id_hex("not-a-uuid")
        assert len(hex_id) == 32

    def test_new_span_id_length(self) -> None:
        assert len(_new_span_id()) == 16

    def test_unix_nano_is_string(self) -> None:
        dt = datetime(2025, 1, 1, 0, 0, 0, tzinfo=UTC)
        result = _unix_nano(dt)
        assert isinstance(result, str)
        assert int(result) > 0


class TestToolSpan:
    def test_span_name(self) -> None:
        span = _tool_span(_tool_event())
        assert span["name"] == "tool/bash"

    def test_success_status_code(self) -> None:
        span = _tool_span(_tool_event(status="success"))
        assert span["status"]["code"] == 1

    def test_error_status_code(self) -> None:
        span = _tool_span(_tool_event(status="failure"))
        assert span["status"]["code"] == 2

    def test_trace_id_hex(self) -> None:
        span = _tool_span(_tool_event())
        assert span["traceId"] == "00000000000000000000000000000001"

    def test_end_time_after_start(self) -> None:
        span = _tool_span(_tool_event(latency_ms=200.0))
        assert int(span["endTimeUnixNano"]) > int(span["startTimeUnixNano"])

    def test_latency_ms_encoded(self) -> None:
        span = _tool_span(_tool_event(latency_ms=150.0))
        keys = [a["key"] for a in span["attributes"]]
        assert "anjor.latency_ms" in keys

    def test_failure_type_included_when_set(self) -> None:
        span = _tool_span(_tool_event(status="failure", failure_type="timeout"))
        keys = [a["key"] for a in span["attributes"]]
        assert "anjor.failure_type" in keys

    def test_failure_type_absent_when_none(self) -> None:
        span = _tool_span(_tool_event())
        keys = [a["key"] for a in span["attributes"]]
        assert "anjor.failure_type" not in keys

    def test_project_included_when_set(self) -> None:
        span = _tool_span(_tool_event(project="myapp"))
        keys = [a["key"] for a in span["attributes"]]
        assert "anjor.project" in keys

    def test_kind_is_internal(self) -> None:
        assert _tool_span(_tool_event())["kind"] == 1


class TestLLMSpan:
    def test_span_name(self) -> None:
        span = _llm_span(_llm_event())
        assert span["name"] == "llm/claude-3-5-sonnet-20241022"

    def test_gen_ai_system(self) -> None:
        span = _llm_span(_llm_event())
        attrs = {a["key"]: a["value"] for a in span["attributes"]}
        assert attrs["gen_ai.system"]["stringValue"] == "anthropic"

    def test_token_counts_present(self) -> None:
        span = _llm_span(_llm_event())
        keys = [a["key"] for a in span["attributes"]]
        assert "gen_ai.usage.input_tokens" in keys
        assert "gen_ai.usage.output_tokens" in keys

    def test_token_counts_absent_when_none(self) -> None:
        span = _llm_span(_llm_event(token_usage=None))
        keys = [a["key"] for a in span["attributes"]]
        assert "gen_ai.usage.input_tokens" not in keys

    def test_status_ok(self) -> None:
        assert _llm_span(_llm_event())["status"]["code"] == 1


class TestOtlpExportHandler:
    @pytest.mark.asyncio
    async def test_tool_event_posts_to_traces_endpoint(self) -> None:
        handler = OtlpExportHandler(endpoint="http://otel:4318", headers={})
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch.object(handler._client, "post", return_value=mock_resp) as mock_post:
            await handler.handle(_tool_event())
        mock_post.assert_called_once()
        url = mock_post.call_args[0][0]
        assert url.endswith("/v1/traces")

    @pytest.mark.asyncio
    async def test_llm_event_posts_to_traces_endpoint(self) -> None:
        handler = OtlpExportHandler(endpoint="http://otel:4318", headers={})
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch.object(handler._client, "post", return_value=mock_resp) as mock_post:
            await handler.handle(_llm_event())
        mock_post.assert_called_once()

    @pytest.mark.asyncio
    async def test_unknown_event_type_skipped(self) -> None:
        handler = OtlpExportHandler(endpoint="http://otel:4318", headers={})
        with patch.object(handler._client, "post") as mock_post:
            await handler.handle(
                AgentSpanEvent(  # type: ignore
                    span_id="s1",
                    parent_span_id=None,
                    operation="test",
                    agent_name="a",
                    duration_ms=10.0,
                )
            )
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_export_failure_swallowed(self) -> None:
        handler = OtlpExportHandler(endpoint="http://otel:4318", headers={})
        with patch.object(handler._client, "post", side_effect=Exception("connection refused")):
            await handler.handle(_tool_event())  # must not raise

    @pytest.mark.asyncio
    async def test_custom_headers_forwarded(self) -> None:
        handler = OtlpExportHandler(
            endpoint="http://otel:4318",
            headers={"x-api-key": "secret"},
        )
        assert handler._client.headers.get("x-api-key") == "secret"
        await handler.shutdown()

    @pytest.mark.asyncio
    async def test_shutdown_closes_client(self) -> None:
        handler = OtlpExportHandler(endpoint="http://otel:4318", headers={})
        with patch.object(handler._client, "aclose") as mock_close:
            await handler.shutdown()
        mock_close.assert_called_once()

    @pytest.mark.asyncio
    async def test_payload_structure(self) -> None:
        handler = OtlpExportHandler(endpoint="http://otel:4318", headers={})
        captured: list[dict] = []

        async def fake_post(url: str, **kwargs: object) -> MagicMock:
            captured.append(kwargs.get("json", {}))  # type: ignore
            resp = MagicMock()
            resp.raise_for_status = MagicMock()
            return resp

        with patch.object(handler._client, "post", side_effect=fake_post):
            await handler.handle(_tool_event())

        assert len(captured) == 1
        payload = captured[0]
        assert "resourceSpans" in payload
        rs = payload["resourceSpans"][0]
        assert "resource" in rs
        assert "scopeSpans" in rs
        spans = rs["scopeSpans"][0]["spans"]
        assert len(spans) == 1
        assert spans[0]["name"] == "tool/bash"
