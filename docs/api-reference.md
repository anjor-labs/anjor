# API Reference

The collector runs at `http://localhost:7843` by default. All endpoints are local-only.

## Events

| Method | Path | Description |
|--------|------|-------------|
| `POST` | `/events` | Ingest a tool call, LLM call, or span event |
| `POST` | `/flush` | Force-flush pending batch writes; returns `{"flushed": N}` |

### POST /events

Accepts a JSON body matching the event schema. The `event_type` field routes the event to the correct table.

```json
{
  "event_type": "tool_call",
  "tool_name": "web_search",
  "trace_id": "...",
  "session_id": "...",
  "agent_id": "default",
  "project": "myapp",
  "timestamp": "2026-04-17T12:00:00Z",
  "status": "success",
  "latency_ms": 342.5,
  "input_payload": { "query": "..." },
  "output_payload": { "results": [...] }
}
```

For LLM calls, add: `model`, `token_input`, `token_output`, `token_cache_read`, `token_cache_write`, `context_window_used`, `context_window_limit`.

---

## Tools

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/tools` | All tools with aggregated stats |
| `GET` | `/tools/{name}` | Single tool detail with latency percentiles |

**Query params:** `?project=myapp`, `?since_minutes=120`

---

## LLM

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/llm` | LLM summary by model |
| `GET` | `/llm/usage/daily` | Daily token usage by model |
| `GET` | `/llm/sources` | Unique source tags in llm_calls |
| `GET` | `/llm/trace/{trace_id}` | All LLM calls for a trace |

**Query params:** `?project=myapp`, `?days=14`, `?since_minutes=120`

---

## Calls

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/calls` | Paginated raw event log |

**Query params:** `?tool_name=web_search`, `?project=myapp`, `?drift_only=true`, `?limit=100`, `?offset=0`

---

## MCP

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/mcp` | Per-server and per-tool MCP aggregates |

**Query params:** `?days=N`

---

## Sessions

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/sessions` | Session list |
| `GET` | `/sessions/{id}/replay` | Chronological turn timeline |
| `GET` | `/sessions/{id}/summary` | Stored natural-language summary (404 if none) |
| `POST` | `/sessions/{id}/archive` | Archive a session |
| `POST` | `/sessions/{id}/unarchive` | Restore an archived session |
| `DELETE` | `/sessions/{id}` | Permanently delete session and all events |
| `PATCH` | `/sessions/{id}/project` | Re-tag a session's project |

**Query params for `/sessions`:** `?limit=50`, `?offset=0`, `?archived=false`

---

## Traces

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/traces` | Trace list, newest first |
| `GET` | `/traces/{id}/graph` | DAG graph for a single trace |

---

## Intelligence

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/intelligence/failures` | Failure clusters sorted by rate |
| `GET` | `/intelligence/optimization` | Token hog tools + savings estimates |
| `GET` | `/intelligence/quality/tools` | Per-tool quality scores + grade |
| `GET` | `/intelligence/quality/runs` | Per-trace run quality scores + grade |
| `GET` | `/intelligence/attribution` | Per-agent token and failure attribution |
| `GET` | `/intelligence/root_causes` | Ranked root-cause hypotheses |
| `GET` | `/intelligence/prompt_versions` | LLM calls grouped by system prompt hash |

---

## Projects

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/projects` | Per-project aggregated stats |

---

## Health

| Method | Path | Description |
|--------|------|-------------|
| `GET` | `/health` | Uptime, queue depth, DB path, version |
