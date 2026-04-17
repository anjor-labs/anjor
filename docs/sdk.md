# @anjor-labs/sdk — JavaScript / TypeScript SDK

A lightweight TypeScript package for instrumenting JavaScript/TypeScript AI agents. Posts events to the Anjor collector's existing `POST /events` endpoint — no new infrastructure needed.

## Install

```bash
npm install @anjor-labs/sdk
```

Requires Node 18+ (uses native `fetch`). Zero runtime dependencies.

## Quick start

```ts
import { anjor } from '@anjor-labs/sdk'

// One instance per agent process — carries sessionId and traceId
const a = anjor({
  collectorUrl: 'http://localhost:7843',   // default
  project: 'myapp',                        // optional
  agentId: 'my-agent',                     // optional, default: "default"
})

// Wrap any async tool call
const results = await a.traceTool('web_search', async () => {
  return await searchTool(query)
})

// Wrap LLM calls — extracts token usage from OpenAI and Anthropic responses
const response = await a.traceCall('openai', () =>
  openai.chat.completions.create({ model: 'gpt-4o', messages })
)

const message = await a.traceCall('anthropic', () =>
  anthropic.messages.create({ model: 'claude-opus-4-7', messages })
)
```

The collector must be running (`anjor start`) to receive events.

## API

### `anjor(config?)`

Creates a new client instance. Each instance has its own `sessionId` and `traceId` (UUIDs generated at construction time).

```ts
interface AnjorConfig {
  collectorUrl?: string   // default: "http://localhost:7843"
  project?: string        // tags all events; default: ""
  agentId?: string        // default: "default"
}
```

### `a.traceTool(name, fn, opts?)`

Wraps an async tool call. Posts a `tool_call` event on completion (success or failure).

```ts
const result = await a.traceTool('web_search', async () => {
  return await searchTool(query)
}, {
  inputPayload: { query }   // optional — stored in DB, truncated to 2000 chars
})
```

- On success: posts `status: "success"` with measured latency and output payload
- On failure: posts `status: "error"` with the error constructor name as `failure_type`, then rethrows

### `a.traceCall(provider, fn)`

Wraps an LLM API call. Extracts token usage from the response automatically.

```ts
const response = await a.traceCall('openai', () =>
  openai.chat.completions.create({ model: 'gpt-4o', messages })
)
```

**Token extraction:**

| SDK | Fields read |
|-----|------------|
| OpenAI | `response.usage.prompt_tokens` / `completion_tokens` |
| Anthropic | `response.usage.input_tokens` / `output_tokens` / `cache_read_input_tokens` / `cache_creation_input_tokens` |

Pass any other provider name — token fields will just be omitted if the response shape doesn't match.

## Fire-and-forget guarantee

`_postEvent` is always fire-and-forget. If the collector is unreachable or the post fails for any reason, the error is silently swallowed. Your agent code is never affected.

## Full TypeScript types

```ts
import type {
  AnjorConfig,
  ToolCallEvent,
  LLMCallEvent,
  AnjorEvent,
  OpenAICompletionResponse,
  AnthropicMessageResponse,
} from '@anjor-labs/sdk'
```
