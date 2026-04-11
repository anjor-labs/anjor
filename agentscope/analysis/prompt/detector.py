"""PromptDriftDetector — detects when system prompts change between agent runs.

Hashes system prompts and message templates per agent_id. On first call,
stores the baseline. On subsequent calls, returns a PromptDrift if the hash changed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import UTC, datetime


@dataclass(frozen=True)
class PromptDrift:
    """Returned when a prompt change is detected for an agent."""

    agent_id: str
    detected: bool
    # Hash of the new (current) prompt
    current_hash: str
    # Hash of the previous (baseline) prompt
    previous_hash: str
    # When the baseline was first established
    baseline_established: datetime
    # Number of calls since the last change
    calls_since_last_change: int


@dataclass
class _PromptBaseline:
    hash: str
    established_at: datetime
    call_count: int = 0


@dataclass
class PromptDriftDetector:
    """Detects changes to system prompts and message templates per agent.

    Usage::

        detector = PromptDriftDetector()

        # First call for this agent — establishes baseline
        result = detector.check("my-agent", system_prompt="You are helpful.")
        assert result is None

        # Same prompt — no drift
        result = detector.check("my-agent", system_prompt="You are helpful.")
        assert result.detected is False

        # Changed prompt — drift detected
        result = detector.check("my-agent", system_prompt="You are a pirate.")
        assert result.detected is True
    """

    _baselines: dict[str, _PromptBaseline] = field(default_factory=dict, repr=False)

    @staticmethod
    def _hash(text: str) -> str:
        return hashlib.sha256(text.encode()).hexdigest()

    def check(
        self,
        agent_id: str,
        system_prompt: str | None = None,
    ) -> PromptDrift | None:
        """Check whether the system prompt has changed for agent_id.

        Args:
            agent_id: Identifies the agent/process being tracked.
            system_prompt: Current system prompt text. None means "no system prompt".

        Returns:
            None on first call (baseline stored).
            PromptDrift(detected=False) if prompt is unchanged.
            PromptDrift(detected=True) if prompt changed.
        """
        current_hash = self._hash(system_prompt or "")

        if agent_id not in self._baselines:
            # DECISION: first call always stores baseline and returns None —
            # a "drift" requires a before-and-after, so the first observation
            # cannot be a drift event.
            self._baselines[agent_id] = _PromptBaseline(
                hash=current_hash,
                established_at=datetime.now(UTC),
            )
            return None

        baseline = self._baselines[agent_id]
        baseline.call_count += 1
        detected = current_hash != baseline.hash

        result = PromptDrift(
            agent_id=agent_id,
            detected=detected,
            current_hash=current_hash,
            previous_hash=baseline.hash,
            baseline_established=baseline.established_at,
            calls_since_last_change=baseline.call_count,
        )

        if detected:
            # Update baseline to new prompt; reset call counter
            self._baselines[agent_id] = _PromptBaseline(
                hash=current_hash,
                established_at=datetime.now(UTC),
            )

        return result

    def reset(self, agent_id: str) -> None:
        """Clear the baseline for agent_id."""
        self._baselines.pop(agent_id, None)
