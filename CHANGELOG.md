# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.2.0] — 2026-04-12

Phase 2: Context & LLM Call Intelligence.

### Added

- **`LLMCallEvent`** — full domain model: model, token usage (input/output/cache_read), latency, context window used/limit, context utilisation (auto-computed), prompt hash, system prompt hash, messages count, finish reason
- **`AnthropicParser` extended** — now always emits an `LLMCallEvent` for every `/v1/messages` call, plus `ToolCallEvent`(s) for any tool_use blocks
- **`ContextWindowTracker`** — per-trace context accumulation with configurable threshold alerts (default 70%/90%), growth rate (tokens/turn), frozen `ContextSnapshot` records
- **`ContextHogDetector`** — per-tool running average output size, flags tools whose estimated token contribution exceeds a configurable fraction of the context window
- **`PromptDriftDetector`** — SHA-256 per `agent_id`, detects system prompt changes across calls, tracks calls-since-last-change
- **Storage migration 002** — `llm_calls` and `prompt_snapshots` tables in SQLite
- **`GET /llm`** — aggregate LLM call summaries by model (call count, avg latency, avg tokens, avg utilisation)
- **`GET /llm/trace/{trace_id}`** — all LLM calls for a specific trace
- **`ContextWindowTracker`, `ContextHogDetector`, `PromptDriftDetector`** exported from `anjor` top-level
- `LLMTokenUsage` with cache_read field for Anthropic prompt caching
- 284 tests, 97.65% coverage

### Changed

- `AnthropicParser.parse()` now returns `[LLMCallEvent, ...ToolCallEvents]` — at minimum one event per call
- `StorageBackend` ABC extended with `write_llm_event`, `query_llm_calls`, `list_llm_summaries`
- `write_event()` routes by `event_type` — tool_call events go to tool_calls table, llm_call events go to llm_calls table
- `__version__` bumped to 0.2.0

---

## [0.1.0] — 2026-04-10

Phase 1: Tool Call Observability — first complete release.

### Added

- `anjor.patch()` — one-line httpx instrumentation; zero changes to agent code required
- `anjor.configure()` — programmatic config override
- **AnthropicParser** — extracts `tool_use` blocks from Anthropic `/v1/messages` responses into `ToolCallEvent`
- **EventPipeline** — async queue with backpressure (drop-not-block), concurrent handler dispatch, graceful shutdown
- **CollectorService** — local sidecar that receives events over HTTP and persists them to SQLite
- **SQLiteBackend** — WAL mode, batch writer (flush every N events or M ms), in-memory mode for tests
- **REST API** — `POST /events`, `GET /tools`, `GET /tools/{name}`, `GET /health`
- **DriftDetector** — structural fingerprinting (SHA-256, type-sensitive, value-agnostic) with field-level diff
- **FailureClassifier** — priority-ordered rule chain: Timeout → SchemaDrift → APIError → Unknown
- **AnjorConfig** — Pydantic BaseSettings with env vars (`ANJOR_*`) and `.anjor.toml` support
- Payload sanitisation — sensitive keys redacted before any storage or logging
- 201 tests, 97.78% coverage (≥95% enforced)
- `scripts/dev_setup.sh` — one-command development environment
- `docs/architecture.md`, `docs/code_flow.md`, `docs/quickstart.md`

### Not in this release

- LLM call tracing (Phase 2)
- Context window intelligence (Phase 2)
- Optimisation suggestions (Phase 3)
- Multi-agent tracing (Phase 4)
- Dashboard UI (API-only)
- Cloud sync

[Unreleased]: https://github.com/anji/anjor/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/anji/anjor/releases/tag/v0.1.0
