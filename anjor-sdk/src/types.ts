export interface AnjorConfig {
  /** URL of the running Anjor collector, default: http://localhost:7843 */
  collectorUrl?: string
  /** Tag all events with this project name */
  project?: string
  /** Agent identifier, default: "default" */
  agentId?: string
}

export interface ToolCallEvent {
  event_type: 'tool_call'
  tool_name: string
  trace_id: string
  session_id: string
  agent_id: string
  project: string
  timestamp: string
  status: 'success' | 'error'
  failure_type?: string
  latency_ms: number
  input_payload?: Record<string, unknown>
  output_payload?: Record<string, unknown>
}

export interface LLMCallEvent {
  event_type: 'llm_call'
  tool_name: string
  trace_id: string
  session_id: string
  agent_id: string
  project: string
  timestamp: string
  model: string
  status: 'success' | 'error'
  failure_type?: string
  latency_ms: number
  token_input?: number
  token_output?: number
  token_cache_read?: number
  token_cache_write?: number
  context_window_used?: number
  context_window_limit?: number
}

export type AnjorEvent = ToolCallEvent | LLMCallEvent

/** Shape of OpenAI chat completion response (subset we care about) */
export interface OpenAICompletionResponse {
  model?: string
  usage?: {
    prompt_tokens?: number
    completion_tokens?: number
  }
}

/** Shape of Anthropic message response (subset we care about) */
export interface AnthropicMessageResponse {
  model?: string
  usage?: {
    input_tokens?: number
    output_tokens?: number
    cache_read_input_tokens?: number
    cache_creation_input_tokens?: number
  }
}
