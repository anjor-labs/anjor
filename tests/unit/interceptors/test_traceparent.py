"""Unit tests for W3C traceparent helpers and PatchInterceptor injection."""

from __future__ import annotations

import httpx

from anjor.interceptors.traceparent import (
    HEADER,
    make_traceparent,
    new_span_id,
    new_trace_id,
    parse_traceparent,
)


class TestNewIds:
    def test_trace_id_length(self) -> None:
        assert len(new_trace_id()) == 32

    def test_span_id_length(self) -> None:
        assert len(new_span_id()) == 16

    def test_trace_id_hex(self) -> None:
        int(new_trace_id(), 16)  # raises if not valid hex

    def test_span_id_hex(self) -> None:
        int(new_span_id(), 16)

    def test_unique(self) -> None:
        assert new_trace_id() != new_trace_id()
        assert new_span_id() != new_span_id()


class TestMakeTraceparent:
    def test_format(self) -> None:
        tid = "a" * 32
        sid = "b" * 16
        result = make_traceparent(tid, sid)
        assert result == f"00-{tid}-{sid}-01"

    def test_round_trip(self) -> None:
        tid = new_trace_id()
        sid = new_span_id()
        parsed = parse_traceparent(make_traceparent(tid, sid))
        assert parsed is not None
        assert parsed == (tid, sid)


class TestParseTraceparent:
    def test_valid(self) -> None:
        tid = "a" * 32
        sid = "b" * 16
        result = parse_traceparent(f"00-{tid}-{sid}-01")
        assert result == (tid, sid)

    def test_invalid_version(self) -> None:
        tid = "a" * 32
        sid = "b" * 16
        assert parse_traceparent(f"01-{tid}-{sid}-01") is None

    def test_wrong_length(self) -> None:
        assert parse_traceparent("00-abc-def-01") is None

    def test_all_zero_trace_id(self) -> None:
        assert parse_traceparent(f"00-{'0' * 32}-{'a' * 16}-01") is None

    def test_all_zero_span_id(self) -> None:
        assert parse_traceparent(f"00-{'a' * 32}-{'0' * 16}-01") is None

    def test_empty_string(self) -> None:
        assert parse_traceparent("") is None

    def test_case_insensitive(self) -> None:
        tid = "A" * 32
        sid = "B" * 16
        result = parse_traceparent(f"00-{tid}-{sid}-01")
        assert result is not None
        assert result == (tid.lower(), sid.lower())


class TestPatchInterceptorInjectsTraceparent:
    def test_injects_when_absent(self) -> None:

        from anjor.interceptors.patch import PatchInterceptor

        interceptor = PatchInterceptor()
        request = httpx.Request("GET", "https://api.anthropic.com/v1/messages")
        assert HEADER not in request.headers

        interceptor._inject_traceparent(request)

        assert HEADER in request.headers
        value = request.headers[HEADER]
        parsed = parse_traceparent(value)
        assert parsed is not None

    def test_preserves_existing_traceparent(self) -> None:
        from anjor.interceptors.patch import PatchInterceptor

        tid = "c" * 32
        sid = "d" * 16
        existing = make_traceparent(tid, sid)
        request = httpx.Request(
            "GET",
            "https://api.anthropic.com/v1/messages",
            headers={HEADER: existing},
        )

        interceptor = PatchInterceptor()
        interceptor._inject_traceparent(request)

        assert request.headers[HEADER] == existing

    def test_injected_value_is_valid_w3c(self) -> None:
        from anjor.interceptors.patch import PatchInterceptor

        interceptor = PatchInterceptor()
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        interceptor._inject_traceparent(request)

        value = request.headers[HEADER]
        parts = value.split("-")
        assert len(parts) == 4
        assert parts[0] == "00"
        assert len(parts[1]) == 32
        assert len(parts[2]) == 16
        assert parts[3] == "01"
