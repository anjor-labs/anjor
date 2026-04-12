# anjor/collector/storage

Storage abstraction layer.

## Key abstractions

- **`StorageBackend`** (ABC) — defines the interface: `write_event`, `query_tool_calls`, `get_tool_summary`, `write_schema_snapshot`, `get_schema_snapshot`, `close`.
- **`SQLiteBackend`** — Phase 1 implementation. aiosqlite, WAL mode, batch writer.
- **`QueryFilters`** — typed filter dataclass for tool call queries.
- **`SchemaSnapshot`** / **`ToolSummary`** — result dataclasses.
- **`migrations/001_initial.sql`** — creates `tool_calls`, `schema_snapshots`, `drift_events` tables. Applied at startup, idempotent.

## Architecture fit

Storage is an implementation detail of the collector. No other layer imports from here directly — they go through `CollectorService`.
