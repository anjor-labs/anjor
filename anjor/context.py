"""Trace context propagation and span context manager for anjor.

Usage:
    import anjor
    anjor.patch()

    with anjor.span("web_researcher", trace_id="my-trace-001") as trace_id:
        # All LLM and tool events inside automatically carry this trace_id + agent_id.
        # An AgentSpanEvent is emitted when the block exits.
        result = client.messages.create(...)
"""

from __future__ import annotations

from collections.abc import Generator
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import UTC, datetime

import structlog

logger = structlog.get_logger(__name__)

# ── Context variables ─────────────────────────────────────────────────────────
# These are set by the `span()` context manager and read by PatchInterceptor
# to stamp every event produced within the block with the correct IDs.

_trace_id_var: ContextVar[str] = ContextVar("anjor_trace_id", default="")
_agent_id_var: ContextVar[str] = ContextVar("anjor_agent_id", default="")
_span_id_var: ContextVar[str] = ContextVar("anjor_span_id", default="")
_parent_span_id_var: ContextVar[str] = ContextVar("anjor_parent_span_id", default="")


def get_trace_id() -> str:
    return _trace_id_var.get()


def get_agent_id() -> str:
    return _agent_id_var.get()


def get_span_id() -> str:
    return _span_id_var.get()


def get_parent_span_id() -> str:
    return _parent_span_id_var.get()


# ── Internal span emitter ─────────────────────────────────────────────────────


def _emit_span(
    agent_name: str,
    trace_id: str,
    span_id: str,
    parent_span_id: str | None,
    span_kind: str,
    started_at: str,
    ended_at: str,
    status: str,
    failure_type: str | None,
) -> None:
    """Put an AgentSpanEvent onto the global pipeline (non-blocking)."""
    try:
        from anjor.core.events.agent_span import AgentSpanEvent, SpanKind

        kind = (
            SpanKind(span_kind) if span_kind in SpanKind._value2member_map_ else SpanKind.SUBAGENT
        )

        event = AgentSpanEvent(
            span_id=span_id,
            parent_span_id=parent_span_id,
            trace_id=trace_id,
            span_kind=kind,
            agent_name=agent_name,
            started_at=started_at,
            ended_at=ended_at,
            status=status,
            failure_type=failure_type,
        )

        # Access the global pipeline — gracefully skip if patch() hasn't been called.
        import anjor

        pipeline = anjor._pipeline
        if pipeline is not None:
            pipeline.put(event)
    except Exception as exc:
        logger.warning("span_emit_failed", error=str(exc))


# ── Public context manager ────────────────────────────────────────────────────


@contextmanager
def span(
    agent_name: str,
    trace_id: str = "",
    parent_span_id: str | None = None,
    span_kind: str = "subagent",
) -> Generator[str, None, None]:
    """Context manager that stamps all anjor events with trace/agent context.

    Sets trace_id, agent_id, and span_id on every LLM call and tool event
    produced by code running inside the block. On exit, emits an AgentSpanEvent
    to the collector automatically.

    Args:
        agent_name: Human-readable name for this agent (e.g. "web_researcher").
        trace_id:   Shared trace ID for all agents in the same run. If omitted,
                    a new UUID is generated. Pass the same value to all agents
                    in an orchestrated run so they appear in the same trace.
        parent_span_id: Span ID of the calling agent (for nested DAGs).
        span_kind:  One of "root", "orchestrator", "subagent", "tool".

    Yields:
        The resolved trace_id (useful when auto-generated).

    Example::

        trace_id = f"run-{uuid.uuid4()}"

        with anjor.span("orchestrator", trace_id=trace_id, span_kind="orchestrator"):
            with anjor.span("researcher", trace_id=trace_id,
                            parent_span_id=anjor.context.get_span_id()):
                result = client.messages.create(...)
    """
    from anjor.interceptors.traceparent import new_span_id, new_trace_id

    _resolved_trace_id = trace_id or new_trace_id()
    _resolved_span_id = new_span_id()
    started_at = datetime.now(UTC).isoformat()

    # Stamp context vars — all events produced inside this block pick these up.
    tok_trace = _trace_id_var.set(_resolved_trace_id)
    tok_agent = _agent_id_var.set(agent_name)
    tok_span = _span_id_var.set(_resolved_span_id)
    tok_parent = _parent_span_id_var.set(parent_span_id or "")

    status = "ok"
    failure_type: str | None = None
    try:
        yield _resolved_trace_id
    except Exception:
        status = "error"
        failure_type = "unknown"
        raise
    finally:
        _trace_id_var.reset(tok_trace)
        _agent_id_var.reset(tok_agent)
        _span_id_var.reset(tok_span)
        _parent_span_id_var.reset(tok_parent)

        ended_at = datetime.now(UTC).isoformat()
        _emit_span(
            agent_name=agent_name,
            trace_id=_resolved_trace_id,
            span_id=_resolved_span_id,
            parent_span_id=parent_span_id,
            span_kind=span_kind,
            started_at=started_at,
            ended_at=ended_at,
            status=status,
            failure_type=failure_type,
        )
