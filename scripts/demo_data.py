"""
demo_data.py — fire realistic fake events at the running collector.

Usage:
    python scripts/demo_data.py

Requires the collector to be running:
    python scripts/start_collector.py
"""

from __future__ import annotations

import random
import time
import uuid
from datetime import UTC, datetime

import httpx

COLLECTOR = "http://localhost:7843"
MODEL = "claude-3-5-sonnet-20241022"

# One trace for context growth demo (multi-turn agent)
TRACE_ID = "demo-trace-001"
TRACE_ID_2 = "demo-trace-002"
SESSION_ID = str(uuid.uuid4())


def post(event: dict) -> None:
    resp = httpx.post(f"{COLLECTOR}/events", json=event, timeout=5)
    resp.raise_for_status()


def ts() -> str:
    return datetime.now(UTC).isoformat()


# ---------------------------------------------------------------------------
# LLM calls — growing context across turns (same trace_id)
# ---------------------------------------------------------------------------

def llm_call(
    turn: int,
    context_used: int,
    trace_id: str = TRACE_ID,
    model: str = MODEL,
    context_limit: int = 200_000,
) -> None:
    post({
        "event_type": "llm_call",
        "trace_id": trace_id,
        "session_id": SESSION_ID,
        "agent_id": "research-agent",
        "timestamp": ts(),
        "sequence_no": turn,
        "model": model,
        "latency_ms": random.uniform(800, 2400),
        "finish_reason": "tool_use" if turn < 5 else "end_turn",
        "token_usage": {
            "input": context_used,
            "output": random.randint(60, 200),
            "cache_read": random.randint(0, 500) if turn > 1 else 0,
        },
        "context_window_used": context_used,
        "context_window_limit": context_limit,
        "context_utilisation": round(context_used / context_limit, 6),
        "prompt_hash": "a3f9b2c1" * 8,
        "system_prompt_hash": "d4e5f6a7" * 8,
        "messages_count": turn * 2 + 1,
    })
    print(f"  LLM turn {turn}: {context_used:,} tokens ({context_used/context_limit:.1%} context)")


# ---------------------------------------------------------------------------
# Tool calls
# ---------------------------------------------------------------------------

def tool_call(
    tool_name: str,
    status: str = "success",
    failure_type: str | None = None,
    latency_ms: float | None = None,
    token_in: int = 150,
    token_out: int = 60,
    trace_id: str | None = None,
    sequence_no: int = 0,
    drift: dict | None = None,
) -> None:
    # Derive failure_type from status if not provided
    if status == "failure" and failure_type is None:
        failure_type = "api_error"
    post({
        "event_type": "tool_call",
        "trace_id": trace_id or str(uuid.uuid4()),
        "session_id": SESSION_ID,
        "agent_id": "research-agent",
        "timestamp": ts(),
        "sequence_no": sequence_no,
        "tool_name": tool_name,
        "status": status,
        "failure_type": failure_type if status == "failure" else None,
        "latency_ms": latency_ms or random.uniform(200, 1800),
        "input_payload": {"query": f"sample input for {tool_name}"},
        "output_payload": {"result": f"output from {tool_name}"},
        "input_schema_hash": "a3f9b2" + tool_name[:4].ljust(4, "0"),
        "output_schema_hash": "c4d5e6" + tool_name[:4].ljust(4, "0"),
        "token_usage": {"input": token_in, "output": token_out},
        "schema_drift": drift,
    })


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> None:
    print("Checking collector is up...")
    try:
        httpx.get(f"{COLLECTOR}/health", timeout=3).raise_for_status()
        print("✓ Collector reachable\n")
    except Exception:
        print("✗ Collector not reachable. Start it with: python scripts/start_collector.py")
        raise SystemExit(1)

    # -----------------------------------------------------------------------
    # Multi-turn agent trace (shows context growth chart)
    # -----------------------------------------------------------------------
    print("=== Multi-turn agent trace (trace_id: demo-trace-001) ===")
    context_steps = [8_000, 22_000, 47_000, 81_000, 124_000, 158_000]
    for i, ctx in enumerate(context_steps, 1):
        llm_call(turn=i, context_used=ctx, trace_id=TRACE_ID)
        time.sleep(0.05)

    # High-context second trace (quality scorer: bad context efficiency)
    print("\n=== High-context trace (trace_id: demo-trace-002) ===")
    high_ctx_steps = [50_000, 110_000, 165_000, 185_000]
    for i, ctx in enumerate(high_ctx_steps, 1):
        llm_call(turn=i, context_used=ctx, trace_id=TRACE_ID_2)
        time.sleep(0.05)

    # -----------------------------------------------------------------------
    # web_search — healthy tool, many calls, one timeout failure
    # -----------------------------------------------------------------------
    print("\n=== web_search — 12 success + 1 timeout failure ===")
    for i in range(12):
        tool_call(
            "web_search",
            status="success",
            latency_ms=random.uniform(300, 900),
            token_in=random.randint(120, 200),
            token_out=random.randint(40, 120),
            trace_id=TRACE_ID,
            sequence_no=i,
        )
    # One timeout — high latency
    tool_call(
        "web_search",
        status="failure",
        failure_type="timeout",
        latency_ms=random.uniform(8000, 12000),
        trace_id=TRACE_ID,
    )
    print("  13 calls posted")

    # -----------------------------------------------------------------------
    # database_query — slow, repeated timeout failures (pattern)
    # Intelligence: should cluster as "timeout" pattern, ~50% failure rate
    # -----------------------------------------------------------------------
    print("\n=== database_query — 4 success + 4 timeout failures ===")
    for _ in range(4):
        tool_call(
            "database_query",
            status="success",
            latency_ms=random.uniform(1200, 3500),
            token_out=random.randint(50, 150),
            trace_id=TRACE_ID,
        )
    for _ in range(4):
        tool_call(
            "database_query",
            status="failure",
            failure_type="timeout",
            latency_ms=random.uniform(7500, 11000),
            trace_id=TRACE_ID_2,
        )
    print("  8 calls posted — 50% timeout failure rate")

    # -----------------------------------------------------------------------
    # send_email — mostly failing with api_error (bad pattern)
    # Intelligence: should cluster as "api_error" pattern, ~67% failure rate
    # -----------------------------------------------------------------------
    print("\n=== send_email — 2 success + 4 api_error failures ===")
    for _ in range(2):
        tool_call("send_email", token_in=50, token_out=20, latency_ms=random.uniform(150, 400))
    for _ in range(4):
        tool_call(
            "send_email",
            status="failure",
            failure_type="api_error",
            latency_ms=random.uniform(200, 600),
        )
    print("  6 calls posted — 67% api_error failure rate")

    # -----------------------------------------------------------------------
    # code_execution — fast, reliable, consistent latency
    # Intelligence: should score grade A
    # -----------------------------------------------------------------------
    print("\n=== code_execution — 8 success calls, fast and consistent ===")
    for _ in range(8):
        tool_call(
            "code_execution",
            latency_ms=random.uniform(80, 150),  # consistent fast latency
            token_in=random.randint(200, 400),
            token_out=random.randint(100, 300),
        )
    print("  8 calls posted")

    # -----------------------------------------------------------------------
    # fetch_document — large output tokens (optimization candidate)
    # Intelligence: token_out = 15,000-18,000 → 7.5-9% of 200k context → flagged
    # -----------------------------------------------------------------------
    print("\n=== fetch_document — 6 calls, large output (optimization candidate) ===")
    for _ in range(6):
        tool_call(
            "fetch_document",
            latency_ms=random.uniform(500, 1500),
            token_in=random.randint(50, 100),
            token_out=random.randint(15_000, 18_000),  # big output → optimization target
            trace_id=TRACE_ID,
        )
    print("  6 calls posted — avg ~16,000 output tokens (>5% of 200k context)")

    # -----------------------------------------------------------------------
    # summarise_text — medium output, borderline candidate
    # -----------------------------------------------------------------------
    print("\n=== summarise_text — 4 calls, medium output ===")
    for _ in range(4):
        tool_call(
            "summarise_text",
            latency_ms=random.uniform(300, 800),
            token_in=random.randint(200, 500),
            token_out=random.randint(11_000, 13_000),  # ~5.5-6.5% of 200k
            trace_id=TRACE_ID,
        )
    print("  4 calls posted — avg ~12,000 output tokens")

    # -----------------------------------------------------------------------
    # Schema drift alerts
    # -----------------------------------------------------------------------
    print("\n=== Schema drift alerts ===")
    tool_call("file_reader", token_in=80, token_out=300)
    time.sleep(0.05)
    tool_call(
        "file_reader",
        drift={
            "detected": True,
            "missing_fields": ["content"],
            "unexpected_fields": ["raw_text"],
            "expected_hash": "beef1234cafe5678",
        },
    )
    tool_call(
        "web_search",
        drift={
            "detected": True,
            "missing_fields": [],
            "unexpected_fields": ["sponsored", "position"],
            "expected_hash": "dead0000beef1111",
        },
    )
    print("  2 drift events posted")

    # -----------------------------------------------------------------------
    # More LLM calls on a second model
    # -----------------------------------------------------------------------
    print("\n=== LLM calls on claude-opus-4-5 ===")
    for _ in range(4):
        post({
            "event_type": "llm_call",
            "trace_id": str(uuid.uuid4()),
            "session_id": str(uuid.uuid4()),
            "agent_id": "default",
            "timestamp": ts(),
            "sequence_no": 0,
            "model": "claude-opus-4-5",
            "latency_ms": random.uniform(1500, 4000),
            "finish_reason": "end_turn",
            "token_usage": {
                "input": random.randint(800, 2000),
                "output": random.randint(200, 600),
                "cache_read": 0,
            },
            "context_window_used": random.randint(1000, 3000),
            "context_window_limit": 200_000,
            "context_utilisation": random.uniform(0.005, 0.015),
            "messages_count": random.randint(2, 8),
        })
    print("  4 calls posted")

    print("\n✓ Demo data loaded. Open http://localhost:7844 to explore.")
    print("\nTry these views:")
    print("  Overview      → http://localhost:7844")
    print("  Tools         → http://localhost:7844/tools")
    print("  Calls         → http://localhost:7844/calls")
    print("  Alerts        → http://localhost:7844/alerts")
    print("  LLM           → http://localhost:7844/llm")
    print(f"  Trace detail  → http://localhost:7844/llm/trace/{TRACE_ID}")
    print("  Intelligence  → http://localhost:7844/intelligence")
    print()
    print("What to expect on /intelligence:")
    print("  Failure Patterns  → database_query (50% timeout), send_email (67% api_error)")
    print("  Optimization      → fetch_document (~16k tokens), summarise_text (~12k tokens)")
    print("  Tool Quality      → code_execution = A, send_email/database_query = D/F")
    print("  Run Quality       → demo-trace-001 (efficient), demo-trace-002 (high context)")


if __name__ == "__main__":
    main()
