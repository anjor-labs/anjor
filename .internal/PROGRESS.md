# Anjor — Build Progress

## Phase 1 — Tool Call Observability ✅ COMPLETE

| Step | Description | Status |
|------|-------------|--------|
| 1 | Core events (BaseEvent, ToolCallEvent, LLMCallEvent, EventTypeRegistry) | ✅ Done |
| 2 | Config (AnjorConfig, SanitiseConfig, env prefix ANJOR_) | ✅ Done |
| 3 | Event pipeline (asyncio.Queue, handlers, backpressure) | ✅ Done |
| 4 | Schema analysis (fingerprint, DriftDetector, FailureClassifier) | ✅ Done |
| 5 | Storage (StorageBackend ABC, SQLiteBackend, WAL, batch writer) | ✅ Done |
| 6 | Collector API (FastAPI, POST /events, GET /tools, GET /health) | ✅ Done |
| 7 | Parsers (AnthropicParser, ParserRegistry) | ✅ Done |
| 8 | Patch interceptor (httpx monkey-patch, install/uninstall) | ✅ Done |
| 9 | Integration + E2E tests | ✅ Done |
| 10 | Public API + README | ✅ Done |

## Phase 2 — LLM Call Tracing ✅ COMPLETE

| Step | Description | Status |
|------|-------------|--------|
| 11 | LLMCallEvent (model, token_usage, context_window, prompt_hash) | ✅ Done |
| 12 | LLM storage migration (002_llm_calls.sql) | ✅ Done |
| 13 | ContextWindowTracker + ContextHogDetector | ✅ Done |
| 14 | PromptDriftDetector | ✅ Done |
| 15 | GET /llm endpoint + LLM summary schemas | ✅ Done |
| 16 | GET /calls endpoint (paginated raw event log) | ✅ Done |
| 17 | AnthropicParser extended for LLM call events | ✅ Done |
| 18 | Integration tests for LLM flow | ✅ Done |

## Phase 3 — Intelligence Layer ✅ COMPLETE

| Step | Description | Status |
|------|-------------|--------|
| 19 | FailureClusterer (group by tool+type, rate, NL description, suggestion) | ✅ Done |
| 20 | TokenOptimizer + CostEstimator (5% context hog threshold) | ✅ Done |
| 21 | QualityScorer (ToolQualityScore + AgentRunQualityScore, A–F grades) | ✅ Done |
| 22 | Intelligence API routes (/intelligence/failures, /optimization, /quality/*) | ✅ Done |
| 23 | Dashboard intelligence page | ✅ Done |
| 24 | Unit + integration + property-based tests for intelligence layer | ✅ Done |

## Housekeeping ✅ COMPLETE

| Task | Status |
|------|--------|
| Package rename: agentscope → anjor | ✅ Done |
| Repo transfer to anjor-labs org | ✅ Done |
| GitHub URL updates throughout | ✅ Done |
| Internal files purged from public history | ✅ Done |
| .internal/ folder for private docs | ✅ Done |
| Fix patch(): wire CollectorHandler + start pipeline worker | ✅ Done |
| Fix EventPipeline.put(): thread-safe cross-thread enqueue | ✅ Done |
| Replace Next.js dashboard with bundled static HTML/JS | ✅ Done |
| Add `anjor start` CLI — no clone, no npm required | ✅ Done |

## Current State

- **Version**: 0.5.0
- **Tests**: 549 passing
- **Coverage**: 96.94%
- **Lint**: zero ruff errors
- **Types**: zero mypy errors (strict)
- **Repo**: https://github.com/anjor-labs/anjor

## Phase 5 — Multi-Provider Support ✅ COMPLETE

| Step | Description | Status |
|------|-------------|--------|
| 31 | OpenAIParser — `/v1/chat/completions` → LLMCallEvent + ToolCallEvents | ✅ Done |
| 32 | AnthropicParser model map expansion + Claude 4.x prefix fallback | ✅ Done |
| 34 | GeminiParser — `generateContent` → LLMCallEvent + ToolCallEvents | ✅ Done |
| 33 | Dashboard LLM provider breakdown + OpenAI demo data | ✅ Done |

## Phase 4 — Multi-Agent Tracing (✅ COMPLETE)

See `.internal/steps.md` for detailed step specs.

| Step | Description | Status |
|------|-------------|--------|
| 25 | AgentSpanEvent + W3C traceparent injection/extraction | ✅ Done |
| 26 | TraceGraph — DAG reconstruction, topological sort, cycle detection | ✅ Done |
| 27 | SpanStorage — spans table, write/query | ✅ Done |
| 28 | GET /traces/{trace_id}/graph endpoint | ✅ Done |
| 29 | Cross-agent token + failure attribution | ✅ Done |
| 30 | Dashboard trace visualiser (indented tree) | ✅ Done |
