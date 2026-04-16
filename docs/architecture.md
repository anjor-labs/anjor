# Anjor — Architecture

## Layer Diagram

```
┌──────────────────────────────────────────────────────────────┐
│              Your Agent Code / Claude Code / Gemini CLI       │
└───────────┬─────────────────────────────────┬────────────────┘
            │ httpx calls (unmodified)         │ JSONL transcripts
┌───────────▼──────────────────┐  ┌────────────▼───────────────┐
│      PatchInterceptor         │  │     WatcherManager          │
│  patches httpx.Client.send    │  │  polls every 2 s            │
│  captures req+resp            │  │  ClaudeWatcher / Gemini     │
│  injects W3C traceparent      │  │  Codex / AntiGravity        │
│  → ParserRegistry → events    │  │  → events                   │
└───────────┬──────────────────┘  └────────────┬───────────────┘
            └─────────────────┬────────────────┘
                              ▼
┌──────────────────────────────────────────────────────────────┐
│                      EventPipeline                            │
│  asyncio.Queue with backpressure (drop + stats on full)       │
│  asyncio.gather() → all handlers concurrently                 │
│  handler exceptions logged + swallowed, never raised          │
└───────────────┬─────────────────────────────────┬────────────┘
                │                                 │
       CollectorHandler                       LogHandler
       (POST /events)                         (structlog)
                │
┌───────────────▼──────────────────────────────────────────────┐
│                    CollectorService                           │
│  SQLiteBackend (WAL mode, batch writer, aiosqlite)            │
│                                                               │
│  REST API routes:                                             │
│    POST /events            ingest event                       │
│    POST /flush             force-flush batch queue            │
│    GET  /tools             tool summaries                     │
│    GET  /tools/{name}      tool detail + latency percentiles  │
│    GET  /llm               LLM summary by model               │
│    GET  /llm/usage/daily   daily token breakdown              │
│    GET  /llm/sources       source tags                        │
│    GET  /llm/trace/{id}    all LLM calls for a trace          │
│    GET  /calls             paginated raw event log            │
│    GET  /mcp               MCP server + tool aggregates       │
│    GET  /traces            trace list                         │
│    GET  /traces/{id}/graph DAG for a single trace             │
│    GET  /projects          project list with counts           │
│    GET  /health            uptime, queue depth, db path       │
│    GET  /intelligence/failures         failure clusters       │
│    GET  /intelligence/optimization     token hog tools        │
│    GET  /intelligence/quality/tools    per-tool grades A–F    │
│    GET  /intelligence/quality/runs     per-trace grades A–F   │
│    GET  /intelligence/attribution      per-agent breakdown    │
└───────────────────────────┬──────────────────────────────────┘
                            │ query raw event history
┌───────────────────────────▼──────────────────────────────────┐
│                   Intelligence & Analysis Layer               │
│                                                               │
│  FailureClusterer    — group failures by (tool, type),        │
│                        compute rate, natural-language         │
│                        description and actionable suggestion  │
│                                                               │
│  TokenOptimizer      — flag tools whose avg output exceeds    │
│                        5% of context window; estimate token   │
│                        waste and cost savings per 1k calls    │
│                                                               │
│  QualityScorer       — ToolQualityScore: reliability ×0.5 +  │
│                        schema stability ×0.3 + latency CV ×0.2│
│                        AgentRunQualityScore: context eff ×0.5 │
│                        + failure recovery ×0.3 + diversity ×0.2│
│                        Grades: A / B / C / D / F              │
│                                                               │
│  TraceGraph          — DAG reconstruction, Kahn topological   │
│                        sort, cycle detection                  │
│                                                               │
│  AttributionAnalyser — per-agent token + failure breakdown    │
└──────────────────────────────────────────────────────────────┘
```

## Module Map

| Module | Responsibility |
|--------|----------------|
| `anjor/__init__.py` | Public API: `patch()`, `configure()`, `get_pipeline()` |
| `anjor/client.py` | `Client` — programmatic read-only access to SQLite (no collector needed) |
| `anjor/models.py` | Public response types importable from `anjor.models` |
| `anjor/cli.py` | `anjor start / mcp / watch-transcripts` CLI entry points |
| `core/events/` | Immutable Pydantic event models (`ToolCallEvent`, `LLMCallEvent`, `AgentSpanEvent`), `EventTypeRegistry` |
| `core/pipeline/` | Async queue, handler dispatch, `CollectorHandler`, `LogHandler` |
| `core/config.py` | `AnjorConfig` — typed config via env vars, `.anjor.toml`, or init kwargs |
| `interceptors/patch.py` | httpx monkey-patcher; W3C `traceparent` injection on every outbound request |
| `interceptors/parsers/anthropic.py` | `/v1/messages` → `LLMCallEvent` + `ToolCallEvent`s |
| `interceptors/parsers/openai.py` | `/v1/chat/completions` → `LLMCallEvent` + `ToolCallEvent`s |
| `interceptors/parsers/gemini.py` | `generateContent` → `LLMCallEvent` + `ToolCallEvent`s |
| `interceptors/parsers/registry.py` | URL-matched parser selection |
| `collector/storage/base.py` | `StorageBackend` ABC + `QueryFilters`, `LLMQueryFilters` |
| `collector/storage/sqlite.py` | `SQLiteBackend` — WAL mode, batch writer, aiosqlite |
| `collector/storage/migrations/` | `001`–`006` numbered `.sql` files; run on startup |
| `collector/api/app.py` | FastAPI factory; mounts `/ui/` static dashboard |
| `collector/api/routes/` | One module per route group: events, tools, llm, calls, mcp, traces, projects, intelligence, health |
| `collector/api/schemas.py` | Pydantic response models for all endpoints |
| `collector/service.py` | Wires storage + pipeline; `CollectorService` lifespan |
| `watchers/base.py` | `BaseTranscriptWatcher` — poll every 2 s, persist offsets to `~/.anjor/` |
| `watchers/claude.py` | Parses `~/.claude/projects/**/*.jsonl` |
| `watchers/gemini.py` | Parses `~/.gemini/tmp/**/*.json` |
| `watchers/codex.py` | Stub — not yet implemented |
| `watchers/antigravity.py` | Stub — not yet implemented |
| `watchers/registry.py` | `build_active_watchers()` factory |
| `watchers/manager.py` | `WatcherManager` — daemon threads, never block main thread |
| `mcp_server.py` | MCP stdio server — exposes `anjor_status` tool |
| `analysis/drift/` | `fingerprint()`, `DriftDetector` |
| `analysis/classification/` | `FailureClassifier` — priority-ordered rule chain |
| `analysis/context/` | `ContextWindowTracker`, `ContextHogDetector` |
| `analysis/prompt/` | `PromptDriftDetector` |
| `analysis/tracing/graph.py` | `TraceGraph` — DAG reconstruction, topological sort, cycle detection |
| `analysis/tracing/attribution.py` | `AttributionAnalyser` — per-agent token + failure breakdown |
| `analysis/intelligence/` | `FailureClusterer`, `TokenOptimizer`, `QualityScorer` |
| `dashboard/static/` | Vanilla JS + Tailwind CDN dashboard; served at `:7843/ui/`; add new pages here |

## Design Decisions

### Why frozen Pydantic models for events?
Events are facts — they describe what happened. Mutation after creation would allow bugs to corrupt observability data silently. Frozen models make this impossible.

### Why asyncio.Queue with backpressure?
The interceptor runs on the agent's critical path. If the pipeline blocks, the agent blocks. Backpressure (drop + counter) ensures the agent is never impacted.

### Why a StorageBackend ABC?
SQLite ships by default. Postgres and ClickHouse can be plugged in without touching any application code — the factory in `collector/storage/__init__.py` handles routing.

### Why separate API schemas from domain models?
Domain models evolve for business reasons. API schemas evolve for client compatibility. Coupling them creates unnecessary churn.

### Why priority-ordered classification rules?
Timeout → SchemaDrift → APIError → Unknown gives deterministic results regardless of rule registration order. New rules are added as new classes, not modifications.

### Why does the intelligence layer sit above the collector rather than inside it?
The analysers are pure functions over raw row dicts — no I/O, no async. This makes them independently testable without a running database, and means any caller (API route, CLI tool, background job) can invoke them directly without going through the HTTP stack.

### Why a reliability hard floor at zero in QualityScorer?
A tool with 0% success rate should always grade F regardless of latency consistency or schema stability. Surfacing a "D" for a completely broken tool would mislead engineers.

### Why W3C traceparent for multi-agent tracing?
The `traceparent` header is the standard for distributed tracing interoperability. Injecting it into outbound httpx requests means downstream agents automatically inherit the trace context without any code changes.

### Why transcript-watching rather than SDK callbacks?
Transcript watching is zero-code: the developer changes nothing. SDK callbacks require importing Anjor into agent code, creating a dependency. The watcher approach makes Anjor genuinely invisible.

## Storage Schema

Three primary tables in `~/.anjor/anjor.db`:

| Table | Key columns | Purpose |
|-------|-------------|---------|
| `tool_calls` | `tool_name`, `status`, `failure_type`, `latency_ms`, `input_payload`, `output_payload`, `*_schema_hash`, `drift_*`, `source`, `project` | Every tool use observed |
| `llm_calls` | `model`, `token_input/output/cache_*`, `context_window_*`, `prompt_hash`, `system_prompt_hash`, `finish_reason`, `source`, `project` | Every LLM API call observed |
| `agent_spans` | `span_id`, `parent_span_id`, `trace_id`, `span_kind`, `agent_name`, `token_*`, `tool_calls_count` | Multi-agent DAG spans |

Supporting tables: `schema_snapshots`, `drift_events`, `prompt_snapshots`.

## Extension Points

- **New event type**: Add to `core/events/`, register in `EventTypeRegistry`, add routing in `sqlite.py` `write_event()`.
- **New storage backend**: Implement `StorageBackend` ABC; wire in `collector/storage/__init__.py`.
- **New parser**: Implement `BaseParser`, register in `build_default_registry()`.
- **New handler**: Implement `EventHandler` protocol, add to pipeline.
- **New classification rule**: Implement `BaseRule`, pass to `FailureClassifier`.
- **New intelligence analyser**: Add a route in `routes/intelligence.py`.
- **New watcher**: Extend `BaseTranscriptWatcher`, add to `registry.py`.
- **New dashboard page**: Create `dashboard/static/foo.html`, add to `NAV_LINKS` in `utils.js`.

## Test Coverage by Layer

| Layer | Approach |
|-------|----------|
| Events, config, pipeline | Pure unit tests — no I/O |
| Fingerprinting, drift, classification, intelligence | Unit + Hypothesis property-based tests |
| Storage | In-memory SQLite (`:memory:`) — real SQL, no mocks |
| Collector API | FastAPI `TestClient` — real HTTP, in-memory storage |
| Integration | Real SQLite + TestClient + `respx` mock for provider HTTP |
| E2E | Simulated agent run, events verified end-to-end |
| Watchers | JSONL fixture files in `tests/watchers/fixtures/` |
