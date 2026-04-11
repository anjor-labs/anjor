# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

---

## [Unreleased]

---

## [0.1.0] — 2026-04-10

Phase 1: Tool Call Observability — first complete release.

### Added

- `agentscope.patch()` — one-line httpx instrumentation; zero changes to agent code required
- `agentscope.configure()` — programmatic config override
- **AnthropicParser** — extracts `tool_use` blocks from Anthropic `/v1/messages` responses into `ToolCallEvent`
- **EventPipeline** — async queue with backpressure (drop-not-block), concurrent handler dispatch, graceful shutdown
- **CollectorService** — local sidecar that receives events over HTTP and persists them to SQLite
- **SQLiteBackend** — WAL mode, batch writer (flush every N events or M ms), in-memory mode for tests
- **REST API** — `POST /events`, `GET /tools`, `GET /tools/{name}`, `GET /health`
- **DriftDetector** — structural fingerprinting (SHA-256, type-sensitive, value-agnostic) with field-level diff
- **FailureClassifier** — priority-ordered rule chain: Timeout → SchemaDrift → APIError → Unknown
- **AgentScopeConfig** — Pydantic BaseSettings with env vars (`AGENTSCOPE_*`) and `.agentscope.toml` support
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

[Unreleased]: https://github.com/anji/agentscope/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/anji/agentscope/releases/tag/v0.1.0
