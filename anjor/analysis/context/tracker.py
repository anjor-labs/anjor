"""ContextWindowTracker — per-trace context utilisation tracking.

Accumulates LLMCallEvents for a given trace_id and:
- Tracks how context usage grows turn-by-turn
- Fires threshold alerts when utilisation crosses configurable levels
- Computes growth rate (average tokens added per turn)
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContextSnapshot:
    """Immutable snapshot of context state at a given turn."""

    trace_id: str
    turn: int
    context_window_used: int
    context_window_limit: int
    # 0.0–1.0; 0.0 when limit is unknown
    utilisation: float


@dataclass(frozen=True)
class ContextThresholdAlert:
    """Emitted when context utilisation crosses a threshold."""

    trace_id: str
    turn: int
    threshold: float
    utilisation: float
    context_window_used: int
    context_window_limit: int


@dataclass
class ContextWindowTracker:
    """Tracks context window usage across turns of the same trace.

    Usage::

        tracker = ContextWindowTracker(thresholds=[0.7, 0.9])
        alert = tracker.record(
            trace_id="abc", context_used=140_000, context_limit=200_000
        )
        if alert:
            print(f"Context at {alert.utilisation:.0%} of limit")

    Each call to ``record()`` for the same trace_id increments the turn counter
    and checks whether any configured threshold has been crossed since the last turn.
    """

    # DECISION: thresholds sorted descending so we check the most critical first
    # and return the highest-priority alert rather than multiple.
    thresholds: list[float] = field(default_factory=lambda: [0.7, 0.9])

    # Per-trace state: turn count and last-known utilisation
    _turns: dict[str, int] = field(default_factory=dict, repr=False)
    _snapshots: dict[str, list[ContextSnapshot]] = field(default_factory=dict, repr=False)
    _alerted: dict[str, set[float]] = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        self.thresholds = sorted(self.thresholds, reverse=True)

    def record(
        self,
        trace_id: str,
        context_used: int,
        context_limit: int,
    ) -> ContextThresholdAlert | None:
        """Record a new turn for trace_id. Returns an alert if a threshold is crossed.

        Thresholds are one-way — once alerted at a given level, no repeat alert
        for that level within the same trace.
        """
        turn = self._turns.get(trace_id, 0) + 1
        self._turns[trace_id] = turn

        utilisation = (context_used / context_limit) if context_limit > 0 else 0.0
        snap = ContextSnapshot(
            trace_id=trace_id,
            turn=turn,
            context_window_used=context_used,
            context_window_limit=context_limit,
            utilisation=utilisation,
        )
        self._snapshots.setdefault(trace_id, []).append(snap)

        alerted = self._alerted.setdefault(trace_id, set())
        for threshold in self.thresholds:  # descending order
            if utilisation >= threshold and threshold not in alerted:
                alerted.add(threshold)
                return ContextThresholdAlert(
                    trace_id=trace_id,
                    turn=turn,
                    threshold=threshold,
                    utilisation=utilisation,
                    context_window_used=context_used,
                    context_window_limit=context_limit,
                )
        return None

    def snapshots(self, trace_id: str) -> list[ContextSnapshot]:
        """Return all snapshots for a trace in turn order."""
        return list(self._snapshots.get(trace_id, []))

    def growth_rate(self, trace_id: str) -> float:
        """Average tokens added per turn for trace_id.

        Returns 0.0 if fewer than 2 turns recorded.
        """
        snaps = self._snapshots.get(trace_id, [])
        if len(snaps) < 2:
            return 0.0
        total_growth = snaps[-1].context_window_used - snaps[0].context_window_used
        turns = len(snaps) - 1
        return total_growth / turns

    def reset(self, trace_id: str) -> None:
        """Clear all state for a trace (e.g. when a run completes)."""
        self._turns.pop(trace_id, None)
        self._snapshots.pop(trace_id, None)
        self._alerted.pop(trace_id, None)
