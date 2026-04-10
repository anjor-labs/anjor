# agentscope/interceptors/parsers

HTTP response parsers — translate API responses into domain events.

## Key abstractions

- **`BaseParser`** (ABC) — `can_parse(url)` + `parse(url, req_body, resp_body, latency_ms, status_code) → [BaseEvent]`.
- **`AnthropicParser`** — matches `api.anthropic.com/v1/messages`. Extracts `tool_use` blocks → `ToolCallEvent`. Sanitises sensitive keys. Handles both success and error responses.
- **`OpenAIParser`** — Phase 2 stub. Returns `[]`.
- **`ParserRegistry`** — first-match URL routing. Call `find_parser(url)` or `parse(...)` directly.

## Architecture fit

Parsers are the translation boundary between raw HTTP and typed domain events. They never write to storage or call the pipeline — they return lists of events that the caller (PatchInterceptor) enqueues.

## Extension

New provider: implement `BaseParser`, add to `build_default_registry()`.
