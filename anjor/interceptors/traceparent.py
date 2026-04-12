"""W3C Trace Context (traceparent) helpers.

Spec: https://www.w3.org/TR/trace-context/
Format: 00-<trace_id:32hex>-<parent_id:16hex>-<flags:2hex>

Only the sampled flag (01) is used. trace_id and parent_id are both
randomly generated when no incoming traceparent is present.
"""

from __future__ import annotations

import os
import re

_TRACEPARENT_RE = re.compile(r"^00-([0-9a-f]{32})-([0-9a-f]{16})-([0-9a-f]{2})$")

HEADER = "traceparent"


def new_trace_id() -> str:
    """Generate a fresh 32-hex (16-byte) trace ID."""
    return os.urandom(16).hex()


def new_span_id() -> str:
    """Generate a fresh 16-hex (8-byte) span ID."""
    return os.urandom(8).hex()


def make_traceparent(trace_id: str, span_id: str) -> str:
    """Build a W3C traceparent header value."""
    return f"00-{trace_id}-{span_id}-01"


def parse_traceparent(value: str) -> tuple[str, str] | None:
    """Parse a traceparent header value.

    Returns (trace_id, parent_span_id) or None if the header is invalid
    or uses an unsupported version.
    """
    m = _TRACEPARENT_RE.match(value.strip().lower())
    if m is None:
        return None
    trace_id, parent_span_id, _flags = m.groups()
    # All-zero IDs are invalid per spec
    if trace_id == "0" * 32 or parent_span_id == "0" * 16:
        return None
    return trace_id, parent_span_id
