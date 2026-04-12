"""Unit tests for DriftDetector."""

from __future__ import annotations

import pytest

from anjor.analysis.drift.detector import DriftDetector


class TestDriftDetector:
    def test_first_call_returns_none(self) -> None:
        detector = DriftDetector()
        result = detector.check("search", {"query": "hello"})
        assert result is None

    def test_same_schema_returns_no_drift(self) -> None:
        detector = DriftDetector()
        payload = {"query": "hello", "limit": 10}
        detector.check("search", payload)
        result = detector.check("search", {"query": "world", "limit": 5})
        assert result is not None
        assert result.detected is False

    def test_different_schema_returns_drift(self) -> None:
        detector = DriftDetector()
        detector.check("search", {"query": "hello", "limit": 10})
        result = detector.check("search", {"query": "world", "offset": 0})
        assert result is not None
        assert result.detected is True
        assert "limit" in result.missing_fields
        assert "offset" in result.unexpected_fields

    def test_drift_has_expected_hash(self) -> None:
        from anjor.analysis.drift.fingerprint import fingerprint

        detector = DriftDetector()
        baseline = {"a": 1, "b": 2}
        detector.check("t", baseline)
        result = detector.check("t", {"a": 1, "c": 3})
        assert result is not None
        assert result.expected_hash == fingerprint(baseline)

    def test_multiple_tools_independent(self) -> None:
        detector = DriftDetector()
        detector.check("tool_a", {"x": 1})
        detector.check("tool_b", {"y": 2})

        # tool_a drifts
        drift_a = detector.check("tool_a", {"z": 3})
        assert drift_a is not None and drift_a.detected is True

        # tool_b does not drift (same schema)
        drift_b = detector.check("tool_b", {"y": 99})
        assert drift_b is not None and drift_b.detected is False

    def test_reset_single_tool(self) -> None:
        detector = DriftDetector()
        detector.check("t", {"a": 1})
        detector.reset("t")
        # After reset, first call again stores baseline
        result = detector.check("t", {"b": 2})
        assert result is None

    def test_reset_all(self) -> None:
        detector = DriftDetector()
        detector.check("t1", {"a": 1})
        detector.check("t2", {"b": 2})
        detector.reset()
        assert detector.check("t1", {"x": 9}) is None
        assert detector.check("t2", {"y": 9}) is None

    def test_analyse_raises(self) -> None:
        detector = DriftDetector()
        with pytest.raises(NotImplementedError):
            detector.analyse(None)
