# AgentScope — Detailed Code Flow

This document traces every meaningful code path through the system, from `agentscope.patch()` to a row in SQLite. Read this when you want to understand *exactly* what happens, not just the broad strokes.

---

## 1. Install (`agentscope.patch()`)

```
agentscope.patch()
  └── agentscope/__init__.py:patch()
        ├── AgentScopeConfig()              # loads env vars + TOML + defaults
        ├── EventPipeline()                 # asyncio.Queue(maxsize=1000), no worker yet
        ├── build_default_registry()        # ParserRegistry with AnthropicParser + OpenAIParser
        └── PatchInterceptor.install()
              ├── threading.Lock (acquire)
              ├── _original_sync_send  = httpx.Client.send      # save original
              ├── _original_async_send = httpx.AsyncClient.send # save original
              ├── httpx.Client.send       = wrapped_send()      # replace with wrapper
              ├── httpx.AsyncClient.send  = wrapped_async_send()# replace with wrapper
              └── threading.Lock (release)
```

After this point every httpx call anywhere in the process goes through the wrapper.

---

## 2. Agent Makes an httpx Call

```python
# Agent code (unchanged):
response = httpx.Client().post("https://api.anthropic.com/v1/messages", json={...})
```

Actual execution path:

```
httpx.Client.send  →  wrapped_send()           # interceptors/patch.py
  ├── start = time.monotonic()
  ├── original_send(client, request, **kwargs)  # real HTTP call to Anthropic
  ├── latency_ms = (time.monotonic() - start) * 1000
  ├── PatchInterceptor._process(request, response, latency_ms)
  │     ├── url = str(request.url)
  │     ├── request_body  = _body_to_dict(request.content)   # bytes → dict, {} on error
  │     ├── response_body = _body_to_dict(response.content)
  │     ├── ParserRegistry.parse(url, req_body, resp_body, latency_ms, status_code)
  │     │     ├── find_parser(url)  →  AnthropicParser (can_parse returns True)
  │     │     └── AnthropicParser.parse(...)  →  [ToolCallEvent, ...]  (see §3)
  │     └── for event in events: EventPipeline.put(event)    (see §4)
  └── return response   # unmodified — agent sees normal httpx.Response
```

`_process` is wrapped in a broad `except Exception` — any crash here is logged and swallowed. The agent's call always completes normally.

---

## 3. AnthropicParser — Response → ToolCallEvent

```
AnthropicParser.parse(url, request_body, response_body, latency_ms, status_code)
  ├── is_success = 200 <= status_code < 300
  ├── Extract token_usage from response_body["usage"]
  │     └── TokenUsage(input=input_tokens, output=output_tokens)
  ├── Extract trace_id / session_id from request_body["metadata"] (if present)
  ├── content = response_body.get("content", [])
  ├── tool_use_blocks = [b for b in content if b["type"] == "tool_use"]
  │
  ├── [No blocks, success] → return []           # text-only response, nothing to record
  │
  ├── [No blocks, failure] → build one ToolCallEvent(tool_name="unknown", status=FAILURE)
  │
  └── [Has blocks] → for each tool_use block:
        ├── tool_name = block["name"]            # e.g. "web_search"
        ├── tool_input = block["input"]          # the args dict
        ├── sanitised_input = _sanitise(tool_input)
        │     └── recursively redacts keys matching *api_key*, *secret*, *token*, etc.
        ├── input_schema_hash  = fingerprint(sanitised_input)   # SHA-256 of structure
        ├── output_schema_hash = fingerprint({})                 # output not yet known
        └── ToolCallEvent(
              tool_name, status, failure_type,
              latency_ms, input_payload=sanitised_input,
              input_schema_hash, output_schema_hash,
              token_usage, trace_id, session_id
            )
              └── model_validator runs:
                    - success + failure_type set → ValidationError
                    - failure + failure_type None → coerce to UNKNOWN
```

Each `tool_use` block becomes exactly one `ToolCallEvent`. For 2 tool calls in one response: 2 events are returned and each is enqueued separately.

---

## 4. EventPipeline.put() — Enqueue

```
EventPipeline.put(event)                        # core/pipeline/pipeline.py
  ├── asyncio.Queue.put_nowait(event)
  │     ├── [Queue not full] → enqueued, stats.enqueued += 1, return True
  │     └── [QueueFull]      → stats.dropped += 1, log warning, return False
  └── caller (PatchInterceptor._process) never sees QueueFull — it's caught inside put()
```

The queue has a background worker running since `pipeline.start()` (called by `CollectorService.start()` during FastAPI lifespan):

```
EventPipeline._worker()  [asyncio.Task, running in background]
  └── loop:
        ├── asyncio.wait_for(queue.get(), timeout=0.1)
        │     ├── [Got event] → _dispatch(event)
        │     └── [TimeoutError] → continue  (checks _running again)
        └── asyncio.CancelledError → break
```

---

## 5. EventPipeline._dispatch() — Fan-out to Handlers

```
EventPipeline._dispatch(event)
  └── asyncio.gather(
        CollectorHandler.handle(event),
        LogHandler.handle(event),
        ...,
        return_exceptions=True          # one crash never kills the others
      )
        ├── CollectorHandler.handle(event)     (see §6)
        ├── LogHandler.handle(event)
        │     └── structlog.debug("event", event_type=..., trace_id=...)
        └── [Any exception in any handler]
              └── logged to structlog, stats.handler_errors += 1, swallowed
```

All handlers run concurrently. Order of completion is not guaranteed and not required.

---

## 6. CollectorHandler → REST API → SQLiteBackend

```
CollectorHandler.handle(event)               # core/pipeline/handlers.py
  ├── payload = event.model_dump(mode="json")
  └── httpx.AsyncClient.post(
        "http://localhost:7843/events",
        json=payload,
        timeout=2.0
      )
        └── [POST /events]  FastAPI route      # collector/api/routes/events.py
              ├── Validate Content-Length <= max_payload_size_kb
              ├── Pydantic parses body → EventIngestRequest
              └── CollectorService.storage.write_event(body.model_dump())
                    └── SQLiteBackend.write_event(event_dict)    (see §7)
```

---

## 7. SQLiteBackend — Batch Write to Disk

```
SQLiteBackend.write_event(event_dict)
  ├── _lock.acquire()
  ├── self._batch.append(event_dict)
  ├── should_flush = len(self._batch) >= batch_size   (default: 100)
  └── _lock.release()
        └── [should_flush] → _flush()

SQLiteBackend._flush()
  ├── _lock.acquire()
  ├── batch = self._batch[:]   # snapshot
  ├── self._batch.clear()
  ├── _lock.release()
  └── conn.executemany(
        "INSERT INTO tool_calls (...) VALUES (...)",   # parameterised — no f-strings
        [_row_from_event(e) for e in batch]
      )
        └── conn.commit()

# Also runs on a timer regardless of batch size:
SQLiteBackend._periodic_flush()   [asyncio.Task]
  └── loop: asyncio.sleep(batch_interval_ms / 1000)  →  _flush()
```

`_row_from_event` maps the event dict to a 20-element tuple covering every column in `tool_calls`.

---

## 8. Query Path (GET /tools/{name})

```
GET /tools/web_search
  └── FastAPI route               # collector/api/routes/tools.py
        └── CollectorService.storage.get_tool_summary("web_search")
              └── SQLiteBackend.get_tool_summary("web_search")
                    ├── SELECT status, latency_ms FROM tool_calls WHERE tool_name = ?
                    └── _compute_summary(tool_name, rows)
                          ├── latencies = sorted([row["latency_ms"] for row in rows])
                          ├── success_count = count(status == "success")
                          ├── avg = sum(latencies) / count
                          └── percentile(latencies, 50/95/99)
                                └── data[int(len(data) * p / 100)]
```

Response:
```json
{
  "tool_name": "web_search",
  "call_count": 42,
  "success_count": 40,
  "failure_count": 2,
  "success_rate": 0.952,
  "avg_latency_ms": 234.5,
  "p50_latency_ms": 210.0,
  "p95_latency_ms": 480.0,
  "p99_latency_ms": 650.0
}
```

---

## 9. Schema Drift Detection (DriftDetector)

`DriftDetector` is not wired into the default pipeline automatically — it's a component you call when building a custom handler or parser extension.

```
DriftDetector.check("web_search", payload)
  ├── current_hash = fingerprint(payload)
  │     └── _structural_shape(payload)   # replaces all values with type names
  │           e.g. {"query": "hello", "limit": 10}
  │               → {"limit": "int", "query": "str"}   (keys sorted)
  │           → json.dumps(shape, sort_keys=True)
  │           → sha256(canonical).hexdigest()
  │
  ├── [No baseline for this tool] → store as baseline, return None
  │
  └── [Baseline exists]
        ├── [hashes match] → SchemaDrift(detected=False, ...)
        └── [hashes differ]
              ├── diff_schemas(current_payload, baseline_payload)
              │     ├── missing_fields    = sorted(reference_keys - current_keys)
              │     └── unexpected_fields = sorted(current_keys - reference_keys)
              └── SchemaDrift(
                    detected=True,
                    missing_fields=[...],
                    unexpected_fields=[...],
                    expected_hash=baseline_hash
                  )
```

---

## 10. Failure Classification (FailureClassifier)

```
FailureClassifier.analyse(ClassificationContext(...))
  └── for rule in sorted(rules, key=lambda r: r.priority):
        └── rule.matches(ctx)?
              ├── TimeoutRule   (priority 10): latency >= threshold OR "timeout" in error_msg
              ├── SchemaDriftRule (priority 20): ctx.has_schema_drift
              ├── APIErrorRule  (priority 30): status_code >= 400 OR api error keywords
              └── UnknownRule   (priority 999): always True
                    → return rule.failure_type  # first match wins
```

---

## 11. Shutdown

```
CollectorService.stop()
  ├── EventPipeline.stop()
  │     ├── self._running = False
  │     ├── Drain remaining queue items synchronously
  │     │     └── _dispatch(event) for each remaining event
  │     ├── _worker_task.cancel()
  │     └── await _worker_task  (catches CancelledError)
  └── SQLiteBackend.close()
        ├── _flush_task.cancel()
        ├── _flush()   (final flush of any remaining batch)
        └── conn.close()
```

No events are lost on clean shutdown.

---

## Data Shape Summary

```
httpx Request/Response
    │
    ▼ AnthropicParser
ToolCallEvent (frozen Pydantic)
    │  tool_name, status, failure_type, latency_ms
    │  input_payload (sanitised), output_payload
    │  input_schema_hash, output_schema_hash
    │  token_usage (input, output)
    │  schema_drift (detected, missing_fields, unexpected_fields, expected_hash)
    │  trace_id, session_id, agent_id, timestamp, sequence_no
    │
    ▼ model_dump(mode="json")
dict → POST /events → EventIngestRequest (Pydantic) → dict
    │
    ▼ _row_from_event()
20-tuple → INSERT INTO tool_calls
    │
    ▼ SELECT + _compute_summary()
ToolSummary → ToolDetailResponse → JSON
```
