"""Unit tests for DiffReport."""

from __future__ import annotations

import json

import pytest

from anjor.analysis.report import (
    DiffData,
    DiffReport,
    ToolDiff,
    WindowMetrics,
    _direction,
)


def _metrics(
    call_count: int = 10,
    success_rate: float = 0.9,
    failure_count: int = 1,
    p50: float = 200.0,
    p95: float = 500.0,
    avg_token: float = 0.0,
) -> WindowMetrics:
    return WindowMetrics(
        call_count=call_count,
        success_rate=success_rate,
        failure_count=failure_count,
        p50_latency_ms=p50,
        p95_latency_ms=p95,
        avg_token_input=avg_token,
    )


@pytest.fixture()
def gen() -> DiffReport:
    return DiffReport()


@pytest.fixture()
def cur_rows() -> list[dict]:
    return [
        {"tool_name": "bash", "status": "success", "latency_ms": 100.0},
        {"tool_name": "bash", "status": "success", "latency_ms": 200.0},
        {"tool_name": "bash", "status": "failure", "latency_ms": 500.0},
        {"tool_name": "web_search", "status": "success", "latency_ms": 800.0},
        {"tool_name": "web_search", "status": "failure", "latency_ms": 1500.0},
    ]


@pytest.fixture()
def pri_rows() -> list[dict]:
    return [
        {"tool_name": "bash", "status": "success", "latency_ms": 120.0},
        {"tool_name": "bash", "status": "success", "latency_ms": 150.0},
        {"tool_name": "bash", "status": "success", "latency_ms": 180.0},
        {"tool_name": "web_search", "status": "success", "latency_ms": 700.0},
        {"tool_name": "web_search", "status": "success", "latency_ms": 900.0},
    ]


class TestHelpers:
    def test_percentile_empty_returns_zero(self) -> None:
        from anjor.analysis.report import _percentile

        assert _percentile([], 50) == 0.0

    def test_window_label_hours_non_day(self) -> None:
        gen = DiffReport()
        assert gen._window_label(120) == "2h"

    def test_window_label_minutes(self) -> None:
        gen = DiffReport()
        assert gen._window_label(45) == "45m"

    def test_window_label_days(self) -> None:
        gen = DiffReport()
        assert gen._window_label(10080) == "7d"


class TestDirection:
    def test_higher_is_better_improved(self) -> None:
        assert _direction(0.95, 0.90, higher_is_better=True) == "↑"

    def test_higher_is_better_regressed(self) -> None:
        assert _direction(0.85, 0.90, higher_is_better=True) == "↓"

    def test_lower_is_better_improved(self) -> None:
        assert _direction(400.0, 500.0, higher_is_better=False) == "↑"

    def test_lower_is_better_regressed(self) -> None:
        assert _direction(600.0, 500.0, higher_is_better=False) == "↓"

    def test_equal_returns_equals(self) -> None:
        assert _direction(1.0, 1.0, higher_is_better=True) == "="


class TestDiffReportGenerate:
    def test_tool_names_from_both_windows(
        self, gen: DiffReport, cur_rows: list[dict], pri_rows: list[dict]
    ) -> None:
        data = gen.generate(cur_rows, pri_rows, 1440, None)
        names = {td.tool_name for td in data.tools}
        assert names == {"bash", "web_search"}

    def test_tool_only_in_current(self, gen: DiffReport) -> None:
        cur = [{"tool_name": "new_tool", "status": "success", "latency_ms": 100.0}]
        data = gen.generate(cur, [], 60, None)
        assert any(td.tool_name == "new_tool" for td in data.tools)
        new_td = next(td for td in data.tools if td.tool_name == "new_tool")
        assert new_td.prior.call_count == 0

    def test_tool_only_in_prior(self, gen: DiffReport) -> None:
        pri = [{"tool_name": "old_tool", "status": "success", "latency_ms": 100.0}]
        data = gen.generate([], pri, 60, None)
        old_td = next(td for td in data.tools if td.tool_name == "old_tool")
        assert old_td.current.call_count == 0

    def test_overall_aggregates_all_rows(
        self, gen: DiffReport, cur_rows: list[dict], pri_rows: list[dict]
    ) -> None:
        data = gen.generate(cur_rows, pri_rows, 1440, None)
        assert data.overall_current.call_count == len(cur_rows)
        assert data.overall_prior.call_count == len(pri_rows)

    def test_success_rate_computed(
        self, gen: DiffReport, cur_rows: list[dict], pri_rows: list[dict]
    ) -> None:
        data = gen.generate(cur_rows, pri_rows, 1440, None)
        # cur: 3 success / 5 total = 0.6
        assert data.overall_current.success_rate == pytest.approx(3 / 5)
        # pri: 5 success / 5 total = 1.0
        assert data.overall_prior.success_rate == pytest.approx(1.0)

    def test_window_minutes_propagated(self, gen: DiffReport) -> None:
        data = gen.generate([], [], 1440, None)
        assert data.window_minutes == 1440

    def test_project_propagated(self, gen: DiffReport) -> None:
        data = gen.generate([], [], 60, "myapp")
        assert data.project == "myapp"

    def test_avg_token_propagated(self, gen: DiffReport) -> None:
        data = gen.generate(
            [], [], 60, None, current_avg_token_input=5000.0, prior_avg_token_input=4000.0
        )
        assert data.overall_current.avg_token_input == 5000.0
        assert data.overall_prior.avg_token_input == 4000.0

    def test_empty_rows_gives_zero_metrics(self, gen: DiffReport) -> None:
        data = gen.generate([], [], 60, None)
        assert data.overall_current.call_count == 0
        assert data.overall_current.success_rate == 0.0


class TestDiffReportFormatText:
    def _data(self, window_minutes: int = 1440, project: str | None = None) -> DiffData:
        cur = _metrics(10, 0.8, 2, 200.0, 500.0)
        pri = _metrics(10, 0.9, 1, 180.0, 400.0)
        td = ToolDiff("bash", cur, pri)
        return DiffData(
            window_minutes=window_minutes,
            project=project,
            tools=[td],
            overall_current=cur,
            overall_prior=pri,
        )

    def test_header_shows_window(self, gen: DiffReport) -> None:
        out = gen.format_text(self._data(1440))
        assert "1d" in out

    def test_header_shows_day_label(self, gen: DiffReport) -> None:
        out = gen.format_text(self._data(10080))
        assert "7d" in out

    def test_header_shows_minutes_under_60(self, gen: DiffReport) -> None:
        out = gen.format_text(self._data(30))
        assert "30m" in out

    def test_project_tag_in_header(self, gen: DiffReport) -> None:
        out = gen.format_text(self._data(1440, "myapp"))
        assert "[myapp]" in out

    def test_tool_name_in_output(self, gen: DiffReport) -> None:
        out = gen.format_text(self._data())
        assert "bash" in out

    def test_direction_indicators_present(self, gen: DiffReport) -> None:
        out = gen.format_text(self._data())
        assert "↓" in out  # success_rate regressed, p95 regressed

    def test_overall_row_present(self, gen: DiffReport) -> None:
        out = gen.format_text(self._data())
        assert "overall" in out

    def test_avg_token_shown_when_nonzero(self, gen: DiffReport) -> None:
        cur = _metrics(avg_token=5000.0)
        pri = _metrics(avg_token=4000.0)
        data = DiffData(1440, None, [], cur, pri)
        out = gen.format_text(data)
        assert "token" in out


class TestDiffReportFormatJson:
    def _data(self) -> DiffData:
        cur = _metrics(10, 0.8, 2, 200.0, 500.0)
        pri = _metrics(10, 0.9, 1, 180.0, 400.0)
        return DiffData(1440, "proj", [ToolDiff("bash", cur, pri)], cur, pri)

    def test_valid_json(self, gen: DiffReport) -> None:
        out = gen.format_json(self._data())
        parsed = json.loads(out)
        assert "overall" in parsed
        assert "tools" in parsed

    def test_tool_in_tools_list(self, gen: DiffReport) -> None:
        out = gen.format_json(self._data())
        parsed = json.loads(out)
        assert parsed["tools"][0]["tool_name"] == "bash"

    def test_window_minutes_present(self, gen: DiffReport) -> None:
        out = gen.format_json(self._data())
        assert json.loads(out)["window_minutes"] == 1440

    def test_project_present(self, gen: DiffReport) -> None:
        out = gen.format_json(self._data())
        assert json.loads(out)["project"] == "proj"


class TestDiffReportFormatMarkdown:
    def _data(self) -> DiffData:
        cur = _metrics(10, 0.8, 2, 200.0, 500.0)
        pri = _metrics(10, 0.9, 1, 180.0, 400.0)
        return DiffData(1440, None, [ToolDiff("bash", cur, pri)], cur, pri)

    def test_header_present(self, gen: DiffReport) -> None:
        out = gen.format_markdown(self._data())
        assert "## Anjor Diff" in out

    def test_table_headers(self, gen: DiffReport) -> None:
        out = gen.format_markdown(self._data())
        assert "| Tool |" in out

    def test_tool_row_in_table(self, gen: DiffReport) -> None:
        out = gen.format_markdown(self._data())
        assert "`bash`" in out

    def test_overall_row_present(self, gen: DiffReport) -> None:
        out = gen.format_markdown(self._data())
        assert "**overall**" in out
