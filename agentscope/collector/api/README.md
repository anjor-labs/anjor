# agentscope/collector/api

FastAPI REST API for the collector service.

## Key abstractions

- **`app.py`** — `create_app(config, service)` factory. Attaches lifespan to start/stop `CollectorService`. Returns a `FastAPI` instance — testable without running a server.
- **`routes/events.py`** — `POST /events`: validates payload size, writes to storage, returns 202.
- **`routes/tools.py`** — `GET /tools`, `GET /tools/{name}`: aggregated stats and latency percentiles.
- **`routes/health.py`** — `GET /health`: uptime, queue depth, db path.
- **`schemas.py`** — Pydantic response models, separate from domain models.

## Architecture fit

The API layer depends on `CollectorService` (and transitively on storage). It does not depend on `interceptors/` or `core/pipeline/` directly.
