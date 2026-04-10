# agentscope/collector

Local event persistence and query API.

## Key abstractions

- **`CollectorService`** — wires `SQLiteBackend` + `EventPipeline`. Call `start()`/`stop()` or use as a lifespan dependency.
- **`storage/SQLiteBackend`** — WAL mode, batch writer (flush every N events or M ms), in-memory mode for tests. Implements `StorageBackend` ABC — swap for Postgres in Phase 2.
- **`api/app.py`** — FastAPI app factory. Takes config/service, returns `FastAPI` instance with lifespan.
- **Routes:** `POST /events` (ingest), `GET /tools` (list), `GET /tools/{name}` (detail), `GET /health`.

## Architecture fit

The collector is the persistence and query layer. It never imports from `interceptors/` — it only receives serialised event dicts via the REST API or directly from the pipeline handler.

## Extension

New storage backend: implement `StorageBackend` ABC, inject into `CollectorService`.
