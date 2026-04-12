'use client'

import { useEffect, useState } from 'react'
import {
  api,
  fmt,
  type FailureCluster,
  type OptimizationSuggestion,
  type ToolQualityScore,
  type AgentRunQualityScore,
} from '@/lib/api'

// ---------------------------------------------------------------------------
// Grade badge
// ---------------------------------------------------------------------------

function GradeBadge({ grade }: { grade: string }) {
  const colors: Record<string, string> = {
    A: 'bg-green-900 text-green-300 border-green-700',
    B: 'bg-blue-900 text-blue-300 border-blue-700',
    C: 'bg-yellow-900 text-yellow-300 border-yellow-700',
    D: 'bg-orange-900 text-orange-300 border-orange-700',
    F: 'bg-red-900 text-red-300 border-red-700',
  }
  const cls = colors[grade] ?? 'bg-gray-800 text-gray-300 border-gray-600'
  return (
    <span className={`inline-flex items-center px-2 py-0.5 rounded border text-xs font-bold ${cls}`}>
      {grade}
    </span>
  )
}

// ---------------------------------------------------------------------------
// Score bar
// ---------------------------------------------------------------------------

function ScoreBar({ score, label }: { score: number; label: string }) {
  const pct = Math.round(score * 100)
  const color = pct >= 90 ? 'bg-green-500' : pct >= 75 ? 'bg-blue-500' : pct >= 60 ? 'bg-yellow-500' : pct >= 40 ? 'bg-orange-500' : 'bg-red-500'
  return (
    <div className="flex items-center gap-2">
      <span className="text-xs text-gray-400 w-28 truncate shrink-0">{label}</span>
      <div className="flex-1 bg-gray-800 rounded-full h-1.5">
        <div className={`${color} h-1.5 rounded-full transition-all`} style={{ width: `${pct}%` }} />
      </div>
      <span className="text-xs text-gray-300 w-8 text-right">{pct}%</span>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Section header
// ---------------------------------------------------------------------------

function SectionHeader({ title, count, sub }: { title: string; count?: number; sub?: string }) {
  return (
    <div className="flex items-baseline gap-3 mb-4">
      <h2 className="text-lg font-semibold text-white">{title}</h2>
      {count != null && (
        <span className="text-sm text-gray-400">{count} found</span>
      )}
      {sub && <span className="text-xs text-gray-500">{sub}</span>}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Failure Patterns section
// ---------------------------------------------------------------------------

function FailurePatternsSection({ clusters }: { clusters: FailureCluster[] }) {
  if (clusters.length === 0) {
    return (
      <div className="text-sm text-gray-500 italic">
        No failure patterns detected — all tools passing.
      </div>
    )
  }
  return (
    <div className="space-y-3">
      {clusters.map((c) => (
        <div key={`${c.tool_name}-${c.failure_type}`}
          className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="flex items-start justify-between gap-3 mb-2">
            <div>
              <span className="font-mono text-sm text-white">{c.tool_name}</span>
              <span className="ml-2 text-xs px-1.5 py-0.5 rounded bg-red-900 text-red-300 border border-red-700 uppercase">
                {c.failure_type}
              </span>
            </div>
            <div className="text-right shrink-0">
              <span className="text-lg font-bold text-red-400">{fmt.pct(c.failure_rate)}</span>
              <p className="text-xs text-gray-500">{c.occurrence_count}/{c.total_calls} calls</p>
            </div>
          </div>
          <p className="text-xs text-gray-300 mb-2">{c.pattern_description}</p>
          <div className="bg-gray-800 rounded p-2 text-xs text-gray-400">
            <span className="text-yellow-400 font-medium">Suggestion: </span>{c.suggestion}
          </div>
          {c.example_trace_ids.length > 0 && (
            <p className="text-xs text-gray-600 mt-2">
              Example traces: {c.example_trace_ids.map(id => id.slice(0, 12)).join(', ')}
            </p>
          )}
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Optimization Suggestions section
// ---------------------------------------------------------------------------

function OptimizationSection({ suggestions }: { suggestions: OptimizationSuggestion[] }) {
  if (suggestions.length === 0) {
    return (
      <div className="text-sm text-gray-500 italic">
        No optimization opportunities found — all tool outputs are within context budget.
      </div>
    )
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 uppercase border-b border-gray-800">
            <th className="pb-2 pr-4">Tool</th>
            <th className="pb-2 pr-4">Avg output tokens</th>
            <th className="pb-2 pr-4">Context %</th>
            <th className="pb-2 pr-4">Waste score</th>
            <th className="pb-2 pr-4">Est. savings / 1k calls</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {suggestions.map((s) => (
            <tr key={s.tool_name} className="hover:bg-gray-900/50">
              <td className="py-3 pr-4 font-mono text-white">{s.tool_name}</td>
              <td className="py-3 pr-4 text-gray-300">{s.avg_output_tokens.toLocaleString()}</td>
              <td className="py-3 pr-4 text-orange-400">{fmt.pct(s.avg_context_fraction)}</td>
              <td className="py-3 pr-4">
                <div className="flex items-center gap-2">
                  <div className="w-16 bg-gray-800 rounded-full h-1.5">
                    <div
                      className="bg-orange-500 h-1.5 rounded-full"
                      style={{ width: `${Math.round(s.waste_score * 100)}%` }}
                    />
                  </div>
                  <span className="text-gray-400">{Math.round(s.waste_score * 100)}%</span>
                </div>
              </td>
              <td className="py-3 pr-4 text-green-400">${s.estimated_savings_usd_per_1k_calls.toFixed(4)}</td>
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-4 space-y-2">
        {suggestions.map((s) => (
          <div key={`${s.tool_name}-tip`} className="text-xs text-gray-400 bg-gray-900 rounded px-3 py-2">
            <span className="text-blue-400 font-medium">{s.tool_name}:</span>{' '}
            {s.suggestion_text}
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Tool Quality Scores section
// ---------------------------------------------------------------------------

function ToolQualitySection({ scores }: { scores: ToolQualityScore[] }) {
  if (scores.length === 0) {
    return <div className="text-sm text-gray-500 italic">No tool data yet.</div>
  }
  return (
    <div className="space-y-3">
      {scores.map((s) => (
        <div key={s.tool_name} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="font-mono text-sm text-white">{s.tool_name}</span>
              <GradeBadge grade={s.grade} />
            </div>
            <div className="text-right">
              <span className="text-lg font-bold text-white">
                {Math.round(s.overall_score * 100)}
              </span>
              <span className="text-xs text-gray-500">/100</span>
              <p className="text-xs text-gray-500">{s.call_count} calls</p>
            </div>
          </div>
          <div className="space-y-1.5">
            <ScoreBar score={s.reliability_score} label="Reliability" />
            <ScoreBar score={s.schema_stability_score} label="Schema stability" />
            <ScoreBar score={s.latency_consistency_score} label="Latency consistency" />
          </div>
        </div>
      ))}
    </div>
  )
}

// ---------------------------------------------------------------------------
// Run Quality Scores section
// ---------------------------------------------------------------------------

function RunQualitySection({ scores }: { scores: AgentRunQualityScore[] }) {
  if (scores.length === 0) {
    return <div className="text-sm text-gray-500 italic">No run data yet.</div>
  }
  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500 uppercase border-b border-gray-800">
            <th className="pb-2 pr-4">Trace ID</th>
            <th className="pb-2 pr-4">Grade</th>
            <th className="pb-2 pr-4">Score</th>
            <th className="pb-2 pr-4">Context eff.</th>
            <th className="pb-2 pr-4">Failure rec.</th>
            <th className="pb-2 pr-4">Tool div.</th>
            <th className="pb-2 pr-4">LLM calls</th>
            <th className="pb-2 pr-4">Tool calls</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-gray-800">
          {scores.map((s) => (
            <tr key={s.trace_id} className="hover:bg-gray-900/50">
              <td className="py-3 pr-4 font-mono text-xs text-gray-300">{s.trace_id.slice(0, 16)}…</td>
              <td className="py-3 pr-4"><GradeBadge grade={s.grade} /></td>
              <td className="py-3 pr-4 font-bold text-white">{Math.round(s.overall_score * 100)}</td>
              <td className="py-3 pr-4 text-gray-300">{fmt.pct(s.context_efficiency_score)}</td>
              <td className="py-3 pr-4 text-gray-300">{fmt.pct(s.failure_recovery_score)}</td>
              <td className="py-3 pr-4 text-gray-300">{fmt.pct(s.tool_diversity_score)}</td>
              <td className="py-3 pr-4 text-gray-400">{s.llm_call_count}</td>
              <td className="py-3 pr-4 text-gray-400">{s.tool_call_count}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

export default function IntelligencePage() {
  const [clusters, setClusters] = useState<FailureCluster[]>([])
  const [suggestions, setSuggestions] = useState<OptimizationSuggestion[]>([])
  const [toolScores, setToolScores] = useState<ToolQualityScore[]>([])
  const [runScores, setRunScores] = useState<AgentRunQualityScore[]>([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    const load = async () => {
      try {
        const [c, s, tq, rq] = await Promise.all([
          api.intelligenceFailures(),
          api.intelligenceOptimization(),
          api.intelligenceQualityTools(),
          api.intelligenceQualityRuns(),
        ])
        setClusters(c)
        setSuggestions(s)
        setToolScores(tq)
        setRunScores(rq)
      } catch (e) {
        setError(e instanceof Error ? e.message : 'Failed to load intelligence data')
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  return (
    <div className="space-y-12">
        <div>
          <h1 className="text-xl font-bold text-white">Intelligence</h1>
          <p className="text-sm text-gray-500 mt-1">
            Active recommendations derived from historical event data.
          </p>
        </div>

        {loading && (
          <div className="text-gray-400 text-sm">Loading intelligence data…</div>
        )}
        {error && (
          <div className="bg-red-950 border border-red-800 rounded-lg p-4 text-red-300 text-sm">
            {error} — is the collector running at localhost:7843?
          </div>
        )}

        {!loading && !error && (
          <>
            {/* Summary cards */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Failure patterns</p>
                <p className="text-2xl font-bold text-red-400">{clusters.length}</p>
              </div>
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Optimization opportunities</p>
                <p className="text-2xl font-bold text-orange-400">{suggestions.length}</p>
              </div>
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Tools scored</p>
                <p className="text-2xl font-bold text-blue-400">{toolScores.length}</p>
              </div>
              <div className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Runs scored</p>
                <p className="text-2xl font-bold text-purple-400">{runScores.length}</p>
              </div>
            </div>

            {/* Failure Patterns */}
            <section>
              <SectionHeader
                title="Failure Patterns"
                count={clusters.length}
                sub="Sorted by failure rate — worst first"
              />
              <FailurePatternsSection clusters={clusters} />
            </section>

            {/* Token Optimization */}
            <section>
              <SectionHeader
                title="Token Optimization"
                count={suggestions.length}
                sub="Tools whose outputs consume >5% of context window"
              />
              <OptimizationSection suggestions={suggestions} />
            </section>

            {/* Tool Quality Scores */}
            <section>
              <SectionHeader
                title="Tool Quality Scores"
                count={toolScores.length}
                sub="Sorted by overall score — lowest first"
              />
              <ToolQualitySection scores={toolScores} />
            </section>

            {/* Run Quality Scores */}
            <section>
              <SectionHeader
                title="Agent Run Quality"
                count={runScores.length}
                sub="Per trace_id — sorted by overall score ascending"
              />
              <RunQualitySection scores={runScores} />
            </section>
          </>
        )}
    </div>
  )
}
