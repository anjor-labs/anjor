# @anjor-labs/sdk

JavaScript/TypeScript SDK for the [Anjor](https://github.com/anjor-labs/anjor) observability platform. Lets AI agents running in Node.js post tool-call and LLM-call events to the Anjor collector with zero overhead on the agent critical path.

## Installation

```bash
npm install @anjor-labs/sdk
```

Requires Node 18+ (uses the built-in `fetch` and `crypto` APIs — no runtime dependencies).

## Prerequisites

The Anjor collector must be running locally before events will be stored:

```bash
anjor start --watch-transcripts
# collector now listening at http://localhost:7843
```

## Quick start

```typescript
import { anjor } from '@anjor-labs/sdk'

// Create a client — each instance gets its own session + trace IDs
const client = anjor({
  project: 'my-agent',
  agentId:  'worker-1',
})

// --- Tracing a tool call ---------------------------------------------------
// Wrap any async function. On success, a tool_call event is posted.
// On failure, a tool_call event with status: 'error' is posted, then the
// error is rethrown so your agent handles it normally.

const results = await client.traceTool(
  'web_search',                         // tool name shown in the dashboard
  () => mySearchFunction('query'),      // the actual call
  { inputPayload: { query: 'hello' } }  // optional — logged as input
)

// --- Tracing an LLM call ---------------------------------------------------
// Works with OpenAI and Anthropic response shapes out of the box.
// Token usage is extracted automatically and stored.

import Anthropic from '@anthropic-ai/sdk'
const anthropic = new Anthropic()

const message = await client.traceCall(
  'anthropic',                          // provider label shown in dashboard
  () =>
    anthropic.messages.create({
      model: 'claude-opus-4-5',
      max_tokens: 1024,
      messages: [{ role: 'user', content: 'Hello!' }],
    })
)

// Works the same way with OpenAI:
import OpenAI from 'openai'
const openai = new OpenAI()

const completion = await client.traceCall(
  'openai',
  () =>
    openai.chat.completions.create({
      model: 'gpt-4o',
      messages: [{ role: 'user', content: 'Hello!' }],
    })
)
```

## Configuration

| Option | Type | Default | Description |
|---|---|---|---|
| `collectorUrl` | `string` | `"http://localhost:7843"` | URL of the running Anjor collector |
| `project` | `string` | `""` | Tag all events with this project name (shows in dashboard project filter) |
| `agentId` | `string` | `"default"` | Identifier for this agent instance |

## Fire-and-forget guarantee

`@anjor-labs/sdk` **never throws into your agent code** as a result of observability work. If the collector is not running, if the network is unavailable, or if event serialisation fails, the error is silently swallowed. Your agent always gets back the result it expects from `traceTool` / `traceCall`.

This mirrors the `anjor.patch()` contract in the Python SDK.

## Token extraction

`traceCall` automatically detects the response shape and maps tokens to Anjor's fields:

| Provider | Input field | Output field | Cache read | Cache write |
|---|---|---|---|---|
| OpenAI | `usage.prompt_tokens` | `usage.completion_tokens` | — | — |
| Anthropic | `usage.input_tokens` | `usage.output_tokens` | `usage.cache_read_input_tokens` | `usage.cache_creation_input_tokens` |

## TypeScript

Full type definitions are included. The package is written in strict TypeScript and ships `.d.ts` files — no `@types/` package needed.

```typescript
import type { AnjorConfig, ToolCallEvent, LLMCallEvent } from '@anjor-labs/sdk'
```
