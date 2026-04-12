# Anjor — Detailed Code Flow

This document traces every meaningful code path through the system, from `anjor.patch()` to a row in SQLite. Read this when you want to understand *exactly* what happens, not just the broad strokes.

---

## 1. Install (`anjor.patch()`)

```
anjor.patch()
  └── anjor/__init__.py:patch()
        ├── AnjorConfig()              # loads env vars + TOML + defaults
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

## 3. AnthropicParser — Response → LLMCallEvent + ToolCallEvents

```
AnthropicParser.parse(url, request_body, response_body, latency_ms, status_code)
  ├── is_success = 200 <= status_code < 300
  ├── model = request_body.get("model", "")
  ├── context_limit = _MODEL_CONTEXT_LIMITS.get(model, 200_000)
  ├── Extract token_usage from response_body["usage"]
  │     └── LLMTokenUsage(input=input_tokens, output=output_tokens, cache_read=...)
  ├── Extract trace_id / session_id from request_body["metadata"] (if present)
  ├── finish_reason = response_body.get("stop_reason")
  ├── context_window_used = token_usage.input + token_usage.output
  │
  ├── _prompt_hash(messages)       # SHA-256 of structural shape: [(role, content_type), ...]
  ├── _system_prompt_hash(system)  # SHA-256 of system prompt string, or None
  │
  ├── LLMCallEvent(
  │     model, latency_ms, token_usage,
  │     context_window_used, context_window_limit=context_limit,
  │     context_utilisation  ← auto-computed by model_validator (used/limit, capped at 1.0)
  │     prompt_hash, system_prompt_hash,
  │     messages_count=len(messages), finish_reason,
  │     trace_id, session_id
  │   )
  │
  ├── content = response_body.get("content", [])
  ├── tool_use_blocks = [b for b in content if b["type"] == "tool_use"]
  │
  ├── [No blocks, success] → return [LLMCallEvent]      # text-only response
  │
  ├── [No blocks, failure] → return [LLMCallEvent, ToolCallEvent(tool_name="unknown", FAILURE)]
  │
  └── [Has blocks] → return [LLMCallEvent] + for each tool_use block:
        ├── tool_name = block["name"]
        ├── sanitised_input = _sanitise(block["input"])
        ├── input_schema_hash = fingerprint(sanitised_input)
        └── ToolCallEvent(
              tool_name, status, failure_type, latency_ms,
              input_payload=sanitised_input,
              input_schema_hash, token_usage,
              trace_id, session_id          # same values as LLMCallEvent above
            )
```

Every `/v1/messages` call produces at minimum one `LLMCallEvent`. Tool-use responses also produce `ToolCallEvent`(s). The `trace_id` and `session_id` are identical across all events from the same HTTP call.

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

## 7. SQLiteBackend — Event Routing + Write

```
SQLiteBackend.write_event(event_dict)
  ├── event_type = event_dict.get("event_type")
  │
  ├── [event_type == "llm_call"] → write_llm_event(event_dict)
  │     └── conn.execute(
  │           "INSERT INTO llm_calls (...) VALUES (...)",
  │           (trace_id, session_id, agent_id, timestamp, model, latency_ms,
  │            token_input, token_output, token_cache_read,
  │            context_window_used, context_window_limit, context_utilisation,
  │            prompt_hash, system_prompt_hash, messages_count, finish_reason)
  │         )
  │           └── conn.commit()  [direct write — no batching for LLM events]
  │
  └── [event_type == "tool_call"] → batch path
        ├── _lock.acquire()
        ├── self._batch.append(event_dict)
        ├── should_flush = len(self._batch) >= batch_size
        └── _lock.release()
              └── [should_flush] → _flush()

SQLiteBackend._flush()
  └── conn.executemany(
        "INSERT INTO tool_calls (...) VALUES (...)",   # parameterised
        [_row_from_event(e) for e in batch]
      )
        └── conn.commit()

# Timer flush regardless of batch size:
SQLiteBackend._periodic_flush()   [asyncio.Task]
  └── loop: asyncio.sleep(batch_interval_ms / 1000)  →  _flush()
```

DECISION: `write_event()` routes by `event_type` so callers (CollectorHandler) always call one method and the backend decides where data goes. Adding a new event type only requires a new branch here, not changes in callers.

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

## 11. LLM Query Path (GET /llm, GET /llm/trace/{trace_id})

```
GET /llm
  └── FastAPI route               # collector/api/routes/llm.py
        └── CollectorService.storage.list_llm_summaries()
              └── SQLiteBackend.list_llm_summaries()
                    └── SELECT model, COUNT(*), AVG(latency_ms), AVG(token_input),
                               AVG(token_output), AVG(context_utilisation)
                        FROM llm_calls
                        GROUP BY model
                        ORDER BY COUNT(*) DESC

GET /llm/trace/{trace_id}
  └── FastAPI route
        └── CollectorService.storage.query_llm_calls(LLMQueryFilters(trace_id=...))
              └── SQLiteBackend.query_llm_calls(filters)
                    └── SELECT * FROM llm_calls
                        WHERE trace_id = ?
                        ORDER BY timestamp ASC
                          └── 404 if result is empty
```

---

## 12. Shutdown

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
    ├── LLMCallEvent (frozen Pydantic)               ← always emitted
    │     model, latency_ms, finish_reason
    │     token_usage (input, output, cache_read)
    │     context_window_used, context_window_limit
    │     context_utilisation  (auto-computed)
    │     prompt_hash, system_prompt_hash
    │     messages_count
    │     trace_id, session_id, agent_id, timestamp, sequence_no
    │
    └── ToolCallEvent (frozen Pydantic)              ← per tool_use block
          tool_name, status, failure_type, latency_ms
          input_payload (sanitised), output_payload
          input_schema_hash, output_schema_hash
          token_usage (input, output)
          schema_drift (detected, missing_fields, unexpected_fields, expected_hash)
          trace_id, session_id, agent_id, timestamp, sequence_no
              │ same trace_id as LLMCallEvent
    │
    ▼ model_dump(mode="json")
dict → POST /events → EventIngestRequest (extra="allow") → dict
    │
    ▼ write_event() routes by event_type
    ├── "llm_call"  → INSERT INTO llm_calls (direct)
    └── "tool_call" → batch → INSERT INTO tool_calls
    │
    ▼ SELECT
    ├── GET /llm               → LLMSummaryItem[]  (grouped by model)
    ├── GET /llm/trace/{id}    → LLMDetailItem[]
    ├── GET /tools             → ToolSummary[]
    └── GET /tools/{name}      → ToolDetailResponse
```
