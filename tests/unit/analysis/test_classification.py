"""Unit tests for FailureClassifier and classification rules."""

from __future__ import annotations

from hypothesis import given
from hypothesis import strategies as st

from anjor.analysis.classification.failure import (
    APIErrorRule,
    ClassificationContext,
    FailureClassifier,
    SchemaDriftRule,
    TimeoutRule,
    UnknownRule,
)
from anjor.core.events.tool_call import FailureType


class TestTimeoutRule:
    def test_latency_over_threshold(self) -> None:
        rule = TimeoutRule()
        ctx = ClassificationContext(latency_ms=6000.0, timeout_threshold_ms=5000.0)
        assert rule.matches(ctx) is True

    def test_latency_under_threshold(self) -> None:
        rule = TimeoutRule()
        ctx = ClassificationContext(latency_ms=1000.0, timeout_threshold_ms=5000.0)
        assert rule.matches(ctx) is False

    def test_error_message_timeout(self) -> None:
        rule = TimeoutRule()
        ctx = ClassificationContext(error_message="Connection timed out")
        assert rule.matches(ctx) is True

    def test_failure_type(self) -> None:
        assert TimeoutRule().failure_type == FailureType.TIMEOUT

    def test_priority(self) -> None:
        assert TimeoutRule().priority == 10


class TestSchemaDriftRule:
    def test_drift_detected(self) -> None:
        rule = SchemaDriftRule()
        ctx = ClassificationContext(has_schema_drift=True)
        assert rule.matches(ctx) is True

    def test_no_drift(self) -> None:
        rule = SchemaDriftRule()
        ctx = ClassificationContext(has_schema_drift=False)
        assert rule.matches(ctx) is False

    def test_failure_type(self) -> None:
        assert SchemaDriftRule().failure_type == FailureType.SCHEMA_DRIFT

    def test_priority_lower_than_api_error(self) -> None:
        assert SchemaDriftRule().priority < APIErrorRule().priority


class TestAPIErrorRule:
    def test_http_500(self) -> None:
        rule = APIErrorRule()
        ctx = ClassificationContext(status_code=500)
        assert rule.matches(ctx) is True

    def test_http_404(self) -> None:
        rule = APIErrorRule()
        ctx = ClassificationContext(status_code=404)
        assert rule.matches(ctx) is True

    def test_http_200(self) -> None:
        rule = APIErrorRule()
        ctx = ClassificationContext(status_code=200)
        assert rule.matches(ctx) is False

    def test_error_message_rate_limit(self) -> None:
        rule = APIErrorRule()
        ctx = ClassificationContext(error_message="Rate limit exceeded")
        assert rule.matches(ctx) is True

    def test_failure_type(self) -> None:
        assert APIErrorRule().failure_type == FailureType.API_ERROR


class TestUnknownRule:
    def test_always_matches(self) -> None:
        rule = UnknownRule()
        assert rule.matches(ClassificationContext()) is True

    def test_failure_type(self) -> None:
        assert UnknownRule().failure_type == FailureType.UNKNOWN

    def test_priority_is_highest(self) -> None:
        assert UnknownRule().priority == 999


class TestFailureClassifier:
    def test_timeout_takes_priority(self) -> None:
        clf = FailureClassifier()
        ctx = ClassificationContext(
            latency_ms=9000.0,
            has_schema_drift=True,
            status_code=500,
        )
        assert clf.analyse(ctx) == FailureType.TIMEOUT

    def test_schema_drift_before_api_error(self) -> None:
        clf = FailureClassifier()
        ctx = ClassificationContext(has_schema_drift=True, status_code=500)
        assert clf.analyse(ctx) == FailureType.SCHEMA_DRIFT

    def test_api_error_before_unknown(self) -> None:
        clf = FailureClassifier()
        ctx = ClassificationContext(status_code=502)
        assert clf.analyse(ctx) == FailureType.API_ERROR

    def test_unknown_fallback(self) -> None:
        clf = FailureClassifier()
        ctx = ClassificationContext()
        assert clf.analyse(ctx) == FailureType.UNKNOWN

    def test_custom_rules(self) -> None:
        class AlwaysTimeout(TimeoutRule):
            def matches(self, ctx: ClassificationContext) -> bool:
                return True

        clf = FailureClassifier(rules=[AlwaysTimeout(), UnknownRule()])
        ctx = ClassificationContext()
        assert clf.analyse(ctx) == FailureType.TIMEOUT

    def test_rules_sorted_by_priority(self) -> None:
        clf = FailureClassifier()
        priorities = [r.priority for r in clf._rules]
        assert priorities == sorted(priorities)

    @given(
        st.floats(min_value=0, max_value=100_000, allow_nan=False),
        st.booleans(),
        st.one_of(st.none(), st.integers(min_value=100, max_value=599)),
    )
    def test_always_returns_a_failure_type(
        self,
        latency: float,
        has_drift: bool,
        status_code: int | None,
    ) -> None:
        clf = FailureClassifier()
        ctx = ClassificationContext(
            latency_ms=latency,
            has_schema_drift=has_drift,
            status_code=status_code,
        )
        result = clf.analyse(ctx)
        assert isinstance(result, FailureType)
