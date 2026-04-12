# Anjor — Quickstart

This walks you through running Anjor locally, capturing tool calls and LLM events, and querying the results. No cloud. No account. Everything runs on your machine.

---

## Prerequisites

Python 3.11+ and pip.

```bash
pip install anjor
```

---

## Step 1 — Start the Collector

```bash
anjor start
```

You should see:
```
Anjor collector  http://localhost:7843/health
Anjor dashboard  http://localhost:7843/ui/
Database         anjor.db
```

Verify it's running:
```bash
curl http://localhost:7843/health
# {"status":"ok","uptime_seconds":1.2,"queue_depth":0,"db_path":"anjor.db"}
```

Leave this running in a terminal tab.

---

## Step 2 — Instrument Your Agent

Add one line at the top of your agent file:

```python
import anjor
anjor.patch()   # that's it
```

Every httpx call your process makes is now captured. The Anthropic, OpenAI, and Google Gemini SDKs all use httpx internally, so no other changes are required.

---

## Step 3 — Make Tool Calls

### Anthropic

```python
import anjor
anjor.patch()

import anthropic

client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env

response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    tools=[{
        "name": "web_search",
        "description": "Search the web",
        "input_schema": {
            "type": "object",
            "properties": {"query": {"type": "string"}},
            "required": ["query"]
        }
    }],
    messages=[{"role": "user", "content": "Search for the latest AI news"}]
)
```

### OpenAI

```python
import anjor
anjor.patch()

from openai import OpenAI

client = OpenAI()  # reads OPENAI_API_KEY from env

response = client.chat.completions.create(
    model="gpt-4o",
    tools=[{
        "type": "function",
        "function": {
            "name": "web_search",
            "description": "Search the web",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string"}},
                "required": ["query"]
            }
        }
    }],
    messages=[{"role": "user", "content": "Search for the latest AI news"}]
)
```

### Google Gemini

```python
import anjor
anjor.patch()

import google.generativeai as genai

genai.configure(api_key="YOUR_GEMINI_API_KEY")
model = genai.GenerativeModel("gemini-2.0-flash")
response = model.generate_content("Search for the latest AI news")
```

---

## Step 4 — Query the Data

As soon as the call completes, events are in SQLite and queryable.

```bash
# All tools seen
curl http://localhost:7843/tools

# Tool detail with latency percentiles
curl http://localhost:7843/tools/web_search

# LLM call summaries by model
curl http://localhost:7843/llm

# Paginated event log
curl http://localhost:7843/calls

# Failure patterns with suggestions
curl http://localhost:7843/intelligence/failures

# Token optimization opportunities
curl http://localhost:7843/intelligence/optimization

# Per-tool quality scores (A–F)
curl http://localhost:7843/intelligence/quality/tools
```

Or open the dashboard at `http://localhost:7843/ui/`.

---

## Without a Real API Key (Using respx)

You don't need a real API key to see the full flow. Use `respx` to mock the response:

```python
import anjor
anjor.patch()

import httpx
import respx

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"

FAKE_RESPONSE = {
    "content": [{
        "type": "tool_use",
        "id": "toolu_01",
        "name": "web_search",
        "input": {"query": "AI news"},
    }],
    "model": "claude-sonnet-4-6",
    "usage": {"input_tokens": 150, "output_tokens": 60},
}

with respx.mock:
    respx.post(ANTHROPIC_URL).mock(return_value=httpx.Response(200, json=FAKE_RESPONSE))
    with httpx.Client() as client:
        client.post(
            ANTHROPIC_URL,
            json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "Search"}]},
            headers={"x-api-key": "fake-key"},
        )

# Now query
import requests
print(requests.get("http://localhost:7843/tools/web_search").json())
```

---

## Multi-Agent Tracing

Anjor automatically injects W3C `traceparent` headers into outbound httpx requests. If your orchestrator calls sub-agents over HTTP, the trace context propagates automatically — no code changes needed.

You can also pass a `trace_id` explicitly in Anthropic request metadata to correlate events across calls:

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    messages=[...],
    metadata={"trace_id": "my-session-001"},  # shared across all events in this trace
)
```

View traces:
```bash
curl http://localhost:7843/traces
curl http://localhost:7843/traces/{trace_id}/graph
```

---

## Configuration

```bash
# Use a specific DB path
ANJOR_DB_PATH=./my_project.db python my_agent.py

# Flush after every event (useful in development)
ANJOR_BATCH_SIZE=1 ANJOR_BATCH_INTERVAL_MS=100 python my_agent.py

# Debug logging
ANJOR_LOG_LEVEL=DEBUG python my_agent.py
```

Or via `.anjor.toml` in your project root:

```toml
db_path = "my_project.db"
batch_size = 10
batch_interval_ms = 200
log_level = "DEBUG"
```

---

## Common Issues

**No events appearing in `/tools`**

The batch writer flushes every 500ms or 100 events. If you only made one call and queried immediately, wait 600ms or set `ANJOR_BATCH_SIZE=1`.

**`curl` returns empty list `[]`**

Confirm your agent completed a tool-using call (not just a text response). Text-only responses produce an `LLMCallEvent` visible at `/llm`, not `/tools`.

**`anjor.patch()` installs but nothing is intercepted**

Your agent may be using `requests` instead of `httpx`. Anjor patches httpx only. All three major provider SDKs (Anthropic, OpenAI, Gemini) use httpx by default.

**Collector exits immediately**

Check the port isn't already in use: `lsof -i :7843`. Change with `ANJOR_COLLECTOR_PORT=7844`.
