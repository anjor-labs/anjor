"""ContextHogDetector — identifies tools with disproportionately large output payloads.

A "context hog" is a tool whose average output payload size contributes more than
a configurable threshold (default: 10%) of the model's total context window.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class ContextHogResult:
    """Result of a single tool size check."""

    tool_name: str
    avg_output_bytes: float
    # Estimated token count: bytes / 4 (rough approximation for English text)
    estimated_tokens: int
    # Fraction of context_window_limit (0.0 if limit is unknown)
    context_fraction: float
    is_hog: bool


@dataclass
class ContextHogDetector:
    """Tracks average output sizes per tool and flags context hogs.

    Usage::

        detector = ContextHogDetector(threshold=0.1, context_window_limit=200_000)
        result = detector.record("web_search", output_bytes=80_000)
        if result.is_hog:
            print(f"{result.tool_name} uses {result.context_fraction:.0%} of context")

    ``record()`` updates the running average and returns the current verdict.
    """

    # DECISION: 0.10 (10%) default — a single tool consuming more than 10% of the
    # available context on average is worth flagging; below that, optimisation is
    # unlikely to yield meaningful savings.
    threshold: float = 0.10
    context_window_limit: int = 200_000

    _counts: dict[str, int] = field(default_factory=dict, repr=False)
    _total_bytes: dict[str, float] = field(default_factory=dict, repr=False)

    def record(self, tool_name: str, output_bytes: int) -> ContextHogResult:
        """Update running average for tool_name and return the current verdict."""
        self._counts[tool_name] = self._counts.get(tool_name, 0) + 1
        self._total_bytes[tool_name] = self._total_bytes.get(tool_name, 0.0) + output_bytes

        avg = self._total_bytes[tool_name] / self._counts[tool_name]
        estimated_tokens = max(1, int(avg / 4))  # rough bytes-to-tokens heuristic

        if self.context_window_limit > 0:
            context_fraction = estimated_tokens / self.context_window_limit
        else:
            context_fraction = 0.0

        return ContextHogResult(
            tool_name=tool_name,
            avg_output_bytes=avg,
            estimated_tokens=estimated_tokens,
            context_fraction=context_fraction,
            is_hog=context_fraction >= self.threshold,
        )

    def summary(self) -> list[ContextHogResult]:
        """Return current results for all tracked tools, sorted by fraction descending."""
        corrected = []
        for name in self._counts:
            avg = self._total_bytes[name] / self._counts[name]
            estimated_tokens = max(1, int(avg / 4))
            limit = self.context_window_limit
            cf = (estimated_tokens / limit) if limit > 0 else 0.0
            corrected.append(
                ContextHogResult(
                    tool_name=name,
                    avg_output_bytes=avg,
                    estimated_tokens=estimated_tokens,
                    context_fraction=cf,
                    is_hog=cf >= self.threshold,
                )
            )
        return sorted(corrected, key=lambda r: r.context_fraction, reverse=True)
