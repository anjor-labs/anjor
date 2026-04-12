# AgentScope — Architecture

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
│          /intelligence/failures                               │
│          /intelligence/optimization                           │
│          /intelligence/quality/tools                          │
│          /intelligence/quality/runs                           │
└───────────────────────────┬──────────────────────────────────┘
                            │ query raw event history
┌───────────────────────────▼──────────────────────────────────┐
│                   Intelligence Layer  (Phase 3)               │
│                                                               │
│  FailureClusterer    — group failures by (tool, type),        │
│                        compute rate, generate NL description  │
│                        and actionable suggestion              │
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
└──────────────────────────────────────────────────────────────┘
```

## Module Map

| Module | Phase | Responsibility |
|--------|-------|----------------|
| `agentscope/__init__.py` | 1–3 | Public API: `patch()`, `configure()`, `get_pipeline()`, intelligence classes |
| `core/events/` | 1–2 | Immutable Pydantic event models, EventTypeRegistry |
| `core/pipeline/` | 1 | Async queue, handler dispatch, built-in handlers |
| `core/config.py` | 1 | Typed configuration (env + TOML + defaults) |
| `interceptors/patch.py` | 1 | httpx monkey-patcher |
| `interceptors/parsers/` | 1–2 | URL-matched response parsers → events |
| `collector/storage/` | 1–3 | StorageBackend ABC + SQLiteBackend (incl. Phase 3 query methods) |
| `collector/api/routes/intelligence.py` | 3 | `/intelligence/*` endpoints — delegates to intelligence analysers |
| `collector/api/` | 1–3 | FastAPI app factory + all route modules |
| `collector/service.py` | 1 | Wires storage + pipeline |
| `analysis/drift/` | 1 | Fingerprinting + DriftDetector |
| `analysis/classification/` | 1 | FailureClassifier rules |
| `analysis/context/` | 2 | ContextWindowTracker, ContextHogDetector |
| `analysis/prompt/` | 2 | PromptDriftDetector |
| `analysis/intelligence/failure_clustering.py` | 3 | FailureClusterer — groups historical failures into patterns |
| `analysis/intelligence/token_optimizer.py` | 3 | TokenOptimizer + CostEstimator |
| `analysis/intelligence/quality_scorer.py` | 3 | QualityScorer — per-tool and per-run grades |
| `dashboard/` | 1–3 | Next.js local dashboard (`:7844`) |

## Design Decisions

### Why frozen Pydantic models for events?
Events are facts — they describe what happened. Mutation after creation would allow bugs to corrupt observability data silently. Frozen models make this impossible.

### Why asyncio.Queue with backpressure?
The interceptor runs on the agent's critical path. If the pipeline blocks, the agent blocks. Backpressure (drop + counter) ensures the agent is never impacted.

### Why StorageBackend ABC?
SQLite is Phase 1. Postgres is Phase 2. New backends drop in without touching any application code.

### Why separate API schemas from domain models?
Domain models evolve for business reasons. API schemas evolve for client compatibility. Coupling them creates unnecessary churn.

### Why priority-ordered classification rules?
Timeout > SchemaDrift > APIError > Unknown gives deterministic results regardless of rule registration order. New rules are added as new classes, not modifications.

### Why does the intelligence layer sit above the collector rather than inside it?
The analysers are pure functions over raw row dicts — no I/O, no async. This makes them independently testable without a running database, and means any caller (API route, CLI tool, future background job) can invoke them directly without going through the HTTP stack.

### Why a reliability hard floor at zero in QualityScorer?
A tool with 0% success rate should always grade F regardless of latency consistency or schema stability. Surfacing a "D" for a completely broken tool would mislead engineers into thinking there's something partially functional about it.

### Phase 3 intelligence is heuristic, not ML
Clustering by `(tool_name, failure_type)` and computing a weighted score is fast, deterministic, and fully explainable — no training data required. ML-based anomaly detection can replace these heuristics in Phase 4 once enough real production telemetry has been collected.

## Extension Points

- **New event type**: Add to `core/events/`, register in `EventTypeRegistry`.
- **New storage backend**: Implement `StorageBackend` ABC.
- **New parser**: Implement `BaseParser`, register in `ParserRegistry`.
- **New handler**: Implement `EventHandler` protocol, add to pipeline.
- **New classification rule**: Implement `BaseRule`, pass to `FailureClassifier`.
- **New intelligence analyser**: Implement `BaseAnalyser`, add a route in `routes/intelligence.py`.
- **New quality dimension**: Add a weight key to `_TOOL_WEIGHTS` or `_RUN_WEIGHTS` in `quality_scorer.py` and implement the scoring method.

## Test Coverage by Layer

| Layer | Approach |
|-------|----------|
| Events, config, pipeline | Pure unit tests — no I/O |
| Fingerprinting, drift, classification, intelligence | Unit + Hypothesis property-based tests |
| Storage | In-memory SQLite (`:memory:`) — real SQL, no mocks |
| Collector API | FastAPI `TestClient` — real HTTP, in-memory storage |
| Integration | Real SQLite + TestClient + `respx` mock for Anthropic HTTP |
| E2E | Simulated agent run, events verified end-to-end |
