import { describe, it, before, after, beforeEach } from 'node:test'
import assert from 'node:assert/strict'
import { anjor } from '../index.js'
import type { AnjorEvent, ToolCallEvent, LLMCallEvent } from '../types.js'

// ---------------------------------------------------------------------------
// Fetch mock helpers
// ---------------------------------------------------------------------------

interface CapturedRequest {
  url: string
  method: string
  body: AnjorEvent
}

let capturedRequests: CapturedRequest[] = []
let fetchShouldThrow = false

function installMockFetch(): void {
  capturedRequests = []
  fetchShouldThrow = false
  globalThis.fetch = async (input: RequestInfo | URL, init?: RequestInit) => {
    if (fetchShouldThrow) {
      throw new Error('Network unreachable')
    }
    const url = typeof input === 'string' ? input : input.toString()
    const body = JSON.parse((init?.body as string) ?? '{}') as AnjorEvent
    capturedRequests.push({ url, method: init?.method ?? 'GET', body })
    return new Response(JSON.stringify({ ok: true }), { status: 200 })
  }
}

function lastRequest(): CapturedRequest {
  const req = capturedRequests[capturedRequests.length - 1]
  assert.ok(req, 'No fetch request was captured')
  return req
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe('@anjor/sdk', () => {
  before(installMockFetch)

  beforeEach(() => {
    capturedRequests = []
    fetchShouldThrow = false
  })

  // 1. traceTool posts a tool_call event with correct fields on success
  it('traceTool posts a tool_call event with correct fields on success', async () => {
    const client = anjor({ project: 'test-project', agentId: 'agent-1' })
    const inputPayload = { query: 'hello' }

    const result = await client.traceTool('search', async () => ({ hits: 42 }), { inputPayload })

    assert.deepEqual(result, { hits: 42 })
    assert.equal(capturedRequests.length, 1)

    const req = lastRequest()
    assert.equal(req.method, 'POST')
    assert.ok(req.url.endsWith('/events'))

    const event = req.body as ToolCallEvent
    assert.equal(event.event_type, 'tool_call')
    assert.equal(event.tool_name, 'search')
    assert.equal(event.project, 'test-project')
    assert.equal(event.agent_id, 'agent-1')
    assert.equal(event.status, 'success')
    assert.equal(event.session_id, client.sessionId)
    assert.equal(event.trace_id, client.traceId)
    assert.deepEqual(event.input_payload, inputPayload)
    assert.deepEqual(event.output_payload, { hits: 42 })
    assert.ok(typeof event.latency_ms === 'number' && event.latency_ms >= 0)
    assert.ok(event.timestamp.endsWith('Z'), 'timestamp should be ISO 8601 UTC')
  })

  // 2. traceTool posts status: 'error' and rethrows on exception
  it('traceTool posts status error and rethrows the exception', async () => {
    const client = anjor({ project: 'test-project' })

    await assert.rejects(
      () =>
        client.traceTool('failing-tool', async () => {
          throw new TypeError('Something went wrong')
        }),
      (err: unknown) => {
        assert.ok(err instanceof TypeError)
        assert.equal((err as TypeError).message, 'Something went wrong')
        return true
      }
    )

    assert.equal(capturedRequests.length, 1)
    const event = lastRequest().body as ToolCallEvent
    assert.equal(event.event_type, 'tool_call')
    assert.equal(event.tool_name, 'failing-tool')
    assert.equal(event.status, 'error')
    assert.equal(event.failure_type, 'TypeError')
    assert.ok(typeof event.latency_ms === 'number')
  })

  // 3. traceCall extracts OpenAI token usage (prompt_tokens / completion_tokens)
  it('traceCall extracts OpenAI token usage', async () => {
    const client = anjor({ project: 'openai-project' })
    const openAIResponse = {
      model: 'gpt-4o',
      usage: { prompt_tokens: 100, completion_tokens: 50 },
    }

    const result = await client.traceCall('openai', async () => openAIResponse)

    assert.deepEqual(result, openAIResponse)
    assert.equal(capturedRequests.length, 1)

    const event = lastRequest().body as LLMCallEvent
    assert.equal(event.event_type, 'llm_call')
    assert.equal(event.tool_name, 'openai')
    assert.equal(event.model, 'gpt-4o')
    assert.equal(event.status, 'success')
    assert.equal(event.token_input, 100)
    assert.equal(event.token_output, 50)
    assert.equal(event.token_cache_read, undefined)
    assert.equal(event.token_cache_write, undefined)
  })

  // 4. traceCall extracts Anthropic token usage (input_tokens / output_tokens / cache_*)
  it('traceCall extracts Anthropic token usage including cache fields', async () => {
    const client = anjor({ project: 'anthropic-project' })
    const anthropicResponse = {
      model: 'claude-opus-4-5',
      usage: {
        input_tokens: 200,
        output_tokens: 80,
        cache_read_input_tokens: 150,
        cache_creation_input_tokens: 50,
      },
    }

    const result = await client.traceCall('anthropic', async () => anthropicResponse)

    assert.deepEqual(result, anthropicResponse)
    assert.equal(capturedRequests.length, 1)

    const event = lastRequest().body as LLMCallEvent
    assert.equal(event.event_type, 'llm_call')
    assert.equal(event.model, 'claude-opus-4-5')
    assert.equal(event.status, 'success')
    assert.equal(event.token_input, 200)
    assert.equal(event.token_output, 80)
    assert.equal(event.token_cache_read, 150)
    assert.equal(event.token_cache_write, 50)
  })

  // 5. traceCall posts status: 'error' and rethrows on exception
  it('traceCall posts status error and rethrows the exception', async () => {
    const client = anjor({ project: 'test-project' })

    await assert.rejects(
      () =>
        client.traceCall('openai', async () => {
          throw new RangeError('Rate limit exceeded')
        }),
      (err: unknown) => {
        assert.ok(err instanceof RangeError)
        assert.equal((err as RangeError).message, 'Rate limit exceeded')
        return true
      }
    )

    assert.equal(capturedRequests.length, 1)
    const event = lastRequest().body as LLMCallEvent
    assert.equal(event.event_type, 'llm_call')
    assert.equal(event.status, 'error')
    assert.equal(event.failure_type, 'RangeError')
    assert.equal(event.tool_name, 'openai')
    assert.ok(typeof event.latency_ms === 'number')
  })

  // 6. Collector unavailable (fetch throws) — never propagates error to caller
  it('never propagates fetch errors into agent code when collector is unavailable', async () => {
    fetchShouldThrow = true
    const client = anjor({ project: 'test-project' })

    // traceTool should succeed and return the result even if fetch throws
    const result = await client.traceTool('safe-tool', async () => 'ok')
    assert.equal(result, 'ok')

    // traceCall should succeed even if fetch throws
    const llmResult = await client.traceCall('openai', async () => ({
      model: 'gpt-4o',
      usage: { prompt_tokens: 10, completion_tokens: 5 },
    }))
    assert.equal(llmResult.model, 'gpt-4o')

    // No requests were captured because fetch threw before we could capture them,
    // but crucially no error propagated to the caller.
    assert.equal(capturedRequests.length, 0)
  })

  // 7. Each anjor() call gets a unique sessionId and traceId
  it('each anjor() call gets a unique sessionId and traceId', () => {
    const client1 = anjor()
    const client2 = anjor()
    const client3 = anjor()

    // Session IDs are all unique
    assert.notEqual(client1.sessionId, client2.sessionId)
    assert.notEqual(client2.sessionId, client3.sessionId)
    assert.notEqual(client1.sessionId, client3.sessionId)

    // Trace IDs are all unique
    assert.notEqual(client1.traceId, client2.traceId)
    assert.notEqual(client2.traceId, client3.traceId)
    assert.notEqual(client1.traceId, client3.traceId)

    // Session ID and trace ID within a client are also different
    assert.notEqual(client1.sessionId, client1.traceId)

    // IDs look like UUIDs (36 chars, 4 hyphens)
    const uuidRe = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/
    assert.match(client1.sessionId, uuidRe)
    assert.match(client1.traceId, uuidRe)
  })

  // Bonus: default config values
  it('uses correct defaults when no config is provided', async () => {
    const client = anjor()

    await client.traceTool('noop', async () => null)

    const event = lastRequest().body as ToolCallEvent
    assert.equal(event.project, '')
    assert.equal(event.agent_id, 'default')
    assert.ok(lastRequest().url.startsWith('http://localhost:7843'))
  })

  // Bonus: trailing slash in collectorUrl is stripped
  it('strips trailing slash from collectorUrl', async () => {
    const client = anjor({ collectorUrl: 'http://localhost:9000/' })
    await client.traceTool('noop', async () => null)
    assert.ok(lastRequest().url.startsWith('http://localhost:9000/events'))
  })
})
