"""Unit tests for RootCauseAdvisor.

Covers: empty input returns [], each hypothesis rule triggers correctly,
confidence ordering, deduplication.
"""

from __future__ import annotations

from anjor.analysis.intelligence.root_cause import Hypothesis, RootCauseAdvisor


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _cluster(
    tool_name: str = "web_search",
    failure_type: str = "timeout",
    occurrence_count: int = 3,
    total_calls: int = 10,
    failure_rate: float = 0.3,
    avg_latency_ms: float = 500.0,
) -> dict:
    return {
        "tool_name": tool_name,
        "failure_type": failure_type,
        "occurrence_count": occurrence_count,
        "total_calls": total_calls,
        "failure_rate": failure_rate,
        "avg_latency_ms": avg_latency_ms,
    }


def _tool_summary(
    tool_name: str = "web_search",
    call_count: int = 20,
    success_rate: float = 0.9,
    avg_latency_ms: float = 200.0,
    p95_latency_ms: float = 400.0,
    drift_rate: float = 0.0,
    avg_context_fraction: float = 0.1,
) -> dict:
    return {
        "tool_name": tool_name,
        "call_count": call_count,
        "success_rate": success_rate,
        "avg_latency_ms": avg_latency_ms,
        "p95_latency_ms": p95_latency_ms,
        "drift_rate": drift_rate,
        "avg_context_fraction": avg_context_fraction,
    }


def _llm_summary(
    model: str = "claude-sonnet-4-6",
    call_count: int = 10,
    avg_context_utilisation: float = 0.5,
    avg_token_input: int = 50_000,
    avg_token_output: int = 1_000,
) -> dict:
    return {
        "model": model,
        "call_count": call_count,
        "avg_context_utilisation": avg_context_utilisation,
        "avg_token_input": avg_token_input,
        "avg_token_output": avg_token_output,
    }


# ---------------------------------------------------------------------------
# Empty input
# ---------------------------------------------------------------------------


class TestEmptyInput:
    def test_all_empty_returns_empty(self) -> None:
        advisor = RootCauseAdvisor()
        assert advisor.generate([], [], []) == []

    def test_no_failures_no_hypotheses(self) -> None:
        tools = [_tool_summary(success_rate=1.0, drift_rate=0.0)]
        llm = [_llm_summary(avg_context_utilisation=0.3)]
        assert RootCauseAdvisor().generate([], tools, llm) == []

    def test_analyse_tuple_interface(self) -> None:
        advisor = RootCauseAdvisor()
        result = advisor.analyse(([], [], []))
        assert result == []

    def test_analyse_delegates_to_generate(self) -> None:
        advisor = RootCauseAdvisor()
        clusters = [_cluster()]
        tools = [_tool_summary()]
        llm = [_llm_summary(avg_context_utilisation=0.8)]
        assert advisor.analyse((clusters, tools, llm)) == advisor.generate(clusters, tools, llm)


# ---------------------------------------------------------------------------
# Rule 1 — Context overload
# ---------------------------------------------------------------------------


class TestContextOverload:
    def test_triggers_when_util_above_threshold_and_failures(self) -> None:
        clusters = [_cluster(occurrence_count=2)]
        llm = [_llm_summary(avg_context_utilisation=0.8)]
        result = RootCauseAdvisor().generate(clusters, [], llm)
        titles = [h.title for h in result]
        assert any("Context window pressure" in t for t in titles)

    def test_does_not_trigger_below_threshold(self) -> None:
        clusters = [_cluster(occurrence_count=2)]
        llm = [_llm_summary(avg_context_utilisation=0.74)]
        result = RootCauseAdvisor().generate(clusters, [], llm)
        assert not any("Context window pressure" in h.title for h in result)

    def test_does_not_trigger_without_failures(self) -> None:
        llm = [_llm_summary(avg_context_utilisation=0.9)]
        result = RootCauseAdvisor().generate([], [], llm)
        assert result == []

    def test_evidence_contains_model_name(self) -> None:
        clusters = [_cluster(occurrence_count=1)]
        llm = [_llm_summary(model="claude-opus-4-6", avg_context_utilisation=0.9)]
        result = RootCauseAdvisor().generate(clusters, [], llm)
        h = next(h for h in result if "Context window pressure" in h.title)
        assert "claude-opus-4-6" in h.evidence

    def test_confidence_is_medium(self) -> None:
        clusters = [_cluster(occurrence_count=1)]
        llm = [_llm_summary(avg_context_utilisation=0.9)]
        result = RootCauseAdvisor().generate(clusters, [], llm)
        h = next(h for h in result if "Context window pressure" in h.title)
        assert h.confidence == "medium"

    def test_picks_worst_model_for_evidence(self) -> None:
        clusters = [_cluster(occurrence_count=1)]
        llm = [
            _llm_summary(model="model-a", avg_context_utilisation=0.76),
            _llm_summary(model="model-b", avg_context_utilisation=0.95),
        ]
        result = RootCauseAdvisor().generate(clusters, [], llm)
        h = next(h for h in result if "Context window pressure" in h.title)
        assert "model-b" in h.evidence


# ---------------------------------------------------------------------------
# Rule 2 — Timeout pattern
# ---------------------------------------------------------------------------


class TestTimeoutPattern:
    def test_triggers_for_timeout_above_10pct(self) -> None:
        clusters = [_cluster(failure_type="timeout", failure_rate=0.15, occurrence_count=3)]
        result = RootCauseAdvisor().generate(clusters, [], [])
        assert any("Timeout pattern" in h.title for h in result)

    def test_does_not_trigger_at_exactly_10pct(self) -> None:
        clusters = [_cluster(failure_type="timeout", failure_rate=0.10)]
        result = RootCauseAdvisor().generate(clusters, [], [])
        assert not any("Timeout pattern" in h.title for h in result)

    def test_does_not_trigger_for_non_timeout_type(self) -> None:
        clusters = [_cluster(failure_type="api_error", failure_rate=0.5)]
        result = RootCauseAdvisor().generate(clusters, [], [])
        assert not any("Timeout pattern" in h.title for h in result)

    def test_confidence_is_high(self) -> None:
        clusters = [_cluster(failure_type="timeout", failure_rate=0.2, occurrence_count=2)]
        result = RootCauseAdvisor().generate(clusters, [], [])
        h = next(h for h in result if "Timeout pattern" in h.title)
        assert h.confidence == "high"

    def test_evidence_contains_tool_name_and_count(self) -> None:
        clusters = [
            _cluster(
                tool_name="fetch_page",
                failure_type="timeout",
                failure_rate=0.25,
                occurrence_count=5,
            )
        ]
        result = RootCauseAdvisor().generate(clusters, [], [])
        h = next(h for h in result if "Timeout pattern" in h.title)
        assert "fetch_page" in h.evidence
        assert "5" in h.evidence

    def test_multiple_timeout_clusters_produce_separate_hypotheses(self) -> None:
        clusters = [
            _cluster(
                tool_name="search", failure_type="timeout", failure_rate=0.2, occurrence_count=2
            ),
            _cluster(
                tool_name="fetch", failure_type="timeout", failure_rate=0.3, occurrence_count=3
            ),
        ]
        result = RootCauseAdvisor().generate(clusters, [], [])
        timeout_hypotheses = [h for h in result if "Timeout pattern" in h.title]
        assert len(timeout_hypotheses) == 2


# ---------------------------------------------------------------------------
# Rule 3 — Schema drift + failure
# ---------------------------------------------------------------------------


class TestSchemaDriftFailure:
    def test_triggers_when_drift_and_low_success(self) -> None:
        tools = [_tool_summary(drift_rate=0.2, success_rate=0.7)]
        result = RootCauseAdvisor().generate([], tools, [])
        assert any("Schema drift" in h.title for h in result)

    def test_no_trigger_when_drift_below_threshold(self) -> None:
        tools = [_tool_summary(drift_rate=0.05, success_rate=0.5)]
        result = RootCauseAdvisor().generate([], tools, [])
        assert not any("Schema drift" in h.title for h in result)

    def test_no_trigger_when_success_rate_high(self) -> None:
        tools = [_tool_summary(drift_rate=0.5, success_rate=0.95)]
        result = RootCauseAdvisor().generate([], tools, [])
        assert not any("Schema drift" in h.title for h in result)

    def test_confidence_is_high(self) -> None:
        tools = [_tool_summary(drift_rate=0.3, success_rate=0.6)]
        result = RootCauseAdvisor().generate([], tools, [])
        h = next(h for h in result if "Schema drift" in h.title)
        assert h.confidence == "high"

    def test_evidence_contains_tool_name(self) -> None:
        tools = [_tool_summary(tool_name="parse_json", drift_rate=0.4, success_rate=0.5)]
        result = RootCauseAdvisor().generate([], tools, [])
        h = next(h for h in result if "Schema drift" in h.title)
        assert "parse_json" in h.evidence


# ---------------------------------------------------------------------------
# Rule 4 — Dominant failure tool
# ---------------------------------------------------------------------------


class TestDominantFailureTool:
    def test_triggers_when_one_tool_over_50pct(self) -> None:
        clusters = [
            _cluster(tool_name="search", occurrence_count=6),
            _cluster(tool_name="fetch", occurrence_count=2),
        ]
        result = RootCauseAdvisor().generate(clusters, [], [])
        assert any("dominates failures" in h.title for h in result)

    def test_no_trigger_when_split_evenly(self) -> None:
        clusters = [
            _cluster(tool_name="search", occurrence_count=5),
            _cluster(tool_name="fetch", occurrence_count=5),
        ]
        result = RootCauseAdvisor().generate(clusters, [], [])
        assert not any("dominates failures" in h.title for h in result)

    def test_no_trigger_with_single_tool_at_50pct(self) -> None:
        # 5/10 = 50% — rule requires strictly > 50%
        clusters = [
            _cluster(tool_name="a", occurrence_count=5),
            _cluster(tool_name="b", occurrence_count=5),
        ]
        result = RootCauseAdvisor().generate(clusters, [], [])
        assert not any("dominates failures" in h.title for h in result)

    def test_confidence_is_high(self) -> None:
        clusters = [
            _cluster(tool_name="search", occurrence_count=7),
            _cluster(tool_name="other", occurrence_count=1),
        ]
        result = RootCauseAdvisor().generate(clusters, [], [])
        h = next(h for h in result if "dominates failures" in h.title)
        assert h.confidence == "high"

    def test_evidence_contains_tool_name_and_counts(self) -> None:
        clusters = [
            _cluster(tool_name="bad_tool", occurrence_count=8),
            _cluster(tool_name="ok_tool", occurrence_count=2),
        ]
        result = RootCauseAdvisor().generate(clusters, [], [])
        h = next(h for h in result if "dominates failures" in h.title)
        assert "bad_tool" in h.evidence
        assert "8" in h.evidence

    def test_aggregates_multiple_clusters_for_same_tool(self) -> None:
        clusters = [
            _cluster(tool_name="search", failure_type="timeout", occurrence_count=4),
            _cluster(tool_name="search", failure_type="api_error", occurrence_count=4),
            _cluster(tool_name="other", failure_type="timeout", occurrence_count=2),
        ]
        result = RootCauseAdvisor().generate(clusters, [], [])
        h = next((h for h in result if "dominates failures" in h.title), None)
        assert h is not None
        assert "search" in h.title


# ---------------------------------------------------------------------------
# Rule 5 — High latency variance
# ---------------------------------------------------------------------------


class TestHighLatencyVariance:
    def test_triggers_when_p95_over_3x_avg(self) -> None:
        tools = [_tool_summary(call_count=10, avg_latency_ms=100.0, p95_latency_ms=400.0)]
        result = RootCauseAdvisor().generate([], tools, [])
        assert any("latency variance" in h.title for h in result)

    def test_no_trigger_below_call_count_threshold(self) -> None:
        tools = [_tool_summary(call_count=4, avg_latency_ms=100.0, p95_latency_ms=500.0)]
        result = RootCauseAdvisor().generate([], tools, [])
        assert not any("latency variance" in h.title for h in result)

    def test_no_trigger_when_ratio_at_3x(self) -> None:
        # exactly 3.0 — rule requires strictly > 3.0
        tools = [_tool_summary(call_count=10, avg_latency_ms=100.0, p95_latency_ms=300.0)]
        result = RootCauseAdvisor().generate([], tools, [])
        assert not any("latency variance" in h.title for h in result)

    def test_no_trigger_when_avg_is_zero(self) -> None:
        tools = [_tool_summary(call_count=10, avg_latency_ms=0.0, p95_latency_ms=500.0)]
        result = RootCauseAdvisor().generate([], tools, [])
        assert not any("latency variance" in h.title for h in result)

    def test_confidence_is_medium(self) -> None:
        tools = [_tool_summary(call_count=10, avg_latency_ms=100.0, p95_latency_ms=500.0)]
        result = RootCauseAdvisor().generate([], tools, [])
        h = next(h for h in result if "latency variance" in h.title)
        assert h.confidence == "medium"

    def test_evidence_contains_latency_numbers(self) -> None:
        tools = [
            _tool_summary(
                tool_name="slow_api", call_count=10, avg_latency_ms=200.0, p95_latency_ms=800.0
            )
        ]
        result = RootCauseAdvisor().generate([], tools, [])
        h = next(h for h in result if "latency variance" in h.title)
        assert "slow_api" in h.evidence
        assert "800" in h.evidence
        assert "200" in h.evidence


# ---------------------------------------------------------------------------
# Rule 6 — Retry storm
# ---------------------------------------------------------------------------


class TestRetryStorm:
    def _storm_setup(self) -> tuple[list[dict], list[dict]]:
        # 3 unique tools; call_count/3 = 20 > 5
        clusters = [_cluster(tool_name="search", occurrence_count=5)]
        tools = [
            _tool_summary(tool_name="search", call_count=60),
            _tool_summary(tool_name="fetch", call_count=5),
            _tool_summary(tool_name="parse", call_count=5),
        ]
        return clusters, tools

    def test_triggers_when_call_ratio_high_and_top_failure_tool(self) -> None:
        clusters, tools = self._storm_setup()
        result = RootCauseAdvisor().generate(clusters, tools, [])
        assert any("retry storm" in h.title for h in result)

    def test_no_trigger_when_call_ratio_low(self) -> None:
        clusters = [_cluster(tool_name="search", occurrence_count=5)]
        tools = [
            _tool_summary(tool_name="search", call_count=10),
            _tool_summary(tool_name="fetch", call_count=9),
            _tool_summary(tool_name="parse", call_count=8),
        ]
        result = RootCauseAdvisor().generate(clusters, tools, [])
        assert not any("retry storm" in h.title for h in result)

    def test_no_trigger_when_not_top_failure_tool(self) -> None:
        # "fetch" has high call count but "search" is the top failure tool
        clusters = [_cluster(tool_name="search", occurrence_count=10)]
        tools = [
            _tool_summary(tool_name="fetch", call_count=60),
            _tool_summary(tool_name="search", call_count=5),
            _tool_summary(tool_name="parse", call_count=5),
        ]
        result = RootCauseAdvisor().generate(clusters, tools, [])
        assert not any("retry storm" in h.title for h in result)

    def test_confidence_is_low(self) -> None:
        clusters, tools = self._storm_setup()
        result = RootCauseAdvisor().generate(clusters, tools, [])
        h = next((h for h in result if "retry storm" in h.title), None)
        assert h is not None
        assert h.confidence == "low"

    def test_no_trigger_on_empty_clusters(self) -> None:
        tools = [_tool_summary(call_count=100)]
        result = RootCauseAdvisor().generate([], tools, [])
        assert not any("retry storm" in h.title for h in result)


# ---------------------------------------------------------------------------
# Ordering and deduplication
# ---------------------------------------------------------------------------


class TestOrdering:
    def test_high_confidence_sorted_before_medium(self) -> None:
        # Timeout → high; context overload → medium
        clusters = [_cluster(failure_type="timeout", failure_rate=0.2, occurrence_count=3)]
        llm = [_llm_summary(avg_context_utilisation=0.9)]
        result = RootCauseAdvisor().generate(clusters, [], llm)
        assert len(result) >= 2
        confidences = [h.confidence for h in result]
        high_idx = next(i for i, c in enumerate(confidences) if c == "high")
        medium_idx = next(i for i, c in enumerate(confidences) if c == "medium")
        assert high_idx < medium_idx

    def test_medium_sorted_before_low(self) -> None:
        # Latency variance → medium; retry storm → low
        clusters = [_cluster(tool_name="search", occurrence_count=5)]
        tools = [
            _tool_summary(
                tool_name="search", call_count=60, avg_latency_ms=100.0, p95_latency_ms=500.0
            ),
            _tool_summary(tool_name="b", call_count=5),
            _tool_summary(tool_name="c", call_count=5),
        ]
        result = RootCauseAdvisor().generate(clusters, tools, [])
        confidences = [h.confidence for h in result]
        medium_indices = [i for i, c in enumerate(confidences) if c == "medium"]
        low_indices = [i for i, c in enumerate(confidences) if c == "low"]
        if medium_indices and low_indices:
            assert min(medium_indices) < min(low_indices)

    def test_same_confidence_sorted_by_occurrence_count_desc(self) -> None:
        # Two timeout clusters with different occurrence counts
        clusters = [
            _cluster(
                tool_name="big_fail", failure_type="timeout", failure_rate=0.5, occurrence_count=10
            ),
            _cluster(
                tool_name="small_fail", failure_type="timeout", failure_rate=0.2, occurrence_count=2
            ),
        ]
        result = RootCauseAdvisor().generate(clusters, [], [])
        high_hyps = [h for h in result if h.confidence == "high" and "Timeout pattern" in h.title]
        assert len(high_hyps) == 2
        assert high_hyps[0]._occurrence_count >= high_hyps[1]._occurrence_count

    def test_no_duplicate_hypotheses_for_same_title(self) -> None:
        # Two clusters that would both trigger context overload — should only emit once
        clusters = [
            _cluster(tool_name="a", occurrence_count=2),
            _cluster(tool_name="b", occurrence_count=2),
        ]
        llm = [_llm_summary(avg_context_utilisation=0.9)]
        result = RootCauseAdvisor().generate(clusters, [], llm)
        titles = [h.title for h in result]
        assert len(titles) == len(set(titles))

    def test_returns_list_of_hypothesis_instances(self) -> None:
        clusters = [_cluster(failure_type="timeout", failure_rate=0.2)]
        result = RootCauseAdvisor().generate(clusters, [], [])
        assert all(isinstance(h, Hypothesis) for h in result)

    def test_each_hypothesis_has_non_empty_fields(self) -> None:
        clusters = [_cluster(failure_type="timeout", failure_rate=0.5, occurrence_count=5)]
        tools = [_tool_summary(drift_rate=0.3, success_rate=0.5)]
        llm = [_llm_summary(avg_context_utilisation=0.85)]
        result = RootCauseAdvisor().generate(clusters, tools, llm)
        for h in result:
            assert h.title
            assert h.evidence
            assert h.confidence in {"high", "medium", "low"}
            assert h.action
