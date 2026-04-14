"""Seed realistic demo data into a running collector for dashboard development."""

from __future__ import annotations

import random
import time
import uuid
from datetime import UTC, datetime, timedelta

import httpx

COLLECTOR = "http://127.0.0.1:7843"

TOOLS = ["web_search", "read_file", "write_file", "parse_html", "fetch_url", "run_code"]

MCP_TOOLS = {
    "github":      ["create_pull_request", "search_issues", "get_file_contents", "list_commits", "create_issue"],
    "filesystem":  ["read_file", "write_file", "list_directory", "create_directory"],
    "brave_search":["web_search", "local_search"],
    "slack":       ["post_message", "get_channels", "list_messages"],
    "postgres":    ["query", "list_tables", "describe_table"],
}
MODELS = ["claude-opus-4-6", "claude-sonnet-4-6"]
FAILURE_TYPES = ["timeout", "rate_limit", "schema_error", "unknown"]


def ts(offset_minutes: int = 0) -> str:
    return (datetime.now(UTC) - timedelta(minutes=offset_minutes)).isoformat()


def post(path: str, body: dict) -> None:
    try:
        httpx.post(f"{COLLECTOR}{path}", json=body, timeout=5)
    except Exception as e:
        print(f"  warn: {e}")


def seed_tool_calls() -> None:
    print("Seeding tool calls...")
    trace_ids = [str(uuid.uuid4()) for _ in range(8)]
    seq = 0

    for i in range(120):
        tool = random.choice(TOOLS)
        trace_id = random.choice(trace_ids)
        success = random.random() > (0.3 if tool in ("fetch_url", "run_code") else 0.08)
        latency = random.gauss(280 if tool == "fetch_url" else 95, 40)

        body: dict = {
            "event_type": "tool_call",
            "tool_name": tool,
            "trace_id": trace_id,
            "session_id": "demo-session",
            "agent_id": "demo-agent",
            "timestamp": ts(120 - i),
            "sequence_no": seq,
            "status": "success" if success else "failure",
            "failure_type": None if success else random.choice(FAILURE_TYPES),
            "latency_ms": max(10.0, latency),
            "input_payload": {"query": f"demo input {i}", "tool": tool},
            "output_payload": {"result": "x" * random.randint(50, 800)} if success else {},
            "input_schema_hash": f"hash_{tool}_v{'2' if i > 90 else '1'}",
            "output_schema_hash": f"out_{tool}",
            "token_usage_input": random.randint(100, 800),
            "token_usage_output": random.randint(50, 2000),
        }

        # Inject a few drift events
        if i in (30, 55, 80):
            body["drift_detected"] = True
            body["drift_missing"] = '["query"]'
            body["drift_unexpected"] = '["search_query"]'
            body["drift_expected_hash"] = f"hash_{tool}_v1"

        post("/events", body)
        seq += 1

    print(f"  {seq} tool calls seeded across {len(trace_ids)} traces.")


def seed_llm_calls() -> None:
    print("Seeding LLM calls...")
    trace_ids = [str(uuid.uuid4()) for _ in range(5)]
    seq = 200
    context_limit = 200000

    for trace_id in trace_ids:
        turns = random.randint(3, 8)
        context_used = random.randint(2000, 8000)
        for turn in range(turns):
            context_used += random.randint(1000, 4000)
            model = random.choice(MODELS)
            body = {
                "event_type": "llm_call",
                "model": model,
                "trace_id": trace_id,
                "session_id": "demo-session",
                "agent_id": "demo-agent",
                "timestamp": ts(60 - turn * 5),
                "sequence_no": seq,
                "latency_ms": random.gauss(1800, 300),
                "finish_reason": "end_turn" if turn < turns - 1 else "tool_use",
                "token_usage": {
                    "input": random.randint(500, 3000),
                    "output": random.randint(100, 800),
                    "cache_read": random.randint(0, 200),
                },
                "context_window_used": context_used,
                "context_window_limit": context_limit,
                "context_utilisation": context_used / context_limit,
                "prompt_hash": f"prompt_{trace_id[:8]}",
                "failure_type": None,
                "status": "success",
            }
            post("/events", body)
            seq += 1

    print(f"  {seq - 200} LLM calls seeded across {len(trace_ids)} traces.")


def seed_openai_llm_calls() -> None:
    print("Seeding OpenAI LLM calls...")
    trace_ids = [str(uuid.uuid4()) for _ in range(4)]
    openai_models = ["gpt-4o", "gpt-4o-mini", "gpt-4o", "o1-mini"]
    seq = 400
    context_limit = 128000

    for trace_id in trace_ids:
        turns = random.randint(2, 6)
        context_used = random.randint(1000, 5000)
        model = random.choice(openai_models)
        for turn in range(turns):
            context_used += random.randint(800, 3000)
            body = {
                "event_type": "llm_call",
                "model": model,
                "trace_id": trace_id,
                "session_id": "demo-session",
                "agent_id": "demo-agent",
                "timestamp": ts(90 - turn * 4),
                "sequence_no": seq,
                "latency_ms": random.gauss(1200, 250),
                "finish_reason": "stop" if turn < turns - 1 else "tool_calls",
                "token_usage": {
                    "input": random.randint(300, 2500),
                    "output": random.randint(80, 600),
                },
                "context_window_used": context_used,
                "context_window_limit": context_limit,
                "context_utilisation": context_used / context_limit,
                "prompt_hash": f"oai_prompt_{trace_id[:8]}",
                "failure_type": None,
                "status": "success",
            }
            post("/events", body)
            seq += 1

    print(f"  {seq - 400} OpenAI LLM calls seeded across {len(trace_ids)} traces.")


def seed_mcp_calls() -> None:
    print("Seeding MCP tool calls...")
    # Build flat list of (server, tool) pairs with realistic failure rates per server
    failure_rates = {"github": 0.08, "filesystem": 0.04, "brave_search": 0.15, "slack": 0.10, "postgres": 0.06}
    latency_means = {"github": 320, "filesystem": 45, "brave_search": 480, "slack": 180, "postgres": 95}

    trace_ids = [str(uuid.uuid4()) for _ in range(6)]
    seq = 600
    count = 0

    for _ in range(90):
        server = random.choice(list(MCP_TOOLS.keys()))
        tool_short = random.choice(MCP_TOOLS[server])
        tool_name = f"mcp__{server}__{tool_short}"
        trace_id = random.choice(trace_ids)
        failure_rate = failure_rates[server]
        success = random.random() > failure_rate
        latency = random.gauss(latency_means[server], latency_means[server] * 0.25)

        body: dict = {
            "event_type": "tool_call",
            "tool_name": tool_name,
            "trace_id": trace_id,
            "session_id": "demo-session",
            "agent_id": "demo-agent",
            "timestamp": ts(90 - count),
            "sequence_no": seq,
            "status": "success" if success else "failure",
            "failure_type": None if success else random.choice(["timeout", "api_error", "unknown"]),
            "latency_ms": max(5.0, latency),
            "input_payload": {"tool": tool_name, "args": {"query": f"demo {tool_short}"}},
            "output_payload": {"result": "x" * random.randint(20, 400)} if success else {},
            "input_schema_hash": f"mcp_{server}_{tool_short}_v1",
            "output_schema_hash": f"mcp_{server}_{tool_short}_out",
        }
        post("/events", body)
        seq += 1
        count += 1

    print(f"  {count} MCP tool calls seeded across {len(MCP_TOOLS)} servers.")


def seed_agent_spans() -> None:
    print("Seeding agent spans...")
    # Three separate multi-agent traces
    scenarios = [
        # (trace_name, [(agent_name, span_kind, parent_idx_or_None)])
        ("research_pipeline", [
            ("orchestrator",  "orchestrator", None),
            ("web_researcher", "subagent",     0),
            ("summariser",    "subagent",      0),
            ("fact_checker",  "subagent",      2),
        ]),
        ("data_analysis", [
            ("planner",    "orchestrator", None),
            ("fetcher",    "subagent",     0),
            ("analyser",   "subagent",     0),
            ("reporter",   "subagent",     1),
        ]),
        ("code_review", [
            ("coordinator", "orchestrator", None),
            ("linter",      "subagent",     0),
            ("tester",      "subagent",     0),
        ]),
    ]

    count = 0
    for scenario_name, agents in scenarios:
        trace_id = str(uuid.uuid4())
        span_ids: list[str] = []
        for i, (agent_name, span_kind, parent_idx) in enumerate(agents):
            span_id = str(uuid.uuid4())
            span_ids.append(span_id)
            parent_span_id = span_ids[parent_idx] if parent_idx is not None else None
            offset = len(agents) - i
            success = random.random() > 0.15
            body = {
                "event_type": "agent_span",
                "span_id": span_id,
                "parent_span_id": parent_span_id,
                "trace_id": trace_id,
                "span_kind": "root" if parent_span_id is None else span_kind,
                "agent_name": agent_name,
                "agent_role": f"{scenario_name} — {agent_name}",
                "started_at": ts(offset + 1),
                "ended_at": ts(offset),
                "status": "ok" if success else "error",
                "failure_type": None if success else "timeout",
                "token_input": random.randint(200, 2000),
                "token_output": random.randint(50, 600),
                "tool_calls_count": random.randint(1, 5),
                "llm_calls_count": random.randint(1, 3),
            }
            post("/events", body)
            count += 1

    print(f"  {count} spans seeded across {len(scenarios)} traces.")


if __name__ == "__main__":
    print(f"Checking collector at {COLLECTOR}...")
    try:
        resp = httpx.get(f"{COLLECTOR}/health", timeout=3)
        print(f"  Collector up — {resp.json()}")
    except Exception:
        print("  Collector not reachable. Start it first with: anjor start")
        raise SystemExit(1)

    seed_tool_calls()
    seed_mcp_calls()
    seed_llm_calls()
    seed_openai_llm_calls()
    seed_agent_spans()
    print("\nDone. Open http://localhost:7843/ui/ to see the dashboard.")
