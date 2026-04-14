# Anjor — Architecture

## Layer Diagram

```
┌──────────────────────────────────────────────────────────────┐
│                        Your Agent Code                        │
└───────────────────────────────┬──────────────────────────────┘
                                │ httpx calls (unmodified)
┌───────────────────────────────▼──────────────────────────────┐
│                     PatchInterceptor                          │
│  monkey-patches httpx.Client.send / AsyncClient.send          │
│  captures req + resp → ParserRegistry → EventPipeline.put()  │
└───────────────────────────────┬──────────────────────────────┘
                                │ BaseEvent (immutable)
┌───────────────────────────────▼──────────────────────────────┐
│                      EventPipeline                            │
│  asyncio.Queue with backpressure                              │
│  asyncio.gather() → all handlers concurrently                 │
│  handler exceptions logged + swallowed, never raised          │
└───────────────┬───────────────────────────────────┬──────────┘
                │                                   │
       CollectorHandler                         LogHandler
       (POST /events)                           (structlog)
                │
┌───────────────▼──────────────────────────────────────────────┐
│                    CollectorService                           │
│  SQLiteBackend (WAL mode, batch writer)                       │
│  FastAPI REST API                                             │
│  Routes: /events  /tools  /llm  /calls  /health              │
│          /mcp  /traces  /traces/{id}/graph                    │
│          /intelligence/failures                               │
│          /intelligence/optimization                           │
│          /intelligence/quality/tools                          │
│          /intelligence/quality/runs                           │
│          /intelligence/attribution                            │
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
| `anjor/__init__.py` | Public API: `patch()`, `configure()`, `get_pipeline()`, intelligence classes |
| `core/events/` | Immutable Pydantic event models, EventTypeRegistry |
| `core/pipeline/` | Async queue, handler dispatch, built-in handlers |
| `core/config.py` | Typed configuration (env + TOML + defaults) |
| `interceptors/patch.py` | httpx monkey-patcher, W3C traceparent injection |
| `interceptors/traceparent.py` | W3C Trace Context helpers |
| `interceptors/parsers/anthropic.py` | Anthropic `/v1/messages` → LLMCallEvent + ToolCallEvents |
| `interceptors/parsers/openai.py` | OpenAI `/v1/chat/completions` → LLMCallEvent + ToolCallEvents |
| `interceptors/parsers/gemini.py` | Gemini `generateContent` → LLMCallEvent + ToolCallEvents |
| `interceptors/parsers/registry.py` | URL-matched parser selection |
| `collector/storage/` | StorageBackend ABC + SQLiteBackend (WAL, batch writer, spans) |
| `collector/api/routes/mcp.py` | `GET /mcp` — per-server and per-tool MCP aggregates |
| `collector/api/` | FastAPI app factory + all route modules |
| `collector/service.py` | Wires storage + pipeline |
| `analysis/drift/` | Fingerprinting + DriftDetector |
| `analysis/classification/` | FailureClassifier rules |
| `analysis/context/` | ContextWindowTracker, ContextHogDetector |
| `analysis/prompt/` | PromptDriftDetector |
| `analysis/tracing/graph.py` | TraceGraph — DAG reconstruction, topological sort |
| `analysis/tracing/attribution.py` | AttributionAnalyser — per-agent token/failure breakdown |
| `analysis/intelligence/` | FailureClusterer, TokenOptimizer, QualityScorer |
| `dashboard/static/` | Bundled dashboard (HTML + vanilla JS), served on `:7843/ui/` |

## Design Decisions

### Why frozen Pydantic models for events?
Events are facts — they describe what happened. Mutation after creation would allow bugs to corrupt observability data silently. Frozen models make this impossible.

### Why asyncio.Queue with backpressure?
The interceptor runs on the agent's critical path. If the pipeline blocks, the agent blocks. Backpressure (drop + counter) ensures the agent is never impacted.

### Why a StorageBackend ABC?
SQLite ships by default. Postgres and ClickHouse can be plugged in without touching any application code — the factory pattern in `collector/storage/__init__.py` handles routing.

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

## Extension Points

- **New event type**: Add to `core/events/`, register in `EventTypeRegistry`.
- **New storage backend**: Implement `StorageBackend` ABC; wire in `collector/storage/__init__.py`.
- **New parser**: Implement `BaseParser`, register in `build_default_registry()`.
- **New handler**: Implement `EventHandler` protocol, add to pipeline.
- **New classification rule**: Implement `BaseRule`, pass to `FailureClassifier`.
- **New intelligence analyser**: Add a route in `routes/intelligence.py`.

## Test Coverage by Layer

| Layer | Approach |
|-------|----------|
| Events, config, pipeline | Pure unit tests — no I/O |
| Fingerprinting, drift, classification, intelligence | Unit + Hypothesis property-based tests |
| Storage | In-memory SQLite (`:memory:`) — real SQL, no mocks |
| Collector API | FastAPI `TestClient` — real HTTP, in-memory storage |
| Integration | Real SQLite + TestClient + `respx` mock for provider HTTP |
| E2E | Simulated agent run, events verified end-to-end |
