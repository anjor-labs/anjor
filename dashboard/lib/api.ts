export const COLLECTOR_URL =
  process.env.NEXT_PUBLIC_COLLECTOR_URL ?? 'http://localhost:7843'

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

export interface HealthData {
  status: string
  uptime_seconds: number
  queue_depth: number
  db_path: string
}

export interface ToolListItem {
  tool_name: string
  call_count: number
  success_rate: number
  avg_latency_ms: number
}

export interface ToolDetail {
  tool_name: string
  call_count: number
  success_count: number
  failure_count: number
  success_rate: number
  avg_latency_ms: number
  p50_latency_ms: number
  p95_latency_ms: number
  p99_latency_ms: number
}

export interface CallRecord {
  id: number
  tool_name: string
  status: string
  failure_type: string | null
  latency_ms: number
  token_usage_input: number | null
  token_usage_output: number | null
  input_payload: string   // JSON string
  output_payload: string  // JSON string
  input_schema_hash: string
  output_schema_hash: string
  drift_detected: number | null  // 0, 1, or null
  drift_missing: string | null   // JSON string: string[]
  drift_unexpected: string | null
  drift_expected_hash: string | null
  trace_id: string
  session_id: string
  timestamp: string
}

export interface LLMSummaryItem {
  model: string
  call_count: number
  avg_latency_ms: number
  avg_token_input: number
  avg_token_output: number
  avg_context_utilisation: number
}

// Phase 3 intelligence types
export interface FailureCluster {
  tool_name: string
  failure_type: string
  occurrence_count: number
  total_calls: number
  failure_rate: number
  avg_latency_ms: number
  pattern_description: string
  suggestion: string
  example_trace_ids: string[]
}

export interface OptimizationSuggestion {
  tool_name: string
  avg_output_tokens: number
  avg_context_fraction: number
  waste_score: number
  estimated_savings_tokens_per_call: number
  estimated_savings_usd_per_1k_calls: number
  suggestion_text: string
  sample_models: string[]
}

export interface ToolQualityScore {
  tool_name: string
  call_count: number
  reliability_score: number
  schema_stability_score: number
  latency_consistency_score: number
  overall_score: number
  grade: string
}

export interface AgentRunQualityScore {
  trace_id: string
  llm_call_count: number
  tool_call_count: number
  context_efficiency_score: number
  failure_recovery_score: number
  tool_diversity_score: number
  overall_score: number
  grade: string
}

export interface LLMDetailItem {
  trace_id: string
  session_id: string
  agent_id: string
  model: string
  latency_ms: number
  token_input: number | null
  token_output: number | null
  token_cache_read: number | null
  context_window_used: number | null
  context_window_limit: number | null
  context_utilisation: number | null
  prompt_hash: string | null
  system_prompt_hash: string | null
  messages_count: number | null
  finish_reason: string | null
  timestamp: string
}

// ---------------------------------------------------------------------------
// Fetch helper
// ---------------------------------------------------------------------------

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${COLLECTOR_URL}${path}`, {
    cache: 'no-store',
    signal: AbortSignal.timeout(5000),
  })
  if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// API surface
// ---------------------------------------------------------------------------

export interface CallsParams {
  tool_name?: string
  drift_only?: boolean
  limit?: number
  offset?: number
}

export const api = {
  health: () => get<HealthData>('/health'),
  tools: () => get<ToolListItem[]>('/tools'),
  tool: (name: string) => get<ToolDetail>(`/tools/${encodeURIComponent(name)}`),

  calls: (params: CallsParams = {}) => {
    const q = new URLSearchParams()
    if (params.tool_name) q.set('tool_name', params.tool_name)
    if (params.drift_only) q.set('drift_only', 'true')
    if (params.limit != null) q.set('limit', String(params.limit))
    if (params.offset != null) q.set('offset', String(params.offset))
    return get<CallRecord[]>(`/calls?${q.toString()}`)
  },

  llm: () => get<LLMSummaryItem[]>('/llm'),
  llmTrace: (traceId: string) =>
    get<LLMDetailItem[]>(`/llm/trace/${encodeURIComponent(traceId)}`),

  // Phase 3 intelligence endpoints
  intelligenceFailures: () => get<FailureCluster[]>('/intelligence/failures'),
  intelligenceOptimization: () => get<OptimizationSuggestion[]>('/intelligence/optimization'),
  intelligenceQualityTools: () => get<ToolQualityScore[]>('/intelligence/quality/tools'),
  intelligenceQualityRuns: () => get<AgentRunQualityScore[]>('/intelligence/quality/runs'),
}

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

export const fmt = {
  ms: (v: number) => `${v.toFixed(0)} ms`,
  pct: (v: number) => `${(v * 100).toFixed(1)}%`,
  utilPct: (v: number | null) => (v == null ? '—' : `${(v * 100).toFixed(1)}%`),
  tokens: (v: number | null) => (v == null ? '—' : v.toLocaleString()),
  shortHash: (h: string | null) => (h ? h.slice(0, 8) : '—'),
  ts: (iso: string) => {
    try {
      return new Date(iso).toLocaleTimeString()
    } catch {
      return iso
    }
  },
}
