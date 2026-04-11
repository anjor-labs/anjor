# AgentScope — Quickstart: See It In Action

This walks you through running AgentScope locally, making tool calls, and seeing the data. No cloud. No account. Everything runs on your machine.

---

## Prerequisites

```bash
cd agentscope
bash scripts/dev_setup.sh   # creates .venv, installs deps, copies .env
source .venv/bin/activate
```

---

## Step 1 — Start the Collector

The collector is the local sidecar that receives events and stores them in SQLite.

```bash
python scripts/start_collector.py
```

You should see:
```
Starting AgentScope Collector on port 7843
Database: agentscope.db
Health: http://localhost:7843/health
INFO: Uvicorn running on http://127.0.0.1:7843
```

Verify it's running:
```bash
curl http://localhost:7843/health
# {"status":"ok","uptime_seconds":1.2,"queue_depth":0,"db_path":"agentscope.db"}
```

Leave this running in a terminal tab.

---

## Step 2 — Instrument Your Agent

In a new terminal (or a Python script), add one line at the top:

```python
import agentscope
agentscope.patch()   # that's it
```

Now every httpx call your process makes is captured. The Anthropic SDK uses httpx internally, so it works with zero other changes.

---

## Step 3 — Make Tool Calls

Here's a minimal example that generates tool calls. You need an Anthropic API key:

```python
import agentscope
agentscope.patch()

import anthropic

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

response = client.messages.create(
    model="claude-3-5-sonnet-20241022",
    max_tokens=1024,
    tools=[
        {
            "name": "web_search",
            "description": "Search the web for information",
            "input_schema": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Search query"}
                },
                "required": ["query"]
            }
        }
    ],
    messages=[
        {"role": "user", "content": "Search for the latest news about AI agents"}
    ]
)

print(response.content)
```

Run it:
```bash
ANTHROPIC_API_KEY=sk-ant-... python my_agent.py
```

---

## Step 4 — Query the Data

As soon as the call completes, the tool call event is in SQLite and queryable.

### List all tools seen

```bash
curl http://localhost:7843/tools
```

```json
[
  {
    "tool_name": "web_search",
    "call_count": 1,
    "success_rate": 1.0,
    "avg_latency_ms": 1243.5
  }
]
```

### Tool detail with latency percentiles

```bash
curl http://localhost:7843/tools/web_search
```

```json
{
  "tool_name": "web_search",
  "call_count": 1,
  "success_count": 1,
  "failure_count": 0,
  "success_rate": 1.0,
  "avg_latency_ms": 1243.5,
  "p50_latency_ms": 1243.5,
  "p95_latency_ms": 1243.5,
  "p99_latency_ms": 1243.5
}
```

### Query the SQLite database directly

```bash
sqlite3 agentscope.db "SELECT tool_name, status, latency_ms, timestamp FROM tool_calls;"
```

```
web_search|success|1243.5|2026-04-10T19:03:21.412345+00:00
```

---

## Step 5 — See Schema Drift In Action

Make the same tool call twice with a different input shape — AgentScope detects the structural change.

```python
import agentscope
agentscope.patch()

from agentscope.analysis.drift.detector import DriftDetector
from agentscope.analysis.drift.fingerprint import fingerprint, diff_schemas

detector = DriftDetector()

# First payload — establishes baseline
payload_v1 = {"query": "AI news", "limit": 10}
result = detector.check("web_search", payload_v1)
print(result)   # None — baseline stored

# Same structure — no drift
payload_v2 = {"query": "Python tips", "limit": 5}
result = detector.check("web_search", payload_v2)
print(result)   # SchemaDrift(detected=False, ...)

# Different structure — drift detected
payload_v3 = {"query": "AI news", "offset": 0}   # "limit" gone, "offset" added
result = detector.check("web_search", payload_v3)
print(result)
# SchemaDrift(
#   detected=True,
#   missing_fields=["limit"],
#   unexpected_fields=["offset"],
#   expected_hash="a3f9..."
# )
```

---

## Step 6 — See Failure Classification In Action

```python
from agentscope.analysis.classification.failure import (
    FailureClassifier,
    ClassificationContext,
)

clf = FailureClassifier()

# Timeout
ctx = ClassificationContext(error_message="connection timed out", latency_ms=9000)
print(clf.analyse(ctx))   # FailureType.TIMEOUT

# Schema drift
ctx = ClassificationContext(has_schema_drift=True)
print(clf.analyse(ctx))   # FailureType.SCHEMA_DRIFT

# API error
ctx = ClassificationContext(status_code=429)
print(clf.analyse(ctx))   # FailureType.API_ERROR

# Unknown fallback
ctx = ClassificationContext()
print(clf.analyse(ctx))   # FailureType.UNKNOWN
```

---

## Step 7 — Run the Full Test Suite

Confirms everything is wired correctly:

```bash
pytest
```

Expected output:
```
201 passed in 1.15s
Total coverage: 97.78%
Required test coverage of 95% reached.
```

---

## Without a Real API Key (Using respx to Mock)

You don't need an actual Anthropic API key to see the flow. Use `respx` to replay a realistic response:

```python
import agentscope
agentscope.patch()

import httpx
import respx

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

FAKE_RESPONSE = {
    "content": [
        {
            "type": "tool_use",
            "id": "toolu_01",
            "name": "web_search",
            "input": {"query": "AI news"},
        }
    ],
    "usage": {"input_tokens": 150, "output_tokens": 60},
}

with respx.mock:
    respx.post(ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=FAKE_RESPONSE))

    with httpx.Client() as client:
        response = client.post(
            ANTHROPIC_URL,
            json={
                "model": "claude-3-5-sonnet-20241022",
                "messages": [{"role": "user", "content": "Search for AI news"}],
            },
            headers={"x-api-key": "fake-key"},
        )

print(response.json()["content"])
```

Then query:
```bash
curl http://localhost:7843/tools/web_search
```

The tool call appears in storage even though no real API was called.

---

## What's In the Database

```sql
-- See all recorded tool calls
SELECT
    tool_name,
    status,
    failure_type,
    round(latency_ms, 1) as latency_ms,
    input_schema_hash,
    token_usage_input,
    token_usage_output,
    timestamp
FROM tool_calls
ORDER BY timestamp DESC
LIMIT 20;

-- Drift events by tool
SELECT tool_name, drift_detected, drift_missing, drift_unexpected
FROM tool_calls
WHERE drift_detected = 1;

-- Aggregated success rate per tool
SELECT
    tool_name,
    count(*) as calls,
    round(avg(latency_ms), 1) as avg_ms,
    sum(CASE WHEN status = 'success' THEN 1 ELSE 0 END) * 100 / count(*) as success_pct
FROM tool_calls
GROUP BY tool_name;
```

---

## Configuration

Override any default via env var (no restart needed for new processes):

```bash
# Use a specific DB path
AGENTSCOPE_DB_PATH=./my_project.db python my_agent.py

# Smaller batches — useful for development (flush more often)
AGENTSCOPE_BATCH_SIZE=1 AGENTSCOPE_BATCH_INTERVAL_MS=100 python my_agent.py

# Debug logging
AGENTSCOPE_LOG_LEVEL=DEBUG python my_agent.py
```

Or via `.agentscope.toml` in your project root:

```toml
mode = "patch"
db_path = "my_project.db"
batch_size = 10
batch_interval_ms = 200
log_level = "DEBUG"
```

Or programmatically:

```python
import agentscope
from agentscope.core.config import AgentScopeConfig

agentscope.patch(config=AgentScopeConfig(
    db_path="my_project.db",
    batch_size=1,
))
```

---

## Common Issues

**No events appearing in `/tools`**

The batch writer flushes every 500ms or 100 events. If you only made one call and queried immediately, wait 600ms or set `AGENTSCOPE_BATCH_SIZE=1`.

**`curl` returns empty list `[]`**

The collector is running but no events have been written yet. Confirm your agent actually completed a tool-using call (not just a text response).

**`agentscope.patch()` installs but nothing is intercepted**

Your agent may be using `requests` instead of `httpx`. The current interceptor patches httpx only. The Anthropic Python SDK uses httpx by default.

**Collector exits immediately**

Check the port isn't already in use: `lsof -i :7843`. Change with `AGENTSCOPE_COLLECTOR_PORT=7844`.

---

## Phase 2 — LLM Call Intelligence

### Query LLM call summaries

```bash
curl http://localhost:7843/llm
```

```json
[
  {
    "model": "claude-3-5-sonnet-20241022",
    "call_count": 5,
    "avg_latency_ms": 1150.2,
    "avg_token_input": 312.0,
    "avg_token_output": 88.4,
    "avg_context_utilisation": 0.002
  }
]
```

### Get all LLM calls for a trace

```bash
curl http://localhost:7843/llm/trace/my-trace-id
```

### Track context window growth in code

```python
from agentscope import ContextWindowTracker

tracker = ContextWindowTracker(thresholds=[0.7, 0.9])

# Call after each LLM response
alert = tracker.record(
    trace_id="session-abc",
    context_used=145_000,
    context_limit=200_000,
)
if alert:
    print(f"Context threshold {alert.threshold:.0%} crossed — utilisation {alert.utilisation:.1%}")

# Get growth rate (avg tokens added per turn)
rate = tracker.growth_rate("session-abc")
print(f"Growing at {rate:,.0f} tokens/turn")
```

### Detect bloated tool outputs

```python
from agentscope import ContextHogDetector

detector = ContextHogDetector(threshold=0.10, context_window_limit=200_000)

result = detector.record("web_search", output_bytes=len(raw_tool_output))
if result.is_hog:
    print(
        f"{result.tool_name} consumes ~{result.context_fraction:.1%} of context window "
        f"({result.estimated_tokens:,} tokens avg)"
    )

# Summary of all tools sorted by context fraction
for r in detector.summary():
    print(f"{r.tool_name}: {r.context_fraction:.2%}")
```

### Detect system prompt drift

```python
from agentscope import PromptDriftDetector

detector = PromptDriftDetector()

# First call per agent — establishes baseline
result = detector.check("my-agent", system_prompt="You are a helpful assistant.")
print(result)  # None

# Subsequent call — returns PromptDrift(detected=False) if unchanged
result = detector.check("my-agent", system_prompt="You are a helpful assistant.")
print(result.detected)  # False

# Changed prompt — drift detected
result = detector.check("my-agent", system_prompt="You are a coding assistant.")
print(result.detected)         # True
print(result.calls_since_last_change)  # resets to 0
```

### Trace ID consistency across LLM and tool events

Pass `trace_id` in the Anthropic request metadata to correlate LLM call and tool events:

```python
import httpx

response = httpx.post(
    "https://api.anthropic.com/v1/messages",
    json={
        "model": "claude-3-5-sonnet-20241022",
        "max_tokens": 1024,
        "messages": [{"role": "user", "content": "Search for AI news"}],
        "metadata": {"trace_id": "my-session-001"},  # shared across all events
    },
    headers={"x-api-key": "sk-ant-..."},
)
```

The `trace_id` propagates to both the `LLMCallEvent` and any `ToolCallEvent`(s) produced from that call.

---

## What's In the llm_calls Table

```sql
SELECT
    model,
    round(latency_ms, 1) as latency_ms,
    token_input,
    token_output,
    token_cache_read,
    round(context_utilisation * 100, 2) as context_pct,
    finish_reason,
    trace_id,
    timestamp
FROM llm_calls
ORDER BY timestamp DESC
LIMIT 20;
```
