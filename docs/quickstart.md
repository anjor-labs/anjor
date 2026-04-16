# Anjor — Quickstart

No cloud. No account. Everything runs on your machine.

---

## Install

```bash
pipx install "anjor[mcp]"   # recommended — includes MCP server support
# or
pip install "anjor[mcp]"
```

---

## Option A — Observe Claude Code or Gemini CLI Sessions

Best if you use Claude Code or Gemini CLI and want a dashboard of your own sessions without changing anything.

### Via MCP (auto-starts with Claude Code)

Add to `.mcp.json` in your project root:

```json
{
  "mcpServers": {
    "anjor": {
      "command": "anjor",
      "args": ["mcp", "--watch-transcripts"]
    }
  }
}
```

Anjor starts automatically when Claude Code opens. It ingests your session transcripts, exposes `anjor_status` as a tool Claude can call to check session health, and serves the dashboard at `http://localhost:7843/ui/`.

For Gemini CLI, add to `.gemini/settings.json`:

```json
{
  "mcpServers": {
    "anjor": {
      "command": "anjor",
      "args": ["mcp", "--watch-transcripts", "--providers", "gemini"]
    }
  }
}
```

### Standalone (no MCP required)

```bash
anjor start --watch-transcripts
```

Opens `http://localhost:7843/ui/` immediately. Polls for new transcript entries every 2 seconds.

```bash
# Watch specific providers or adjust poll interval
anjor start --watch-transcripts --providers claude,gemini --poll-interval 5.0

# List detected agents on this machine
anjor watch-transcripts --list-providers
```

---

## Option B — Instrument Your Own Agent

Best for developers building custom AI agents who want real-time telemetry.

### Step 1 — Start the collector

```bash
anjor start
```

```
Anjor collector  http://localhost:7843/health
Anjor dashboard  http://localhost:7843/ui/
Database         ~/.anjor/anjor.db
```

### Step 2 — One line in your agent

```python
import anjor
anjor.patch()   # that's it — instrument httpx automatically
```

Every httpx call in the process is now captured. The Anthropic, OpenAI, and Gemini SDKs all use httpx internally.

### Step 3 — Make calls normally

**Anthropic:**
```python
import anjor, anthropic
anjor.patch()

client = anthropic.Anthropic()
response = client.messages.create(
    model="claude-sonnet-4-6",
    max_tokens=1024,
    tools=[{
        "name": "web_search",
        "description": "Search the web",
        "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}
    }],
    messages=[{"role": "user", "content": "Search for AI news"}]
)
```

**OpenAI:**
```python
import anjor
from openai import OpenAI
anjor.patch()

client = OpenAI()
response = client.chat.completions.create(
    model="gpt-4o",
    tools=[{"type": "function", "function": {"name": "web_search", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}}}}],
    messages=[{"role": "user", "content": "Search for AI news"}]
)
```

**Gemini:**
```python
import anjor, google.generativeai as genai
anjor.patch()

genai.configure(api_key="YOUR_GEMINI_API_KEY")
model = genai.GenerativeModel("gemini-2.0-flash")
response = model.generate_content("Search for AI news")
```

### Step 4 — Query the data

```bash
# Force-flush the batch writer (useful in development)
curl -X POST http://localhost:7843/flush

# Tool summaries with latency percentiles
curl http://localhost:7843/tools

# LLM usage by model
curl http://localhost:7843/llm

# Failure patterns with fix suggestions
curl http://localhost:7843/intelligence/failures

# Per-tool quality grades (A–F)
curl http://localhost:7843/intelligence/quality/tools
```

Or open the dashboard at `http://localhost:7843/ui/`.

---

## Programmatic Access (no running collector needed)

```python
import anjor

with anjor.Client("~/.anjor/anjor.db") as client:
    for tool in client.tools():
        print(f"{tool.tool_name:30s}  calls={tool.call_count}  ok={tool.success_rate:.0%}")

    patterns  = client.intelligence.failures()
    quality   = client.intelligence.quality()
```

---

## Multi-Agent Tracing

Anjor automatically injects W3C `traceparent` headers into outbound httpx requests. If your orchestrator calls sub-agents over HTTP, the trace context propagates with no code changes.

You can also set a `trace_id` explicitly in Anthropic request metadata:

```python
response = client.messages.create(
    model="claude-sonnet-4-6",
    messages=[...],
    metadata={"trace_id": "my-session-001"},
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
ANJOR_DB_PATH=./my_project.db python my_agent.py
ANJOR_BATCH_SIZE=1 python my_agent.py          # flush after every event
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

## Testing Without a Real API Key

```python
import anjor, httpx, respx
anjor.patch()

FAKE_RESPONSE = {
    "content": [{"type": "tool_use", "id": "t1", "name": "web_search", "input": {"query": "AI"}}],
    "model": "claude-sonnet-4-6",
    "usage": {"input_tokens": 150, "output_tokens": 60},
}

with respx.mock:
    respx.post("https://api.anthropic.com/v1/messages").mock(
        return_value=httpx.Response(200, json=FAKE_RESPONSE)
    )
    with httpx.Client() as c:
        c.post("https://api.anthropic.com/v1/messages",
               json={"model": "claude-sonnet-4-6", "messages": [{"role": "user", "content": "go"}]},
               headers={"x-api-key": "fake"})
```

---

## Common Issues

**No events in `/tools` after a call**

The batch writer flushes every 500 ms. Force-flush for immediate results:
```bash
curl -X POST http://localhost:7843/flush
```
Or set `ANJOR_BATCH_SIZE=1` to bypass batching entirely.

**Empty list `[]` from `/tools`**

Text-only responses produce an `LLMCallEvent` visible at `/llm`, not `/tools`. Tool calls only appear when the model used a tool.

**Nothing intercepted by `anjor.patch()`**

Check that your agent uses httpx (directly or via Anthropic/OpenAI/Gemini SDK). Anjor does not patch the `requests` library.

**Transcript watcher finds no sessions**

Run `anjor watch-transcripts --list-providers` to see which agents are detected. Claude Code transcripts require at least one completed session in `~/.claude/projects/`.

**Watcher posts events before collector is ready**

Expected — the collector may not be bound yet when the watcher first polls. Events dropped on the first poll are picked up on the next 2-second cycle.
