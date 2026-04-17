"""Unit tests for ReportGenerator."""

from __future__ import annotations

import json

import pytest

from anjor.analysis.report import AssertionResult, ReportData, ReportGenerator


@pytest.fixture()
def gen() -> ReportGenerator:
    return ReportGenerator()


@pytest.fixture()
def sample_tools() -> list[dict]:
    return [
        {
            "tool_name": "web_search",
            "call_count": 10,
            "success_count": 8,
            "failure_count": 2,
            "p95_latency_ms": 2100.0,
            "p50_latency_ms": 800.0,
            "p99_latency_ms": 3000.0,
            "avg_latency_ms": 900.0,
        },
        {
            "tool_name": "read_file",
            "call_count": 30,
            "success_count": 30,
            "failure_count": 0,
            "p95_latency_ms": 350.0,
            "p50_latency_ms": 100.0,
            "p99_latency_ms": 500.0,
            "avg_latency_ms": 120.0,
        },
    ]


@pytest.fixture()
def sample_llm() -> list[dict]:
    return [
        {
            "model": "claude-sonnet-4-6",
            "call_count": 5,
            "total_token_input": 10000,
            "total_token_output": 2000,
            "total_cache_read": 0,
            "total_cache_write": 0,
            "avg_context_utilisation": 0.4,
        }
    ]


class TestReportGenerator:
    def test_generate_aggregates_correctly(
        self, gen: ReportGenerator, sample_tools: list[dict], sample_llm: list[dict]
    ) -> None:
        data = gen.generate(sample_tools, sample_llm, since_minutes=120, project=None)
        assert data.total_calls == 40
        assert data.success_count == 38
        assert data.failure_count == 2
        assert data.success_rate == pytest.approx(38 / 40)
        assert data.p95_latency_ms == 2100.0
        assert data.total_cost_usd > 0

    def test_generate_empty_tools(self, gen: ReportGenerator) -> None:
        data = gen.generate([], [], since_minutes=60, project=None)
        assert data.total_calls == 0
        assert data.success_rate == 1.0
        assert data.p95_latency_ms == 0.0
        assert data.total_cost_usd == 0.0

    def test_generate_no_calls_success_rate_is_one(self, gen: ReportGenerator) -> None:
        tools = [
            {
                "tool_name": "x",
                "call_count": 0,
                "success_count": 0,
                "failure_count": 0,
                "p95_latency_ms": 0.0,
            }
        ]
        data = gen.generate(tools, [], since_minutes=60, project=None)
        assert data.success_rate == 1.0

    def test_generate_project_propagated(
        self, gen: ReportGenerator, sample_tools: list[dict]
    ) -> None:
        data = gen.generate(sample_tools, [], since_minutes=30, project="myapp")
        assert data.project == "myapp"
        assert data.since_minutes == 30

    def test_per_tool_breakdown(self, gen: ReportGenerator, sample_tools: list[dict]) -> None:
        data = gen.generate(sample_tools, [], since_minutes=120, project=None)
        assert len(data.per_tool) == 2
        names = {t["tool_name"] for t in data.per_tool}
        assert names == {"web_search", "read_file"}

    def test_per_tool_success_rate_computed(
        self, gen: ReportGenerator, sample_tools: list[dict]
    ) -> None:
        data = gen.generate(sample_tools, [], since_minutes=120, project=None)
        ws = next(t for t in data.per_tool if t["tool_name"] == "web_search")
        assert ws["success_rate"] == pytest.approx(0.8)

    def test_supports_dataclass_objects(self, gen: ReportGenerator) -> None:
        from anjor.collector.storage.base import ToolSummary

        tool = ToolSummary(
            tool_name="bash",
            call_count=5,
            success_count=4,
            failure_count=1,
            avg_latency_ms=200.0,
            p50_latency_ms=180.0,
            p95_latency_ms=400.0,
            p99_latency_ms=500.0,
        )
        data = gen.generate([tool], [], since_minutes=60, project=None)
        assert data.total_calls == 5
        assert data.p95_latency_ms == 400.0


class TestEvaluateAssertions:
    def _data(self, **overrides: float) -> ReportData:
        defaults: dict = {  # type: ignore
            "total_calls": 40,
            "success_count": 38,
            "failure_count": 2,
            "success_rate": 0.95,
            "p95_latency_ms": 1500.0,
            "total_cost_usd": 0.50,
            "since_minutes": 120,
            "project": None,
        }
        defaults.update(overrides)
        return ReportData(**defaults)

    def test_success_rate_ge_pass(self, gen: ReportGenerator) -> None:
        results = gen.evaluate_assertions(["success_rate >= 0.95"], self._data(success_rate=0.95))
        assert results[0].passed is True

    def test_success_rate_ge_fail(self, gen: ReportGenerator) -> None:
        results = gen.evaluate_assertions(["success_rate >= 0.95"], self._data(success_rate=0.90))
        assert results[0].passed is False

    def test_p95_latency_le_pass(self, gen: ReportGenerator) -> None:
        results = gen.evaluate_assertions(
            ["p95_latency_ms <= 3000"], self._data(p95_latency_ms=2000.0)
        )
        assert results[0].passed is True

    def test_p95_latency_le_fail(self, gen: ReportGenerator) -> None:
        results = gen.evaluate_assertions(
            ["p95_latency_ms <= 3000"], self._data(p95_latency_ms=4000.0)
        )
        assert results[0].passed is False

    def test_failure_count_le_pass(self, gen: ReportGenerator) -> None:
        results = gen.evaluate_assertions(["failure_count <= 5"], self._data(failure_count=2))
        assert results[0].passed is True

    def test_total_cost_usd_le_pass(self, gen: ReportGenerator) -> None:
        results = gen.evaluate_assertions(
            ["total_cost_usd <= 1.00"], self._data(total_cost_usd=0.50)
        )
        assert results[0].passed is True

    def test_multiple_assertions(self, gen: ReportGenerator) -> None:
        data = self._data(success_rate=0.95, p95_latency_ms=1000.0)
        results = gen.evaluate_assertions(
            ["success_rate >= 0.95", "p95_latency_ms <= 2000"],
            data,
        )
        assert len(results) == 2
        assert all(r.passed for r in results)

    def test_invalid_syntax_fails(self, gen: ReportGenerator) -> None:
        results = gen.evaluate_assertions(["not_a_real_expression!"], self._data())
        assert results[0].passed is False
        assert "invalid assertion syntax" in results[0].message

    def test_unknown_metric_fails(self, gen: ReportGenerator) -> None:
        results = gen.evaluate_assertions(["banana >= 1"], self._data())
        assert results[0].passed is False
        assert "unknown metric" in results[0].message

    def test_empty_assertions_returns_empty(self, gen: ReportGenerator) -> None:
        results = gen.evaluate_assertions([], self._data())
        assert results == []

    def test_actual_value_in_result(self, gen: ReportGenerator) -> None:
        data = self._data(success_rate=0.87)
        results = gen.evaluate_assertions(["success_rate >= 0.95"], data)
        assert results[0].actual == pytest.approx(0.87)


class TestFormatText:
    def _make(self, **kw: object) -> ReportData:
        return ReportData(
            total_calls=kw.get("total_calls", 40),  # type: ignore[arg-type]
            success_count=kw.get("success_count", 38),  # type: ignore[arg-type]
            failure_count=kw.get("failure_count", 2),  # type: ignore[arg-type]
            success_rate=kw.get("success_rate", 0.95),  # type: ignore[arg-type]
            p95_latency_ms=kw.get("p95_latency_ms", 1500.0),  # type: ignore[arg-type]
            total_cost_usd=kw.get("total_cost_usd", 0.50),  # type: ignore[arg-type]
            since_minutes=kw.get("since_minutes", 120),  # type: ignore[arg-type]
            project=kw.get("project", None),  # type: ignore[arg-type]
            per_tool=kw.get("per_tool", []),  # type: ignore[arg-type]
        )

    def test_header_contains_window(self, gen: ReportGenerator) -> None:
        out = gen.format_text(self._make(since_minutes=120), [])
        assert "last 2h" in out

    def test_header_minutes_under_60(self, gen: ReportGenerator) -> None:
        out = gen.format_text(self._make(since_minutes=30), [])
        assert "last 30m" in out

    def test_project_tag_included(self, gen: ReportGenerator) -> None:
        out = gen.format_text(self._make(project="myapp"), [])
        assert "[myapp]" in out

    def test_pass_mark_shown(self, gen: ReportGenerator) -> None:
        a = AssertionResult("success_rate >= 0.95", True, 0.95, "ok")
        out = gen.format_text(self._make(), [a])
        assert "✓" in out

    def test_fail_mark_shown(self, gen: ReportGenerator) -> None:
        a = AssertionResult("success_rate >= 0.95", False, 0.90, "nope")
        out = gen.format_text(self._make(), [a])
        assert "✗" in out


class TestFormatJson:
    def test_valid_json(self, gen: ReportGenerator) -> None:
        data = ReportData(40, 38, 2, 0.95, 1500.0, 0.5, 120, None)
        out = gen.format_json(data, [])
        parsed = json.loads(out)
        assert parsed["summary"]["total_calls"] == 40
        assert parsed["passed"] is True

    def test_failed_assertion_sets_passed_false(self, gen: ReportGenerator) -> None:
        data = ReportData(40, 38, 2, 0.90, 1500.0, 0.5, 120, None)
        a = AssertionResult("success_rate >= 0.95", False, 0.90, "fail")
        out = gen.format_json(data, [a])
        parsed = json.loads(out)
        assert parsed["passed"] is False

    def test_no_assertions_passed_true(self, gen: ReportGenerator) -> None:
        data = ReportData(40, 38, 2, 0.95, 1500.0, 0.5, 120, None)
        out = gen.format_json(data, [])
        assert json.loads(out)["passed"] is True


class TestFormatMarkdown:
    def test_contains_header(self, gen: ReportGenerator) -> None:
        data = ReportData(40, 38, 2, 0.95, 1500.0, 0.5, 120, None)
        out = gen.format_markdown(data, [])
        assert "## Anjor Report" in out

    def test_table_rows_present(self, gen: ReportGenerator) -> None:
        data = ReportData(40, 38, 2, 0.95, 1500.0, 0.5, 120, "proj")
        out = gen.format_markdown(data, [])
        assert "| Calls |" in out
        assert "proj" in out

    def test_assertion_checkmark(self, gen: ReportGenerator) -> None:
        data = ReportData(40, 38, 2, 0.95, 1500.0, 0.5, 120, None)
        a = AssertionResult("success_rate >= 0.95", True, 0.95, "ok")
        out = gen.format_markdown(data, [a])
        assert "✅" in out

    def test_assertion_cross(self, gen: ReportGenerator) -> None:
        data = ReportData(40, 38, 2, 0.90, 1500.0, 0.5, 120, None)
        a = AssertionResult("success_rate >= 0.95", False, 0.90, "fail")
        out = gen.format_markdown(data, [a])
        assert "❌" in out
