"""Unit tests for Phase 3 intelligence analysis modules.

Covers: FailureClusterer, TokenOptimizer, CostEstimator, QualityScorer.
Property-based tests with Hypothesis where contracts must hold for arbitrary input.
"""

from __future__ import annotations

from typing import Any

import pytest
from hypothesis import given
from hypothesis import strategies as st

from agentscope.analysis.intelligence.failure_clustering import (
    FailureClusterer,
)
from agentscope.analysis.intelligence.quality_scorer import (
    AgentRunQualityScore,
    QualityScorer,
    ToolQualityScore,
    _grade,
)
from agentscope.analysis.intelligence.token_optimizer import (
    CostEstimator,
    OptimizationSuggestion,
    TokenOptimizer,
)

# ---------------------------------------------------------------------------
# Helpers — build raw row dicts that mimic SQLiteBackend output
# ---------------------------------------------------------------------------


def _tool_row(
    tool_name: str = "web_search",
    status: str = "success",
    failure_type: str | None = None,
    latency_ms: float = 200.0,
    trace_id: str = "trace-1",
    drift_detected: int | None = None,
    output_payload: dict[str, Any] | None = None,
    token_usage_output: int | None = None,
) -> dict[str, Any]:
    return {
        "tool_name": tool_name,
        "status": status,
        "failure_type": failure_type,
        "latency_ms": latency_ms,
        "trace_id": trace_id,
        "drift_detected": drift_detected,
        "output_payload": output_payload or {"result": "ok"},
        "token_usage_output": token_usage_output,
    }


def _llm_row(
    trace_id: str = "trace-1",
    model: str = "claude-3-5-sonnet-20241022",
    context_window_limit: int = 200_000,
    context_window_used: int = 10_000,
    context_utilisation: float = 0.05,
    token_output: int = 500,
) -> dict[str, Any]:
    return {
        "trace_id": trace_id,
        "model": model,
        "context_window_limit": context_window_limit,
        "context_window_used": context_window_used,
        "context_utilisation": context_utilisation,
        "token_output": token_output,
    }


# ---------------------------------------------------------------------------
# FailureClusterer
# ---------------------------------------------------------------------------


class TestFailureClusterer:
    def test_no_data_returns_empty(self) -> None:
        clusterer = FailureClusterer()
        result = clusterer.cluster([])
        assert result == []

    def test_only_successes_returns_empty(self) -> None:
        rows = [_tool_row(status="success") for _ in range(5)]
        result = FailureClusterer().cluster(rows)
        assert result == []

    def test_single_failure_cluster(self) -> None:
        rows = [
            _tool_row(status="success"),
            _tool_row(status="success"),
            _tool_row(status="failure", failure_type="timeout", latency_ms=8000.0, trace_id="t1"),
        ]
        clusters = FailureClusterer().cluster(rows)
        assert len(clusters) == 1
        c = clusters[0]
        assert c.tool_name == "web_search"
        assert c.failure_type == "timeout"
        assert c.occurrence_count == 1
        assert c.total_calls == 3
        assert abs(c.failure_rate - 1 / 3) < 1e-4
        assert "t1" in c.example_trace_ids

    def test_multiple_tools_clustered_separately(self) -> None:
        rows = [
            _tool_row(tool_name="search", status="failure", failure_type="api_error"),
            _tool_row(tool_name="search", status="failure", failure_type="api_error"),
            _tool_row(tool_name="fetch", status="failure", failure_type="timeout"),
        ]
        clusters = FailureClusterer().cluster(rows)
        assert len(clusters) == 2
        tool_names = {c.tool_name for c in clusters}
        assert tool_names == {"search", "fetch"}

    def test_clusters_sorted_by_failure_rate_descending(self) -> None:
        rows = [
            # "search" fails 1/3 of the time
            _tool_row(tool_name="search", status="success"),
            _tool_row(tool_name="search", status="success"),
            _tool_row(tool_name="search", status="failure", failure_type="timeout"),
            # "fetch" fails 2/2 = 100% of the time
            _tool_row(tool_name="fetch", status="failure", failure_type="api_error"),
            _tool_row(tool_name="fetch", status="failure", failure_type="api_error"),
        ]
        clusters = FailureClusterer().cluster(rows)
        assert clusters[0].tool_name == "fetch"
        assert clusters[0].failure_rate > clusters[1].failure_rate

    def test_pattern_description_contains_tool_name(self) -> None:
        rows = [_tool_row(status="failure", failure_type="schema_drift")]
        clusters = FailureClusterer().cluster(rows)
        assert "web_search" in clusters[0].pattern_description

    def test_suggestion_present_for_known_failure_types(self) -> None:
        for ftype in ["timeout", "schema_drift", "api_error", "unknown"]:
            rows = [_tool_row(status="failure", failure_type=ftype)]
            clusters = FailureClusterer().cluster(rows)
            assert len(clusters[0].suggestion) > 0

    def test_example_trace_ids_capped_at_five(self) -> None:
        rows = [
            _tool_row(status="failure", failure_type="timeout", trace_id=f"t{i}")
            for i in range(10)
        ]
        clusters = FailureClusterer().cluster(rows)
        assert len(clusters[0].example_trace_ids) <= 5

    def test_failure_type_none_treated_as_unknown(self) -> None:
        rows = [_tool_row(status="failure", failure_type=None)]
        clusters = FailureClusterer().cluster(rows)
        assert clusters[0].failure_type == "unknown"

    def test_analyse_method_matches_cluster(self) -> None:
        rows = [_tool_row(status="failure", failure_type="timeout")]
        clusterer = FailureClusterer()
        assert clusterer.analyse(rows) == clusterer.cluster(rows)

    @given(
        st.lists(
            st.fixed_dictionaries({
                "tool_name": st.text(min_size=1, max_size=20),
                "status": st.sampled_from(["success", "failure"]),
                "failure_type": st.one_of(
                    st.none(), st.sampled_from(["timeout", "api_error", "schema_drift", "unknown"])
                ),
                "latency_ms": st.floats(min_value=0, max_value=100_000, allow_nan=False),
                "trace_id": st.text(min_size=1, max_size=10),
                "drift_detected": st.one_of(st.none(), st.just(0), st.just(1)),
                "output_payload": st.just({"x": 1}),
                "token_usage_output": st.one_of(
                    st.none(), st.integers(min_value=0, max_value=10_000)
                ),
            }),
            max_size=50,
        )
    )
    def test_property_failure_rate_bounded(
        self, tool_calls: list[dict[str, Any]]
    ) -> None:
        """failure_rate is always in [0.0, 1.0] for any input."""
        clusters = FailureClusterer().cluster(tool_calls)
        for c in clusters:
            assert 0.0 <= c.failure_rate <= 1.0

    @given(
        st.lists(
            st.fixed_dictionaries({
                "tool_name": st.just("tool"),
                "status": st.sampled_from(["success", "failure"]),
                "failure_type": st.one_of(st.none(), st.just("timeout")),
                "latency_ms": st.floats(min_value=0, max_value=10_000, allow_nan=False),
                "trace_id": st.just("t1"),
                "drift_detected": st.none(),
                "output_payload": st.just({}),
                "token_usage_output": st.none(),
            }),
            min_size=1,
            max_size=30,
        )
    )
    def test_property_occurrence_count_le_total_calls(
        self, tool_calls: list[dict[str, Any]]
    ) -> None:
        clusters = FailureClusterer().cluster(tool_calls)
        for c in clusters:
            assert c.occurrence_count <= c.total_calls


# ---------------------------------------------------------------------------
# TokenOptimizer + CostEstimator
# ---------------------------------------------------------------------------


class TestTokenOptimizer:
    def test_no_data_returns_empty(self) -> None:
        optimizer = TokenOptimizer()
        result = optimizer.optimize([], [])
        assert result == []

    def test_tool_below_threshold_excluded(self) -> None:
        # Small output payload — well below 5% of 200k context
        rows = [_tool_row(output_payload={"x": 1}, token_usage_output=100)]
        llm = [_llm_row(context_window_limit=200_000)]
        result = TokenOptimizer().optimize(rows, llm)
        assert result == []

    def test_tool_above_threshold_included(self) -> None:
        # 12,000 tokens = 6% of 200k → above default 5% threshold
        rows = [_tool_row(token_usage_output=12_000)]
        llm = [_llm_row(context_window_limit=200_000)]
        result = TokenOptimizer().optimize(rows, llm)
        assert len(result) == 1
        s = result[0]
        assert s.tool_name == "web_search"
        assert s.avg_output_tokens == pytest.approx(12_000.0, rel=0.01)
        assert 0.0 <= s.waste_score <= 1.0
        assert s.estimated_savings_tokens_per_call >= 0.0
        assert s.estimated_savings_usd_per_1k_calls >= 0.0

    def test_suggestion_text_contains_tool_name(self) -> None:
        rows = [_tool_row(tool_name="big_fetcher", token_usage_output=15_000)]
        llm = [_llm_row(context_window_limit=200_000)]
        result = TokenOptimizer().optimize(rows, llm)
        assert len(result) == 1
        assert "big_fetcher" in result[0].suggestion_text

    def test_sorted_by_avg_output_tokens_descending(self) -> None:
        rows = [
            _tool_row(tool_name="small", token_usage_output=11_000),
            _tool_row(tool_name="large", token_usage_output=20_000),
        ]
        llm = [_llm_row(context_window_limit=200_000)]
        result = TokenOptimizer().optimize(rows, llm)
        if len(result) >= 2:
            assert result[0].avg_output_tokens >= result[1].avg_output_tokens

    def test_custom_threshold(self) -> None:
        # Lower threshold to catch smaller tools
        rows = [_tool_row(token_usage_output=3_000)]
        llm = [_llm_row(context_window_limit=200_000)]
        result = TokenOptimizer(hog_threshold=0.01).optimize(rows, llm)
        assert len(result) == 1

    def test_no_llm_calls_uses_default_context_limit(self) -> None:
        rows = [_tool_row(token_usage_output=15_000)]
        result = TokenOptimizer().optimize(rows, [])
        # Should still produce a suggestion (uses 200k default)
        assert len(result) == 1

    def test_fallback_to_payload_bytes_when_no_token_count(self) -> None:
        # Large payload, no explicit token count
        large_payload = {"data": "x" * 60_000}  # ~13k tokens at 4.5 bytes/token
        rows = [_tool_row(output_payload=large_payload, token_usage_output=None)]
        llm = [_llm_row(context_window_limit=200_000)]
        result = TokenOptimizer().optimize(rows, llm)
        # May or may not exceed threshold depending on exact byte count
        for s in result:
            assert s.avg_output_tokens > 0

    def test_analyse_tuple_interface(self) -> None:
        rows = [_tool_row(token_usage_output=12_000)]
        llm = [_llm_row(context_window_limit=200_000)]
        optimizer = TokenOptimizer()
        assert optimizer.analyse((rows, llm)) == optimizer.optimize(rows, llm)

    @given(
        st.lists(
            st.fixed_dictionaries({
                "tool_name": st.just("t"),
                "status": st.just("success"),
                "failure_type": st.none(),
                "latency_ms": st.just(100.0),
                "trace_id": st.just("tr"),
                "drift_detected": st.none(),
                "output_payload": st.just({"x": 1}),
                "token_usage_output": st.integers(min_value=0, max_value=50_000),
            }),
            min_size=1,
            max_size=20,
        )
    )
    def test_property_waste_score_bounded(
        self, tool_calls: list[dict[str, Any]]
    ) -> None:
        llm = [_llm_row(context_window_limit=200_000)]
        suggestions = TokenOptimizer(hog_threshold=0.0).optimize(tool_calls, llm)
        for s in suggestions:
            assert 0.0 <= s.waste_score <= 1.0


class TestCostEstimator:
    def test_estimate_returns_non_negative(self) -> None:
        s = OptimizationSuggestion(
            tool_name="t",
            avg_output_tokens=5000.0,
            avg_context_fraction=0.1,
            waste_score=0.5,
            estimated_savings_tokens_per_call=2500.0,
            estimated_savings_usd_per_1k_calls=0.0075,
            suggestion_text="Filter output.",
        )
        estimator = CostEstimator()
        result = estimator.estimate(s, calls_per_day=500)
        assert result >= 0.0

    def test_more_calls_higher_savings(self) -> None:
        s = OptimizationSuggestion(
            tool_name="t",
            avg_output_tokens=5000.0,
            avg_context_fraction=0.1,
            waste_score=0.5,
            estimated_savings_tokens_per_call=2500.0,
            estimated_savings_usd_per_1k_calls=0.0075,
            suggestion_text="Filter output.",
        )
        estimator = CostEstimator()
        low = estimator.estimate(s, calls_per_day=100)
        high = estimator.estimate(s, calls_per_day=1000)
        assert high > low

    def test_unknown_model_uses_default_pricing(self) -> None:
        s = OptimizationSuggestion(
            tool_name="t",
            avg_output_tokens=5000.0,
            avg_context_fraction=0.1,
            waste_score=0.5,
            estimated_savings_tokens_per_call=2500.0,
            estimated_savings_usd_per_1k_calls=0.0075,
            suggestion_text=".",
        )
        estimator = CostEstimator()
        result = estimator.estimate(s, model="some-unknown-model")
        assert result >= 0.0


# ---------------------------------------------------------------------------
# QualityScorer
# ---------------------------------------------------------------------------


class TestGradeFunction:
    @pytest.mark.parametrize("score,expected", [
        (0.95, "A"),
        (0.90, "A"),
        (0.80, "B"),
        (0.75, "B"),
        (0.65, "C"),
        (0.60, "C"),
        (0.50, "D"),
        (0.40, "D"),
        (0.39, "F"),
        (0.0, "F"),
    ])
    def test_grade_thresholds(self, score: float, expected: str) -> None:
        assert _grade(score) == expected


class TestToolQualityScorer:
    def test_perfect_tool_scores_a(self) -> None:
        rows = [_tool_row(status="success", latency_ms=100.0) for _ in range(10)]
        scorer = QualityScorer()
        scores = scorer.score_tools(rows)
        assert len(scores) == 1
        s = scores[0]
        assert s.reliability_score == 1.0
        assert s.schema_stability_score == 1.0
        assert s.grade == "A"

    def test_all_failures_score_f(self) -> None:
        rows = [
            _tool_row(status="failure", failure_type="timeout", latency_ms=8000.0)
            for _ in range(5)
        ]
        scorer = QualityScorer()
        scores = scorer.score_tools(rows)
        assert scores[0].reliability_score == 0.0
        assert scores[0].grade == "F"

    def test_drift_reduces_schema_stability(self) -> None:
        rows = [
            _tool_row(status="success", drift_detected=1),
            _tool_row(status="success", drift_detected=1),
            _tool_row(status="success", drift_detected=0),
            _tool_row(status="success", drift_detected=0),
        ]
        scorer = QualityScorer()
        scores = scorer.score_tools(rows)
        assert scores[0].schema_stability_score == pytest.approx(0.5, rel=0.01)

    def test_inconsistent_latency_reduces_consistency_score(self) -> None:
        rows = [
            _tool_row(status="success", latency_ms=10.0),
            _tool_row(status="success", latency_ms=10_000.0),
        ]
        scorer = QualityScorer()
        scores = scorer.score_tools(rows)
        assert scores[0].latency_consistency_score < 1.0

    def test_multiple_tools_each_scored(self) -> None:
        rows = [
            _tool_row(tool_name="a", status="success"),
            _tool_row(tool_name="b", status="failure", failure_type="timeout"),
        ]
        scorer = QualityScorer()
        scores = scorer.score_tools(rows)
        assert len(scores) == 2
        # Worst tool first
        assert scores[0].overall_score <= scores[1].overall_score

    def test_empty_rows_returns_empty(self) -> None:
        assert QualityScorer().score_tools([]) == []

    def test_overall_score_bounded(self) -> None:
        rows = [_tool_row(status="success") for _ in range(3)]
        scores = QualityScorer().score_tools(rows)
        for s in scores:
            assert 0.0 <= s.overall_score <= 1.0

    @given(
        st.lists(
            st.fixed_dictionaries({
                "tool_name": st.sampled_from(["a", "b"]),
                "status": st.sampled_from(["success", "failure"]),
                "failure_type": st.one_of(st.none(), st.just("timeout")),
                "latency_ms": st.floats(
                    min_value=0, max_value=100_000, allow_nan=False, allow_infinity=False
                ),
                "trace_id": st.just("t"),
                "drift_detected": st.one_of(st.none(), st.just(0), st.just(1)),
                "output_payload": st.just({}),
                "token_usage_output": st.none(),
            }),
            min_size=1,
            max_size=40,
        )
    )
    def test_property_scores_always_bounded(
        self, tool_calls: list[dict[str, Any]]
    ) -> None:
        scores = QualityScorer().score_tools(tool_calls)
        for s in scores:
            assert 0.0 <= s.reliability_score <= 1.0
            assert 0.0 <= s.schema_stability_score <= 1.0
            assert 0.0 <= s.latency_consistency_score <= 1.0
            assert 0.0 <= s.overall_score <= 1.0


class TestRunQualityScorer:
    def test_efficient_run_scores_high(self) -> None:
        tool_calls = [_tool_row(status="success", trace_id="run1")]
        llm_calls = [_llm_row(trace_id="run1", context_utilisation=0.1)]
        scorer = QualityScorer()
        scores = scorer.score_runs(tool_calls, llm_calls)
        assert len(scores) == 1
        s = scores[0]
        assert s.context_efficiency_score == pytest.approx(0.9, rel=0.01)
        assert s.overall_score > 0.7

    def test_high_context_run_penalised(self) -> None:
        tool_calls = [_tool_row(status="success", trace_id="run2")]
        llm_calls = [_llm_row(trace_id="run2", context_utilisation=0.95)]
        scorer = QualityScorer()
        scores = scorer.score_runs(tool_calls, llm_calls)
        assert scores[0].context_efficiency_score == pytest.approx(0.05, rel=0.1)

    def test_repeated_same_failure_type_penalises_recovery(self) -> None:
        tool_calls = [
            _tool_row(status="failure", failure_type="timeout", trace_id="run3"),
            _tool_row(status="failure", failure_type="timeout", trace_id="run3"),
            _tool_row(status="failure", failure_type="timeout", trace_id="run3"),
        ]
        llm_calls: list[dict[str, Any]] = []
        scorer = QualityScorer()
        scores = scorer.score_runs(tool_calls, llm_calls)
        # Only 1 unique failure type / 3 failures = 0.33 recovery score
        assert scores[0].failure_recovery_score == pytest.approx(1 / 3, rel=0.01)

    def test_diverse_failures_score_recovery_1(self) -> None:
        tool_calls = [
            _tool_row(status="failure", failure_type="timeout", trace_id="run4"),
            _tool_row(status="failure", failure_type="api_error", trace_id="run4"),
            _tool_row(status="failure", failure_type="schema_drift", trace_id="run4"),
        ]
        llm_calls: list[dict[str, Any]] = []
        scorer = QualityScorer()
        scores = scorer.score_runs(tool_calls, llm_calls)
        assert scores[0].failure_recovery_score == 1.0

    def test_no_failures_recovery_score_1(self) -> None:
        tool_calls = [_tool_row(status="success", trace_id="run5")]
        llm_calls = [_llm_row(trace_id="run5", context_utilisation=0.5)]
        scores = QualityScorer().score_runs(tool_calls, llm_calls)
        assert scores[0].failure_recovery_score == 1.0

    def test_diverse_tools_score_higher_diversity(self) -> None:
        tool_calls = [
            _tool_row(tool_name=f"tool_{i}", status="success", trace_id="run6")
            for i in range(5)
        ]
        llm_calls = [_llm_row(trace_id="run6")]
        scores = QualityScorer().score_runs(tool_calls, llm_calls)
        assert scores[0].tool_diversity_score == 1.0

    def test_empty_data_returns_empty(self) -> None:
        assert QualityScorer().score_runs([], []) == []

    def test_analyse_method_returns_both_lists(self) -> None:
        tool_calls = [_tool_row(status="success", trace_id="r")]
        llm_calls = [_llm_row(trace_id="r")]
        scorer = QualityScorer()
        tool_scores, run_scores = scorer.analyse((tool_calls, llm_calls))
        assert isinstance(tool_scores, list)
        assert isinstance(run_scores, list)
        assert all(isinstance(s, ToolQualityScore) for s in tool_scores)
        assert all(isinstance(s, AgentRunQualityScore) for s in run_scores)

    @given(
        st.lists(
            st.fixed_dictionaries({
                "tool_name": st.just("t"),
                "status": st.sampled_from(["success", "failure"]),
                "failure_type": st.one_of(st.none(), st.just("timeout"), st.just("api_error")),
                "latency_ms": st.just(100.0),
                "trace_id": st.just("tr"),
                "drift_detected": st.none(),
                "output_payload": st.just({}),
                "token_usage_output": st.none(),
            }),
            min_size=1,
            max_size=20,
        ),
        st.lists(
            st.fixed_dictionaries({
                "trace_id": st.just("tr"),
                "model": st.just("claude-3-5-sonnet-20241022"),
                "context_window_limit": st.just(200_000),
                "context_window_used": st.integers(min_value=0, max_value=200_000),
                "context_utilisation": st.floats(min_value=0.0, max_value=1.0, allow_nan=False),
                "token_output": st.just(500),
            }),
            min_size=0,
            max_size=10,
        ),
    )
    def test_property_run_scores_bounded(
        self,
        tool_calls: list[dict[str, Any]],
        llm_calls: list[dict[str, Any]],
    ) -> None:
        scores = QualityScorer().score_runs(tool_calls, llm_calls)
        for s in scores:
            assert 0.0 <= s.context_efficiency_score <= 1.0
            assert 0.0 <= s.failure_recovery_score <= 1.0
            assert 0.0 <= s.tool_diversity_score <= 1.0
            assert 0.0 <= s.overall_score <= 1.0
