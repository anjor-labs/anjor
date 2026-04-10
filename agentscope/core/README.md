# agentscope/core

Domain core — pure business logic with zero framework dependencies.

## Modules

- **`events/`** — Immutable event models (BaseEvent, ToolCallEvent, LLMCallEvent, registry)
- **`pipeline/`** — Async event queue with handler dispatch and backpressure
- **`config.py`** — Typed configuration via Pydantic BaseSettings (env + TOML)

## Architecture fit

This is the innermost layer. Nothing in `core/` imports from `collector/`, `interceptors/`, or `analysis/`. All other layers depend on `core/`, never the reverse.
