"""Unit tests for PromptDriftDetector."""

from __future__ import annotations

import dataclasses

import pytest

from anjor.analysis.prompt.detector import PromptDrift, PromptDriftDetector


class TestPromptDriftDetector:
    def setup_method(self) -> None:
        self.detector = PromptDriftDetector()

    def test_first_call_returns_none(self) -> None:
        result = self.detector.check("agent-1", system_prompt="You are helpful.")
        assert result is None

    def test_same_prompt_no_drift(self) -> None:
        self.detector.check("agent-1", system_prompt="You are helpful.")
        result = self.detector.check("agent-1", system_prompt="You are helpful.")
        assert isinstance(result, PromptDrift)
        assert result.detected is False

    def test_changed_prompt_drift_detected(self) -> None:
        self.detector.check("agent-1", system_prompt="You are helpful.")
        result = self.detector.check("agent-1", system_prompt="You are a pirate.")
        assert isinstance(result, PromptDrift)
        assert result.detected is True

    def test_drift_has_correct_hashes(self) -> None:
        import hashlib

        p1 = "You are helpful."
        p2 = "You are a pirate."
        h1 = hashlib.sha256(p1.encode()).hexdigest()
        h2 = hashlib.sha256(p2.encode()).hexdigest()

        self.detector.check("agent-1", system_prompt=p1)
        result = self.detector.check("agent-1", system_prompt=p2)
        assert isinstance(result, PromptDrift)
        assert result.previous_hash == h1
        assert result.current_hash == h2

    def test_calls_since_last_change_increments(self) -> None:
        self.detector.check("agent-1", system_prompt="Hello")
        self.detector.check("agent-1", system_prompt="Hello")
        self.detector.check("agent-1", system_prompt="Hello")
        result = self.detector.check("agent-1", system_prompt="Hello")
        assert isinstance(result, PromptDrift)
        assert result.calls_since_last_change == 3

    def test_calls_since_resets_after_drift(self) -> None:
        self.detector.check("agent-1", system_prompt="v1")
        self.detector.check("agent-1", system_prompt="v1")
        self.detector.check("agent-1", system_prompt="v2")  # drift — resets
        result = self.detector.check("agent-1", system_prompt="v2")
        assert isinstance(result, PromptDrift)
        assert result.calls_since_last_change == 1

    def test_none_prompt_treated_as_empty_string(self) -> None:
        self.detector.check("agent-1", system_prompt=None)
        result = self.detector.check("agent-1", system_prompt=None)
        assert isinstance(result, PromptDrift)
        assert result.detected is False

    def test_none_vs_empty_string_no_drift(self) -> None:
        self.detector.check("agent-1", system_prompt=None)
        result = self.detector.check("agent-1", system_prompt="")
        assert isinstance(result, PromptDrift)
        # None and "" both hash to sha256("") — no drift
        assert result.detected is False

    def test_independent_agents(self) -> None:
        self.detector.check("agent-1", system_prompt="v1")
        self.detector.check("agent-2", system_prompt="v1")
        r1 = self.detector.check("agent-1", system_prompt="v2")
        r2 = self.detector.check("agent-2", system_prompt="v1")
        assert isinstance(r1, PromptDrift)
        assert isinstance(r2, PromptDrift)
        assert r1.detected is True
        assert r2.detected is False

    def test_reset_clears_baseline(self) -> None:
        self.detector.check("agent-1", system_prompt="v1")
        self.detector.reset("agent-1")
        # After reset, next call is treated as first call again
        result = self.detector.check("agent-1", system_prompt="v1")
        assert result is None

    def test_reset_unknown_agent_no_error(self) -> None:
        self.detector.reset("nonexistent")  # must not raise

    def test_drift_result_frozen(self) -> None:
        import datetime
        result = PromptDrift(
            agent_id="a",
            detected=True,
            current_hash="abc",
            previous_hash="def",
            baseline_established=datetime.datetime.now(datetime.UTC),
            calls_since_last_change=1,
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.detected = False  # type: ignore[misc]

    def test_hash_is_deterministic(self) -> None:
        detector2 = PromptDriftDetector()
        detector2.check("a", system_prompt="hello")
        # Just verify same input → same result from both detectors
        self.detector.check("a", system_prompt="hello")
        result1 = self.detector.check("a", system_prompt="hello")
        detector2.check("a", system_prompt="hello")
        result2 = detector2.check("a", system_prompt="hello")
        assert isinstance(result1, PromptDrift)
        assert isinstance(result2, PromptDrift)
        assert result1.current_hash == result2.current_hash
