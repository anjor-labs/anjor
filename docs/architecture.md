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
└──────────────────────────────────────────────────────────────┘
```

## Module Map

| Module | Responsibility |
|--------|----------------|
| `agentscope/__init__.py` | Public API: `patch()`, `configure()`, `get_pipeline()` |
| `core/events/` | Immutable Pydantic event models, EventTypeRegistry |
| `core/pipeline/` | Async queue, handler dispatch, built-in handlers |
| `core/config.py` | Typed configuration (env + TOML + defaults) |
| `interceptors/patch.py` | httpx monkey-patcher |
| `interceptors/parsers/` | URL-matched response parsers → events |
| `collector/storage/` | StorageBackend ABC + SQLiteBackend |
| `collector/api/` | FastAPI app factory + routes |
| `collector/service.py` | Wires storage + pipeline |
| `analysis/drift/` | Fingerprinting + DriftDetector |
| `analysis/classification/` | FailureClassifier rules |

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

## Extension Points

- **New event type**: Add to `core/events/`, register in `EventTypeRegistry`.
- **New storage backend**: Implement `StorageBackend` ABC.
- **New parser**: Implement `BaseParser`, register in `ParserRegistry`.
- **New handler**: Implement `EventHandler` protocol, add to pipeline.
- **New analysis rule**: Implement `BaseRule`, pass to `FailureClassifier`.
