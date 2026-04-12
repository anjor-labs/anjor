"""Unit tests for ContextWindowTracker and ContextHogDetector."""

from __future__ import annotations

import dataclasses

import pytest

from anjor.analysis.context.hog_detector import ContextHogDetector, ContextHogResult
from anjor.analysis.context.tracker import (
    ContextSnapshot,
    ContextThresholdAlert,
    ContextWindowTracker,
)

# ---------------------------------------------------------------------------
# ContextWindowTracker
# ---------------------------------------------------------------------------


class TestContextWindowTracker:
    def test_first_turn_no_alert(self) -> None:
        tracker = ContextWindowTracker(thresholds=[0.7])
        result = tracker.record("t1", context_used=10_000, context_limit=200_000)
        assert result is None

    def test_no_alert_below_threshold(self) -> None:
        tracker = ContextWindowTracker(thresholds=[0.7])
        tracker.record("t1", 10_000, 200_000)
        result = tracker.record("t1", 50_000, 200_000)  # 25% — below 70%
        assert result is None

    def test_alert_when_threshold_crossed(self) -> None:
        tracker = ContextWindowTracker(thresholds=[0.7])
        tracker.record("t1", 10_000, 200_000)
        result = tracker.record("t1", 150_000, 200_000)  # 75%
        assert isinstance(result, ContextThresholdAlert)
        assert result.threshold == 0.7
        assert result.trace_id == "t1"
        assert result.utilisation == pytest.approx(0.75)

    def test_no_repeat_alert_for_same_threshold(self) -> None:
        tracker = ContextWindowTracker(thresholds=[0.7])
        tracker.record("t1", 10_000, 200_000)
        tracker.record("t1", 150_000, 200_000)  # crosses 0.7 — alerted
        result = tracker.record("t1", 160_000, 200_000)  # still above 0.7 — no repeat
        assert result is None

    def test_multiple_thresholds_returns_highest(self) -> None:
        tracker = ContextWindowTracker(thresholds=[0.7, 0.9])
        tracker.record("t1", 10_000, 200_000)
        # Jump directly above 0.9 — should fire 0.9 alert (highest first)
        result = tracker.record("t1", 185_000, 200_000)
        assert isinstance(result, ContextThresholdAlert)
        assert result.threshold == 0.9

    def test_multiple_thresholds_separate_alerts(self) -> None:
        tracker = ContextWindowTracker(thresholds=[0.7, 0.9])
        tracker.record("t1", 10_000, 200_000)
        r1 = tracker.record("t1", 145_000, 200_000)   # 72.5% → fires 0.7
        r2 = tracker.record("t1", 185_000, 200_000)   # 92.5% → fires 0.9
        assert isinstance(r1, ContextThresholdAlert)
        assert r1.threshold == 0.7
        assert isinstance(r2, ContextThresholdAlert)
        assert r2.threshold == 0.9

    def test_independent_traces(self) -> None:
        tracker = ContextWindowTracker(thresholds=[0.7])
        tracker.record("t1", 10_000, 200_000)
        tracker.record("t2", 10_000, 200_000)
        r1 = tracker.record("t1", 150_000, 200_000)  # t1 crosses 0.7
        r2 = tracker.record("t2", 20_000, 200_000)   # t2 still below
        assert r1 is not None
        assert r2 is None

    def test_zero_limit_no_alert(self) -> None:
        tracker = ContextWindowTracker(thresholds=[0.7])
        tracker.record("t1", 0, 0)
        result = tracker.record("t1", 0, 0)
        assert result is None

    def test_turn_counter_increments(self) -> None:
        tracker = ContextWindowTracker()
        tracker.record("t1", 10_000, 200_000)
        tracker.record("t1", 20_000, 200_000)
        snaps = tracker.snapshots("t1")
        assert len(snaps) == 2
        assert snaps[0].turn == 1
        assert snaps[1].turn == 2

    def test_snapshots_returns_ordered(self) -> None:
        tracker = ContextWindowTracker()
        tracker.record("t1", 10_000, 200_000)
        tracker.record("t1", 30_000, 200_000)
        tracker.record("t1", 60_000, 200_000)
        snaps = tracker.snapshots("t1")
        assert [s.turn for s in snaps] == [1, 2, 3]

    def test_snapshots_empty_for_unknown_trace(self) -> None:
        tracker = ContextWindowTracker()
        assert tracker.snapshots("unknown") == []

    def test_growth_rate_two_turns(self) -> None:
        tracker = ContextWindowTracker()
        tracker.record("t1", 10_000, 200_000)
        tracker.record("t1", 30_000, 200_000)
        assert tracker.growth_rate("t1") == pytest.approx(20_000.0)

    def test_growth_rate_multiple_turns(self) -> None:
        tracker = ContextWindowTracker()
        tracker.record("t1", 10_000, 200_000)
        tracker.record("t1", 20_000, 200_000)
        tracker.record("t1", 40_000, 200_000)
        # total growth = 30_000, turns = 2 → avg = 15_000
        assert tracker.growth_rate("t1") == pytest.approx(15_000.0)

    def test_growth_rate_one_turn_returns_zero(self) -> None:
        tracker = ContextWindowTracker()
        tracker.record("t1", 10_000, 200_000)
        assert tracker.growth_rate("t1") == 0.0

    def test_growth_rate_unknown_trace_returns_zero(self) -> None:
        tracker = ContextWindowTracker()
        assert tracker.growth_rate("unknown") == 0.0

    def test_reset_clears_state(self) -> None:
        tracker = ContextWindowTracker(thresholds=[0.7])
        tracker.record("t1", 10_000, 200_000)
        tracker.record("t1", 150_000, 200_000)  # alerted at 0.7
        tracker.reset("t1")
        # After reset, the 0.7 alert fires again (cleared alerted set)
        result = tracker.record("t1", 150_000, 200_000)
        assert isinstance(result, ContextThresholdAlert)
        assert result.threshold == 0.7
        # Turn counter also reset to 1
        assert result.turn == 1

    def test_snapshot_dataclass_frozen(self) -> None:
        snap = ContextSnapshot(
            trace_id="t1", turn=1,
            context_window_used=100, context_window_limit=200,
            utilisation=0.5,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            snap.turn = 2  # type: ignore[misc]


# ---------------------------------------------------------------------------
# ContextHogDetector
# ---------------------------------------------------------------------------


class TestContextHogDetector:
    def test_small_output_not_a_hog(self) -> None:
        detector = ContextHogDetector(threshold=0.1, context_window_limit=200_000)
        # 1000 bytes / 4 = 250 tokens / 200_000 = 0.00125 < 10%
        result = detector.record("search", output_bytes=1_000)
        assert result.is_hog is False

    def test_large_output_is_a_hog(self) -> None:
        detector = ContextHogDetector(threshold=0.1, context_window_limit=200_000)
        # 100_000 bytes / 4 = 25_000 tokens / 200_000 = 12.5% > 10%
        result = detector.record("search", output_bytes=100_000)
        assert result.is_hog is True

    def test_result_fields_populated(self) -> None:
        detector = ContextHogDetector(threshold=0.1, context_window_limit=200_000)
        result = detector.record("search", output_bytes=80_000)
        assert result.tool_name == "search"
        assert result.avg_output_bytes == pytest.approx(80_000.0)
        assert result.estimated_tokens == 20_000

    def test_running_average(self) -> None:
        detector = ContextHogDetector(threshold=0.1, context_window_limit=200_000)
        detector.record("t", output_bytes=0)
        detector.record("t", output_bytes=80_000)
        result = detector.record("t", output_bytes=40_000)
        # avg = (0 + 80_000 + 40_000) / 3 = 40_000
        assert result.avg_output_bytes == pytest.approx(40_000.0)

    def test_independent_tools(self) -> None:
        detector = ContextHogDetector(threshold=0.1, context_window_limit=200_000)
        r1 = detector.record("search", output_bytes=100_000)
        r2 = detector.record("fetch", output_bytes=1_000)
        assert r1.is_hog is True
        assert r2.is_hog is False

    def test_summary_sorted_by_fraction_desc(self) -> None:
        detector = ContextHogDetector(threshold=0.1, context_window_limit=200_000)
        detector.record("small", output_bytes=1_000)
        detector.record("large", output_bytes=100_000)
        summary = detector.summary()
        assert summary[0].tool_name == "large"
        assert summary[1].tool_name == "small"

    def test_zero_limit_no_fraction(self) -> None:
        detector = ContextHogDetector(threshold=0.1, context_window_limit=0)
        result = detector.record("t", output_bytes=100_000)
        assert result.context_fraction == 0.0
        assert result.is_hog is False

    def test_result_is_frozen(self) -> None:
        result = ContextHogResult(
            tool_name="t", avg_output_bytes=1.0,
            estimated_tokens=1, context_fraction=0.0, is_hog=False,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.is_hog = True  # type: ignore[misc]
