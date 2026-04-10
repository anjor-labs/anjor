"""Schema fingerprinting — structural hash of payload shape (not values).

Contract:
1. Deterministic: same input always → same hash
2. Structure-sensitive: field names + types matter, values do not
3. Type-sensitive: {"count": 1} ≠ {"count": "1"}
4. Key-order-invariant: {"a":1,"b":2} == {"b":2,"a":1}
5. Depth-limited: max recursion depth 10, yields "..." at limit
"""

from __future__ import annotations

import hashlib
import json
from typing import Any

_MAX_DEPTH = 10
_DEPTH_SENTINEL = "..."


def _structural_shape(value: Any, depth: int = 0) -> Any:
    """Recursively build a JSON-serialisable structure from types, not values."""
    if depth >= _MAX_DEPTH:
        return _DEPTH_SENTINEL

    if isinstance(value, dict):
        return {
            k: _structural_shape(v, depth + 1)
            for k, v in sorted(value.items())  # sorted for key-order invariance
        }
    if isinstance(value, list):
        if not value:
            return ["list<empty>"]
        # Represent the list by the shape of its first element
        return [_structural_shape(value[0], depth + 1)]
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if value is None:
        return "null"
    # Fallback for exotic types
    return type(value).__name__


def fingerprint(payload: dict[str, Any]) -> str:
    """Return a SHA-256 hex digest of the structural shape of payload."""
    shape = _structural_shape(payload)
    canonical = json.dumps(shape, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def diff_schemas(
    current: dict[str, Any], reference: dict[str, Any]
) -> dict[str, list[str]]:
    """Return field-level diff between current and reference payload shapes.

    Returns:
        {
            "missing_fields": fields in reference but not in current,
            "unexpected_fields": fields in current but not in reference,
        }
    """
    current_keys = set(current.keys())
    reference_keys = set(reference.keys())
    return {
        "missing_fields": sorted(reference_keys - current_keys),
        "unexpected_fields": sorted(current_keys - reference_keys),
    }
