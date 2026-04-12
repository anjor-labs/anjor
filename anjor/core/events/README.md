# anjor/core/events

Immutable Pydantic event models. Zero framework dependencies.

## Key abstractions

- **`BaseEvent`** — frozen root model. All events share trace_id, session_id, timestamp, sequence_no.
- **`ToolCallEvent`** — primary observability event. Enforces `failure_type ↔ status` contract via model_validator.
- **`LLMCallEvent`** — emitted for every LLM provider call. Carries model, token usage, context window, prompt hash, finish reason.
- **`AgentSpanEvent`** — parent/child span for multi-agent trace linking. Compatible with W3C Trace Context.
- **`EventTypeRegistry`** — maps `EventType` strings → classes. Raises clearly on unknown type or duplicate.

## Architecture fit

Events are the data contract between every layer. Parsers produce them, the pipeline transports them, storage persists them. Keeping this module dependency-free means it can be imported anywhere without pulling in FastAPI or SQLite.

## Extension

Add a new event type: create a new file, register in `EventTypeRegistry`.
