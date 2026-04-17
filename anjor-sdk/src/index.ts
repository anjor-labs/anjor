import { randomUUID } from 'crypto'
import type {
  AnjorConfig,
  AnjorEvent,
  AnthropicMessageResponse,
  OpenAICompletionResponse,
} from './types.js'

export type { AnjorConfig, AnjorEvent, AnthropicMessageResponse, OpenAICompletionResponse }

class AnjorClient {
  private readonly collectorUrl: string
  private readonly project: string
  private readonly agentId: string
  readonly sessionId: string
  readonly traceId: string

  constructor(config: AnjorConfig = {}) {
    this.collectorUrl = (config.collectorUrl ?? 'http://localhost:7843').replace(/\/$/, '')
    this.project = config.project ?? ''
    this.agentId = config.agentId ?? 'default'
    this.sessionId = randomUUID()
    this.traceId = randomUUID()
  }

  /** Wrap any async tool call and post a ToolCallEvent to the collector. */
  async traceTool<T>(
    toolName: string,
    fn: () => Promise<T>,
    opts: { inputPayload?: Record<string, unknown> } = {}
  ): Promise<T> {
    const start = Date.now()
    const timestamp = new Date().toISOString()
    let result: T
    let status: 'success' | 'error' = 'success'
    let failureType: string | undefined
    let outputPayload: Record<string, unknown> | undefined

    try {
      result = await fn()
      if (result !== null && typeof result === 'object') {
        outputPayload = result as Record<string, unknown>
      }
    } catch (err) {
      status = 'error'
      failureType = err instanceof Error ? err.constructor.name : 'UNKNOWN'
      this._postEvent({
        event_type: 'tool_call',
        tool_name: toolName,
        trace_id: this.traceId,
        session_id: this.sessionId,
        agent_id: this.agentId,
        project: this.project,
        timestamp,
        status,
        failure_type: failureType,
        latency_ms: Date.now() - start,
        input_payload: opts.inputPayload,
      })
      throw err
    }

    this._postEvent({
      event_type: 'tool_call',
      tool_name: toolName,
      trace_id: this.traceId,
      session_id: this.sessionId,
      agent_id: this.agentId,
      project: this.project,
      timestamp,
      status,
      latency_ms: Date.now() - start,
      input_payload: opts.inputPayload,
      output_payload: outputPayload,
    })

    return result!
  }

  /** Wrap an LLM API call and post an LLMCallEvent. Extracts token usage from OpenAI and Anthropic response shapes. */
  async traceCall<T extends OpenAICompletionResponse | AnthropicMessageResponse>(
    provider: string,
    fn: () => Promise<T>
  ): Promise<T> {
    const start = Date.now()
    const timestamp = new Date().toISOString()
    let response: T
    let status: 'success' | 'error' = 'success'
    let failureType: string | undefined

    try {
      response = await fn()
    } catch (err) {
      status = 'error'
      failureType = err instanceof Error ? err.constructor.name : 'UNKNOWN'
      this._postEvent({
        event_type: 'llm_call',
        tool_name: provider,
        trace_id: this.traceId,
        session_id: this.sessionId,
        agent_id: this.agentId,
        project: this.project,
        timestamp,
        model: provider,
        status,
        failure_type: failureType,
        latency_ms: Date.now() - start,
      })
      throw err
    }

    // Extract token usage — handle both OpenAI and Anthropic response shapes
    const usage = this._extractUsage(response)

    this._postEvent({
      event_type: 'llm_call',
      tool_name: provider,
      trace_id: this.traceId,
      session_id: this.sessionId,
      agent_id: this.agentId,
      project: this.project,
      timestamp,
      model: (response as AnthropicMessageResponse).model ?? provider,
      status,
      latency_ms: Date.now() - start,
      ...usage,
    })

    return response
  }

  private _extractUsage(response: OpenAICompletionResponse | AnthropicMessageResponse): {
    token_input?: number
    token_output?: number
    token_cache_read?: number
    token_cache_write?: number
  } {
    if (!response.usage) return {}
    const u = response.usage as Record<string, number | undefined>
    // OpenAI shape: prompt_tokens / completion_tokens
    if ('prompt_tokens' in u) {
      return {
        token_input: u.prompt_tokens,
        token_output: u.completion_tokens,
      }
    }
    // Anthropic shape: input_tokens / output_tokens / cache_*
    return {
      token_input: u.input_tokens,
      token_output: u.output_tokens,
      token_cache_read: u.cache_read_input_tokens,
      token_cache_write: u.cache_creation_input_tokens,
    }
  }

  /** Fire-and-forget event post. Never throws — swallows errors silently like anjor.patch(). */
  private _postEvent(event: AnjorEvent): void {
    const url = `${this.collectorUrl}/events`
    // Use globalThis.fetch if available (Node 18+), else fall back gracefully
    const fetchFn = typeof globalThis.fetch === 'function' ? globalThis.fetch : null
    if (!fetchFn) return

    fetchFn(url, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(event),
    }).catch(() => {
      // swallow — collector may not be running; never raise into agent code
    })
  }
}

/** Create a new Anjor client instance. Each instance tracks its own session and trace IDs. */
export function anjor(config: AnjorConfig = {}): AnjorClient {
  return new AnjorClient(config)
}
