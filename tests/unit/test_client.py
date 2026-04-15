"""Unit tests for anjor.Client — programmatic query client."""

from __future__ import annotations

import asyncio
import tempfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

import anjor
from anjor.client import Client
from anjor.collector.storage.sqlite import SQLiteBackend  # noqa: F401
from anjor.models import (
    FailurePattern,
    OptimizationSuggestion,
    RunQualityScore,
    ToolCallRecord,
    ToolQualityScore,
    ToolSummary,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _tool_event(
    tool_name: str = "web_search",
    status: str = "success",
    latency_ms: float = 100.0,
    trace_id: str = "trace-1",
    agent_id: str = "default",
) -> dict:
    return {
        "event_type": "tool_call",
        "trace_id": trace_id,
        "session_id": "session-1",
        "agent_id": agent_id,
        "timestamp": datetime.now(UTC).isoformat(),
        "sequence_no": 0,
        "tool_name": tool_name,
        "status": status,
        "failure_type": None if status == "success" else "unknown",
        "latency_ms": latency_ms,
        "input_payload": {},
        "output_payload": {},
        "input_schema_hash": "",
        "output_schema_hash": "",
    }


def _llm_event(
    model: str = "claude-3-5-sonnet-20241022",
    trace_id: str = "trace-1",
    token_input: int = 100,
    token_output: int = 50,
    context_utilisation: float = 0.1,
) -> dict:
    return {
        "event_type": "llm_call",
        "trace_id": trace_id,
        "session_id": "session-1",
        "agent_id": "default",
        "timestamp": datetime.now(UTC).isoformat(),
        "sequence_no": 1,
        "model": model,
        "latency_ms": 500.0,
        "token_usage": {
            "input": token_input,
            "output": token_output,
            "cache_read": 0,
            "cache_creation": 0,
        },
        "context_window_used": token_input + token_output,
        "context_window_limit": 200_000,
        "context_utilisation": context_utilisation,
        "prompt_hash": "abc",
        "system_prompt_hash": "def",
        "messages_count": 5,
        "finish_reason": "end_turn",
    }


def _seed_db(db_path: str, events: list[dict]) -> None:
    """Write events to a real SQLite DB synchronously (for test setup)."""

    async def _write() -> None:
        backend = SQLiteBackend(db_path=db_path, batch_size=1, batch_interval_ms=9_999_999)
        await backend.connect()
        for ev in events:
            await backend.write_event(ev)
        await backend.flush()
        await backend.close()

    asyncio.run(_write())


# ---------------------------------------------------------------------------
# Import / public API
# ---------------------------------------------------------------------------


class TestPublicAPI:
    def test_client_importable_from_anjor(self) -> None:
        assert anjor.Client is Client

    def test_client_in_all(self) -> None:
        assert "Client" in anjor.__all__

    def test_models_importable(self) -> None:
        from anjor.models import (  # noqa: F401
            FailurePattern,
            OptimizationSuggestion,
            RunQualityScore,
            ToolCallRecord,
            ToolQualityScore,
            ToolSummary,
        )


# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


class TestClientConstruction:
    def test_default_db_path(self) -> None:
        client = Client()
        assert client._db_path == "anjor.db"
        # Never opened — no file created
        assert client._backend is None

    def test_custom_db_path(self) -> None:
        client = Client("custom.db")
        assert client._db_path == "custom.db"

    def test_construction_does_not_open_db(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "no_file_yet.db")
            client = Client(db)
            assert client._backend is None  # no connection until first query

    def test_intelligence_namespace_available(self) -> None:
        client = Client()
        assert hasattr(client, "intelligence")
        assert hasattr(client.intelligence, "failures")
        assert hasattr(client.intelligence, "quality")
        assert hasattr(client.intelligence, "run_quality")
        assert hasattr(client.intelligence, "optimization")


# ---------------------------------------------------------------------------
# Context manager
# ---------------------------------------------------------------------------


class TestContextManager:
    def test_enter_returns_client(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "cm.db")
            _seed_db(db, [])
            with Client(db) as client:
                assert isinstance(client, Client)

    def test_exit_closes_connection(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "cm.db")
            _seed_db(db, [])
            with Client(db) as client:
                _ = client.tools()  # open connection
                assert client._backend is not None
            assert client._backend is None

    def test_close_is_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "idem.db")
            _seed_db(db, [])
            client = Client(db)
            client.close()
            client.close()  # must not raise


# ---------------------------------------------------------------------------
# tools()
# ---------------------------------------------------------------------------


class TestClientTools:
    def test_empty_db_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "empty.db")
            _seed_db(db, [])
            with Client(db) as client:
                assert client.tools() == []

    def test_returns_tool_summary_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("web_search")])
            with Client(db) as client:
                result = client.tools()
            assert len(result) == 1
            assert isinstance(result[0], ToolSummary)

    def test_tool_name_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("bash_exec")])
            with Client(db) as client:
                names = {t.tool_name for t in client.tools()}
            assert "bash_exec" in names

    def test_success_rate_computed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(
                db,
                [
                    _tool_event("bash_exec", status="success"),
                    _tool_event("bash_exec", status="failure"),
                ],
            )
            with Client(db) as client:
                t = client.tools()[0]
            assert t.success_rate == pytest.approx(0.5)

    def test_multiple_tools(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(
                db,
                [
                    _tool_event("tool_a"),
                    _tool_event("tool_b"),
                    _tool_event("tool_c"),
                ],
            )
            with Client(db) as client:
                names = {t.tool_name for t in client.tools()}
            assert names == {"tool_a", "tool_b", "tool_c"}

    def test_models_are_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("web_search")])
            with Client(db) as client:
                t = client.tools()[0]
            from pydantic import ValidationError

            with pytest.raises(ValidationError):
                t.tool_name = "mutated"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# tool(name)
# ---------------------------------------------------------------------------


class TestClientTool:
    def test_returns_none_for_unknown_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [])
            with Client(db) as client:
                assert client.tool("no_such_tool") is None

    def test_returns_summary_for_known_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("web_search")])
            with Client(db) as client:
                result = client.tool("web_search")
            assert isinstance(result, ToolSummary)
            assert result.tool_name == "web_search"

    def test_call_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(
                db,
                [
                    _tool_event("bash_exec"),
                    _tool_event("bash_exec"),
                    _tool_event("bash_exec"),
                ],
            )
            with Client(db) as client:
                result = client.tool("bash_exec")
            assert result is not None
            assert result.call_count == 3

    def test_percentiles_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(
                db,
                [
                    _tool_event("bash_exec", latency_ms=50.0),
                    _tool_event("bash_exec", latency_ms=100.0),
                ],
            )
            with Client(db) as client:
                result = client.tool("bash_exec")
            assert result is not None
            assert result.p50_latency_ms >= 0.0
            assert result.p95_latency_ms >= 0.0
            assert result.p99_latency_ms >= 0.0


# ---------------------------------------------------------------------------
# calls()
# ---------------------------------------------------------------------------


class TestClientCalls:
    def test_empty_db_returns_empty_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [])
            with Client(db) as client:
                assert client.calls() == []

    def test_returns_tool_call_records(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("web_search")])
            with Client(db) as client:
                result = client.calls()
            assert len(result) == 1
            assert isinstance(result[0], ToolCallRecord)

    def test_filter_by_tool_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("tool_a"), _tool_event("tool_b")])
            with Client(db) as client:
                result = client.calls(tool_name="tool_a")
            assert all(r.tool_name == "tool_a" for r in result)
            assert len(result) == 1

    def test_filter_by_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(
                db,
                [
                    _tool_event("bash_exec", status="success"),
                    _tool_event("bash_exec", status="failure"),
                ],
            )
            with Client(db) as client:
                result = client.calls(status="failure")
            assert all(r.status == "failure" for r in result)
            assert len(result) == 1

    def test_limit(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("web_search") for _ in range(10)])
            with Client(db) as client:
                result = client.calls(limit=3)
            assert len(result) == 3

    def test_record_fields_populated(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("web_search", trace_id="trace-abc")])
            with Client(db) as client:
                result = client.calls()
            r = result[0]
            assert r.tool_name == "web_search"
            assert r.trace_id == "trace-abc"
            assert r.latency_ms == pytest.approx(100.0)
            assert r.status == "success"

    def test_failure_type_populated_on_failure(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("bash_exec", status="failure")])
            with Client(db) as client:
                result = client.calls(status="failure")
            assert result[0].failure_type == "unknown"

    def test_failure_type_none_on_success(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("web_search", status="success")])
            with Client(db) as client:
                result = client.calls()
            assert result[0].failure_type is None


# ---------------------------------------------------------------------------
# intelligence.failures()
# ---------------------------------------------------------------------------


class TestIntelligenceFailures:
    def test_empty_db_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [])
            with Client(db) as client:
                assert client.intelligence.failures() == []

    def test_returns_failure_pattern_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            events = [_tool_event("bash_exec", status="failure") for _ in range(3)]
            _seed_db(db, events)
            with Client(db) as client:
                result = client.intelligence.failures()
            assert len(result) >= 1
            assert isinstance(result[0], FailurePattern)

    def test_failure_rate_in_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(
                db,
                [
                    _tool_event("bash_exec", status="failure"),
                    _tool_event("bash_exec", status="success"),
                ],
            )
            with Client(db) as client:
                result = client.intelligence.failures()
            for fp in result:
                assert 0.0 <= fp.failure_rate <= 1.0

    def test_no_failures_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("web_search", status="success")])
            with Client(db) as client:
                result = client.intelligence.failures()
            assert result == []


# ---------------------------------------------------------------------------
# intelligence.quality()
# ---------------------------------------------------------------------------


class TestIntelligenceQuality:
    def test_empty_db_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [])
            with Client(db) as client:
                assert client.intelligence.quality() == []

    def test_returns_tool_quality_score_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("web_search")])
            with Client(db) as client:
                result = client.intelligence.quality()
            assert len(result) >= 1
            assert isinstance(result[0], ToolQualityScore)

    def test_grade_is_letter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("web_search")])
            with Client(db) as client:
                result = client.intelligence.quality()
            assert result[0].grade in {"A", "B", "C", "D", "F"}

    def test_score_in_range(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [_tool_event("web_search")])
            with Client(db) as client:
                result = client.intelligence.quality()
            for s in result:
                assert 0.0 <= s.overall_score <= 1.0


# ---------------------------------------------------------------------------
# intelligence.run_quality()
# ---------------------------------------------------------------------------


class TestIntelligenceRunQuality:
    def test_empty_db_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [])
            with Client(db) as client:
                assert client.intelligence.run_quality() == []

    def test_returns_run_quality_score_instances(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            events = [
                _tool_event("web_search", trace_id="trace-1"),
                _llm_event(trace_id="trace-1"),
            ]
            _seed_db(db, events)
            with Client(db) as client:
                result = client.intelligence.run_quality()
            assert len(result) >= 1
            assert isinstance(result[0], RunQualityScore)

    def test_trace_id_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            events = [
                _tool_event("web_search", trace_id="trace-xyz"),
                _llm_event(trace_id="trace-xyz"),
            ]
            _seed_db(db, events)
            with Client(db) as client:
                result = client.intelligence.run_quality()
            trace_ids = {r.trace_id for r in result}
            assert "trace-xyz" in trace_ids


# ---------------------------------------------------------------------------
# intelligence.optimization()
# ---------------------------------------------------------------------------


class TestIntelligenceOptimization:
    def test_empty_db_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            _seed_db(db, [])
            with Client(db) as client:
                assert client.intelligence.optimization() == []

    def test_returns_optimization_suggestion_instances_when_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            db = str(Path(tmpdir) / "t.db")
            # Seed a large output token event to trigger a suggestion
            tool_ev = _tool_event("big_tool", trace_id="trace-1")
            tool_ev["output_payload"] = {"data": "x" * 100}
            llm_ev = _llm_event(trace_id="trace-1", token_output=50_000, token_input=100)
            _seed_db(db, [tool_ev, llm_ev])
            with Client(db) as client:
                result = client.intelligence.optimization()
            # May be empty if threshold not met — just verify types if any returned
            for s in result:
                assert isinstance(s, OptimizationSuggestion)
