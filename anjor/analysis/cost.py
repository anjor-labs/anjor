"""Token cost estimation — mirrors the JS price table in dashboard/static/llm.html.

Tuple format: (input_per_m, cache_write_per_m, cache_read_per_m, output_per_m) USD/M tokens.
"""

from __future__ import annotations

_PRICE_TABLE: dict[str, tuple[float, float, float, float]] = {
    "claude-opus-4-6": (15.00, 18.75, 1.50, 75.00),
    "claude-sonnet-4-6": (3.00, 3.75, 0.30, 15.00),
    "claude-haiku-4-5-20251001": (0.80, 1.00, 0.08, 4.00),
    "claude-haiku-4-5": (0.80, 1.00, 0.08, 4.00),
    "claude-3-5-sonnet-20241022": (3.00, 3.75, 0.30, 15.00),
    "claude-3-5-haiku-20241022": (0.80, 1.00, 0.08, 4.00),
    "claude-3-opus-20240229": (15.00, 18.75, 1.50, 75.00),
    "gpt-4o-mini": (0.15, 0.15, 0.075, 0.60),
    "gpt-4o": (2.50, 2.50, 1.25, 10.00),
    "gpt-4-turbo": (10.00, 10.00, 5.00, 30.00),
    "o3-mini": (1.10, 1.10, 0.55, 4.40),
    "o1": (15.00, 15.00, 7.50, 60.00),
    "gemini-2.0-flash": (0.10, 0.10, 0.025, 0.40),
    "gemini-1.5-flash": (0.075, 0.075, 0.01875, 0.30),
    "gemini-1.5-pro": (1.25, 1.25, 0.3125, 5.00),
}

_DEFAULT: tuple[float, float, float, float] = (3.00, 3.75, 0.30, 15.00)


def _get_price(model: str) -> tuple[float, float, float, float]:
    if model in _PRICE_TABLE:
        return _PRICE_TABLE[model]
    # Prefix match for versioned names like claude-opus-4-7-20260101
    for key, prices in _PRICE_TABLE.items():
        if model.startswith(key):
            return prices
    return _DEFAULT


def estimate_cost_usd(
    model: str,
    token_input: int,
    token_output: int,
    cache_read: int = 0,
    cache_write: int = 0,
) -> float:
    """Return estimated cost in USD for a model + token counts."""
    inp, cw, cr, out = _get_price(model)
    return (token_input * inp + token_output * out + cache_read * cr + cache_write * cw) / 1_000_000
