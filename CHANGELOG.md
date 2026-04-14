# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.6.0] — 2026-04-14

### Added
- **MCP analytics** — `GET /mcp` endpoint with per-server and per-tool aggregates; MCP tools auto-identified by `mcp__<server>__<tool>` naming convention; supports `?days=N` time filter
- **MCP dashboard page** — server bar chart, server/tool tables with colour-coded server badges, success rates, latency, and day-range selector
- **Day-range selector on Usage page** — pill buttons (1d / 7d / 14d / 30d / 90d / All time) filter both the model summary table and daily trend chart
- **Redesigned Overview page** — 6 clickable hero cards (tool calls, LLM calls, est. cost, MCP calls, failure patterns, drift alerts); three side-by-side panels for top tools, LLM cost by model with 14-day sparkline, and MCP servers; intelligence highlights strip; compact drift events row
- **Pagination on Intelligence page** — 5 cards/page for failure patterns and tool quality sections; 10 rows/page for optimization and run quality tables; per-section independent state preserved across auto-refresh
- `list_llm_summaries(days=)` — optional time filter on the `/llm` summary endpoint
- `list_mcp_server_summaries(days=)` and `list_mcp_tool_summaries(days=)` storage methods
- Dashboard screenshots in `docs/screenshots/`

### Changed
- MCP link added to the dashboard nav bar between Tools and Calls

---

## [0.5.0] — 2026-04-12

### Added
- **OpenAI support** — `anjor.patch()` now captures `/v1/chat/completions` calls, emitting `LLMCallEvent` and `ToolCallEvent` for every OpenAI model call
- **Google Gemini support** — `generateContent` calls are captured with token usage, function calls, and model context limits
- **LLM provider breakdown** — dashboard LLM page shows colour-coded Anthropic / OpenAI / Google badges per model
- **Automatic PyPI publish** — pushing a `vX.Y.Z` tag runs CI and publishes the package automatically; no manual steps required
- `claude-opus-4-6`, `claude-sonnet-4-6`, `claude-haiku-4-5-20251001` added to the Anthropic model map
- Unknown `claude-*` models default to 200k context limit rather than 0

### Changed
- `AnthropicParser` context limit lookup now falls back to 200k for any `claude-*` model not explicitly listed

---

## [0.4.0] — 2026-04-12

### Added
- **Multi-agent tracing** — `AgentSpanEvent` with W3C-compatible parent/child span linking
- **TraceGraph** — DAG reconstruction, topological sort, cycle detection
- **Span storage** — `agent_spans` table; `write_span`, `query_spans`, `list_traces` methods
- **`GET /traces`** and **`GET /traces/{trace_id}/graph`** endpoints
- **Cross-agent attribution** — `GET /intelligence/attribution?trace_id=` breaks down token usage and failure rate per agent
- **W3C traceparent injection** — `anjor.patch()` automatically injects `traceparent` into outbound httpx requests; existing headers are preserved
- Traces dashboard page with indented span tree and attribution panel
- Storage backend abstraction — `create_storage_backend(config)` factory; config fields `storage_backend` and `storage_url`

---

## [0.3.0] — 2026-04-12

### Added
- **Failure clustering** — groups historical failures by `(tool_name, failure_type)`, sorted by failure rate with natural-language descriptions and fix suggestions
- **Token optimization** — flags tools whose average output exceeds 5% of the context window; estimates token waste and cost savings per 1,000 calls
- **Quality scoring** — per-tool `ToolQualityScore` (reliability × 0.5 + schema stability × 0.3 + latency consistency × 0.2) and per-trace `AgentRunQualityScore` with A–F grades
- **Intelligence API** — `GET /intelligence/failures`, `GET /intelligence/optimization`, `GET /intelligence/quality/tools`, `GET /intelligence/quality/runs`
- Intelligence dashboard page
- Bundled static dashboard served by the collector — no Node.js required
- `anjor start` CLI command — starts collector + dashboard on `:7843`
- `GET /calls` — paginated raw event log

---

## [0.2.0] — 2026-04-11

### Added
- **LLM call tracing** — every `/v1/messages` call now produces an `LLMCallEvent` (model, token usage, context window, prompt hash, finish reason)
- **`ContextWindowTracker`** — per-trace context accumulation with configurable threshold alerts (70%/90%), growth rate in tokens/turn
- **`ContextHogDetector`** — per-tool running average output size; flags tools consuming >N% of the context window
- **`PromptDriftDetector`** — detects system prompt changes per agent using SHA-256 hashing
- **`GET /llm`** — aggregate LLM call summaries by model (call count, avg latency, avg tokens, avg utilisation)
- `LLMTokenUsage` with `cache_read` field for Anthropic prompt caching
- `ContextWindowTracker`, `ContextHogDetector`, `PromptDriftDetector` exported from top-level `anjor`

---

## [0.1.0] — 2026-04-10

Initial release.

### Added
- `anjor.patch()` — one-line httpx instrumentation; zero changes to agent code required
- **AnthropicParser** — extracts `tool_use` blocks from `/v1/messages` responses into `ToolCallEvent`
- **EventPipeline** — async queue with backpressure, concurrent handler dispatch, graceful shutdown
- **CollectorService** — local sidecar that receives events over HTTP and persists them to SQLite
- **SQLiteBackend** — WAL mode, batch writer, in-memory mode for tests
- **REST API** — `POST /events`, `GET /tools`, `GET /tools/{name}`, `GET /health`
- **DriftDetector** — structural fingerprinting (SHA-256, type-sensitive, value-agnostic) with field-level diff
- **FailureClassifier** — priority-ordered rule chain: Timeout → SchemaDrift → APIError → Unknown
- **AnjorConfig** — typed configuration via environment variables (`ANJOR_*`) and `.anjor.toml`
- Payload sanitisation — keys matching `*api_key*`, `*secret*`, `*password*`, `*token*`, `*auth*`, `*bearer*` are redacted before any storage

[Unreleased]: https://github.com/anjor-labs/anjor/compare/v0.6.0...HEAD
[0.6.0]: https://github.com/anjor-labs/anjor/releases/tag/v0.6.0
[0.5.0]: https://github.com/anjor-labs/anjor/releases/tag/v0.5.0
[0.4.0]: https://github.com/anjor-labs/anjor/releases/tag/v0.4.0
[0.3.0]: https://github.com/anjor-labs/anjor/releases/tag/v0.3.0
[0.2.0]: https://github.com/anjor-labs/anjor/releases/tag/v0.2.0
[0.1.0]: https://github.com/anjor-labs/anjor/releases/tag/v0.1.0
