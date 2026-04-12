"""TokenOptimizer + CostEstimator — identify context-bloating tools and quantify savings.

Phase 3 intelligence: surface tools whose outputs consume disproportionate context
and estimate the cost savings of filtering or summarising their output.
"""

from __future__ import annotations

import json
import statistics
from dataclasses import dataclass, field
from typing import Any

from anjor.analysis.base import BaseAnalyser

# Approximate cost per 1M output tokens (USD), as of Phase 3 implementation.
# DECISION: stored here (not in config) because these are reference values for
# suggestion generation, not operational config. Users who need exact pricing
# can pass a custom pricing dict to TokenOptimizer.
MODEL_PRICING: dict[str, float] = {
    "claude-opus-4-5": 15.0,
    "claude-sonnet-4-5": 3.0,
    "claude-haiku-4-5": 0.25,
    "claude-3-5-sonnet-20241022": 3.0,
    "claude-3-5-haiku-20241022": 0.8,
    "claude-3-opus-20240229": 15.0,
    "gpt-4o": 10.0,
    "gpt-4o-mini": 0.6,
    "gpt-4-turbo": 30.0,
    "default": 3.0,  # conservative fallback
}

# Approximate bytes-per-token ratio for JSON payloads.
# English text ≈ 4 chars/token; JSON overhead pushes it slightly higher.
_BYTES_PER_TOKEN: float = 4.5

# Tools whose average output contributes more than this fraction of the context
# window are flagged as optimization candidates.
_DEFAULT_HOG_THRESHOLD: float = 0.05  # 5% of context window


@dataclass
class OptimizationSuggestion:
    """A concrete token optimization opportunity for a single tool."""

    tool_name: str
    avg_output_tokens: float
    avg_context_fraction: float  # estimated fraction of context window used by this tool
    waste_score: float  # [0.0, 1.0] — higher = more room to optimise
    estimated_savings_tokens_per_call: float
    estimated_savings_usd_per_1k_calls: float
    suggestion_text: str
    sample_models: list[str] = field(default_factory=list)


class TokenOptimizer(BaseAnalyser):
    """Identifies tools with oversized outputs and generates optimization suggestions.

    Input data contract:
        tool_calls: list of raw tool_call row dicts (must include output_payload,
            tool_name, token_usage_output)
        llm_calls: list of raw llm_call row dicts (must include context_window_limit,
            model, token_output)

    These match the row format returned by SQLiteBackend.
    """

    def __init__(
        self,
        hog_threshold: float = _DEFAULT_HOG_THRESHOLD,
        pricing: dict[str, float] | None = None,
    ) -> None:
        self._threshold = hog_threshold
        self._pricing = pricing or MODEL_PRICING

    def analyse(
        self,
        data: tuple[list[dict[str, Any]], list[dict[str, Any]]],
    ) -> list[OptimizationSuggestion]:
        """Run optimization analysis.

        Args:
            data: Tuple of (tool_calls, llm_calls).

        Returns:
            Suggestions sorted by avg_output_tokens descending.
        """
        tool_calls, llm_calls = data
        return self.optimize(tool_calls, llm_calls)

    def optimize(
        self,
        tool_calls: list[dict[str, Any]],
        llm_calls: list[dict[str, Any]],
    ) -> list[OptimizationSuggestion]:
        """Generate optimization suggestions from raw event data."""
        # Derive the average context window limit from LLM call data
        limits = [
            int(r["context_window_limit"]) for r in llm_calls if r.get("context_window_limit")
        ]
        avg_context_limit = statistics.mean(limits) if limits else 200_000

        # Collect model names seen in llm_calls for the suggestion text
        models_seen = list({str(r.get("model", "")) for r in llm_calls if r.get("model")})

        # Compute per-tool output token averages
        tool_output_tokens: dict[str, list[float]] = {}
        for row in tool_calls:
            tool_name = row.get("tool_name", "unknown")
            # Prefer explicit token count; fall back to payload size estimate
            token_count = self._extract_output_tokens(row)
            tool_output_tokens.setdefault(tool_name, []).append(token_count)

        # Build suggestions for tools above the threshold
        suggestions: list[OptimizationSuggestion] = []
        for tool_name, token_counts in tool_output_tokens.items():
            avg_tokens = statistics.mean(token_counts)
            context_fraction = avg_tokens / avg_context_limit if avg_context_limit > 0 else 0.0

            if context_fraction < self._threshold:
                continue  # below threshold — not a candidate

            if context_fraction == 0.0:
                continue  # no output to optimise

            # Waste score: how much of the output is likely unused
            # Heuristic: anything beyond 2% of the context window is "waste"
            # (the agent rarely reads an entire bloated tool output verbatim)
            waste_fraction = max(0.0, (context_fraction - 0.02) / context_fraction)
            savings_tokens = avg_tokens * waste_fraction

            # Cost estimate using the most common (or default) model's output pricing
            cost_per_1m = self._cost_per_1m(models_seen)
            savings_usd_per_1k = (savings_tokens / 1_000_000) * cost_per_1m * 1_000

            suggestion_text = self._build_suggestion(
                tool_name, avg_tokens, context_fraction, savings_tokens
            )
            suggestions.append(
                OptimizationSuggestion(
                    tool_name=tool_name,
                    avg_output_tokens=round(avg_tokens, 1),
                    avg_context_fraction=round(context_fraction, 4),
                    waste_score=round(waste_fraction, 4),
                    estimated_savings_tokens_per_call=round(savings_tokens, 1),
                    estimated_savings_usd_per_1k_calls=round(savings_usd_per_1k, 4),
                    suggestion_text=suggestion_text,
                    sample_models=models_seen[:3],
                )
            )

        return sorted(suggestions, key=lambda s: s.avg_output_tokens, reverse=True)

    def _extract_output_tokens(self, row: dict[str, Any]) -> float:
        """Extract output token count from a tool call row.

        Prefers explicit token_usage_output; falls back to payload byte size.
        """
        explicit = row.get("token_usage_output")
        if explicit is not None:
            try:
                return float(explicit)
            except (TypeError, ValueError):
                pass
        payload = row.get("output_payload")
        if payload:
            if isinstance(payload, str):
                byte_size = len(payload.encode("utf-8"))
            else:
                byte_size = len(json.dumps(payload).encode("utf-8"))
            return byte_size / _BYTES_PER_TOKEN
        return 0.0

    def _cost_per_1m(self, models: list[str]) -> float:
        for model in models:
            if model in self._pricing:
                return self._pricing[model]
        return self._pricing.get("default", 3.0)

    @staticmethod
    def _build_suggestion(
        tool_name: str,
        avg_tokens: float,
        context_fraction: float,
        savings_tokens: float,
    ) -> str:
        pct = f"{context_fraction * 100:.1f}%"
        savings_pct = f"{savings_tokens / avg_tokens * 100:.0f}%" if avg_tokens > 0 else "~"
        return (
            f"Tool '{tool_name}' outputs ~{avg_tokens:,.0f} tokens on average "
            f"({pct} of context window). "
            f"Filtering or summarising the output could reduce context usage by ~{savings_pct}."
        )


class CostEstimator:
    """Estimates dollar cost savings for a given OptimizationSuggestion.

    Separated from TokenOptimizer so callers can recompute with different
    pricing or call volumes without re-running the full analysis.
    """

    def __init__(self, pricing: dict[str, float] | None = None) -> None:
        self._pricing = pricing or MODEL_PRICING

    def estimate(
        self,
        suggestion: OptimizationSuggestion,
        calls_per_day: int = 1000,
        model: str = "default",
    ) -> float:
        """Estimate daily USD savings if the suggestion is acted on.

        Args:
            suggestion: The optimization suggestion to cost.
            calls_per_day: Expected daily call volume.
            model: Model name for pricing lookup.

        Returns:
            Estimated daily USD savings.
        """
        cost_per_1m = self._pricing.get(model, self._pricing.get("default", 3.0))
        tokens_saved_per_day = suggestion.estimated_savings_tokens_per_call * calls_per_day
        return round((tokens_saved_per_day / 1_000_000) * cost_per_1m, 6)
