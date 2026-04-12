# anjor/core/pipeline

Async event pipeline with backpressure and concurrent handler dispatch.

## Key abstractions

- **`EventPipeline`** — asyncio.Queue with configurable max size. `put()` is non-blocking and never raises. Dropped events increment `stats.dropped`.
- **`EventHandler`** — Protocol (structural typing). Anything with `async handle(event)` and a `name` qualifies.
- **`CollectorHandler`** — POSTs events to the collector REST API. Swallows errors.
- **`LogHandler`** — Logs events via structlog at DEBUG level.
- **`NoOpHandler`** — Discards events. Used in tests or as a placeholder.

## Architecture fit

The pipeline sits between the interceptor and all downstream consumers (storage, logging). Its job is to absorb bursts, decouple the agent's call stack from I/O, and ensure handler failures are isolated.

## Extension

Add a new handler: implement the `EventHandler` protocol, call `pipeline.add_handler()`.
