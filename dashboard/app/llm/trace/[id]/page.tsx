'use client'

import { useParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { api, fmt, type LLMDetailItem } from '@/lib/api'

// ---------------------------------------------------------------------------
// Context growth SVG line chart (no external dependency)
// ---------------------------------------------------------------------------

function ContextGrowthChart({ turns }: { turns: LLMDetailItem[] }) {
  const data = turns.filter((t) => t.context_window_used != null && t.context_window_limit != null)
  if (data.length < 2) {
    return <p className="text-gray-600 text-sm">Need 2+ turns to render chart.</p>
  }

  const W = 600
  const H = 180
  const PAD = { top: 16, right: 56, bottom: 28, left: 52 }
  const innerW = W - PAD.left - PAD.right
  const innerH = H - PAD.top - PAD.bottom

  const limit = data[0].context_window_limit ?? 1
  const xStep = innerW / (data.length - 1)
  const yFor = (used: number) => PAD.top + innerH - (used / limit) * innerH

  const points = data.map((d, i) => ({
    x: PAD.left + i * xStep,
    y: yFor(d.context_window_used ?? 0),
    util: d.context_utilisation ?? 0,
    turn: i + 1,
  }))

  const linePath = points.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')

  const thresh70y = yFor(limit * 0.7)
  const thresh90y = yFor(limit * 0.9)

  return (
    <svg viewBox={`0 0 ${W} ${H}`} className="w-full h-44 text-xs">
      {/* y-axis labels */}
      {[0, 0.25, 0.5, 0.75, 1.0].map((pct) => {
        const y = yFor(limit * pct)
        return (
          <g key={pct}>
            <line x1={PAD.left} y1={y} x2={W - PAD.right} y2={y} stroke="#1f2937" strokeWidth={1} />
            <text x={PAD.left - 4} y={y + 4} textAnchor="end" fill="#6b7280" fontSize={9}>
              {(pct * 100).toFixed(0)}%
            </text>
          </g>
        )
      })}

      {/* threshold lines */}
      <line x1={PAD.left} y1={thresh70y} x2={W - PAD.right} y2={thresh70y}
        stroke="#fbbf24" strokeDasharray="4 3" strokeWidth={1} />
      <text x={W - PAD.right + 4} y={thresh70y + 4} fill="#fbbf24" fontSize={9}>70%</text>

      <line x1={PAD.left} y1={thresh90y} x2={W - PAD.right} y2={thresh90y}
        stroke="#f87171" strokeDasharray="4 3" strokeWidth={1} />
      <text x={W - PAD.right + 4} y={thresh90y + 4} fill="#f87171" fontSize={9}>90%</text>

      {/* data line */}
      <path d={linePath} fill="none" stroke="#60a5fa" strokeWidth={2} strokeLinejoin="round" />

      {/* dots + tooltips */}
      {points.map((p) => (
        <g key={p.turn}>
          <circle cx={p.x} cy={p.y} r={3.5} fill="#60a5fa" />
          <text x={p.x} y={H - 8} textAnchor="middle" fill="#6b7280" fontSize={9}>
            {p.turn}
          </text>
        </g>
      ))}

      {/* x-axis label */}
      <text x={PAD.left + innerW / 2} y={H - 2} textAnchor="middle" fill="#4b5563" fontSize={9}>
        Turn
      </text>
    </svg>
  )
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function LLMTracePage() {
  const { id } = useParams<{ id: string }>()
  const traceId = decodeURIComponent(id)

  const [turns, setTurns] = useState<LLMDetailItem[]>([])
  const [error, setError] = useState(false)
  const [lastUpdated, setLastUpdated] = useState('')

  async function load() {
    try {
      setTurns(await api.llmTrace(traceId))
      setError(false)
      setLastUpdated(new Date().toLocaleTimeString())
    } catch {
      setError(true)
    }
  }

  useEffect(() => {
    load()
    const id = setInterval(load, 5000)
    return () => clearInterval(id)
  }, [traceId])

  if (error) {
    return <p className="text-red-400 text-sm">Trace not found or collector unreachable.</p>
  }

  const totalTokensIn = turns.reduce((s, t) => s + (t.token_input ?? 0), 0)
  const totalTokensOut = turns.reduce((s, t) => s + (t.token_output ?? 0), 0)
  const maxUtil = turns.reduce((m, t) => Math.max(m, t.context_utilisation ?? 0), 0)
  const growthRates = turns
    .slice(1)
    .map((t, i) => (t.context_window_used ?? 0) - (turns[i].context_window_used ?? 0))
  const avgGrowth = growthRates.length
    ? growthRates.reduce((s, v) => s + v, 0) / growthRates.length
    : 0

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Trace Detail</h1>
          <code className="text-xs text-gray-500 font-mono">{traceId}</code>
        </div>
        {lastUpdated && <p className="text-xs text-gray-600">Updated {lastUpdated}</p>}
      </div>

      {turns.length > 0 && (
        <>
          {/* summary */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Turns', value: turns.length.toString() },
              { label: 'Total Tokens In', value: totalTokensIn.toLocaleString() },
              { label: 'Total Tokens Out', value: totalTokensOut.toLocaleString() },
              {
                label: 'Peak Context Util.',
                value: fmt.pct(maxUtil),
                warn: maxUtil > 0.9,
                caution: maxUtil > 0.7,
              },
            ].map(({ label, value, warn, caution }) => (
              <div key={label} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</p>
                <p className={`text-xl font-bold ${warn ? 'text-red-400' : caution ? 'text-yellow-400' : 'text-white'}`}>
                  {value}
                </p>
              </div>
            ))}
          </div>

          {/* context growth chart */}
          <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <div className="flex items-center justify-between mb-4">
              <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">
                Context Window Growth
              </h2>
              {avgGrowth > 0 && (
                <span className="text-xs text-gray-500">
                  avg +{avgGrowth.toFixed(0)} tokens/turn
                </span>
              )}
            </div>
            <ContextGrowthChart turns={turns} />
          </section>

          {/* turn-by-turn table */}
          <section>
            <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
              Turn-by-Turn
            </h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left text-xs text-gray-500 uppercase pb-3 pr-4">#</th>
                  <th className="text-left text-xs text-gray-500 uppercase pb-3 pr-4">Model</th>
                  <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Latency</th>
                  <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Tokens In</th>
                  <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Tokens Out</th>
                  <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Context Used</th>
                  <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Context Util.</th>
                  <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Finish</th>
                  <th className="text-right text-xs text-gray-500 uppercase pb-3">Time</th>
                </tr>
              </thead>
              <tbody>
                {turns.map((t, i) => (
                  <tr key={i} className="border-b border-gray-900 hover:bg-gray-900/50">
                    <td className="py-2 pr-4 text-gray-600 text-xs">{i + 1}</td>
                    <td className="py-2 pr-4 text-gray-400 font-mono text-xs truncate max-w-xs">
                      {t.model}
                    </td>
                    <td className="py-2 pr-4 text-right text-gray-300">{fmt.ms(t.latency_ms)}</td>
                    <td className="py-2 pr-4 text-right text-gray-300">{fmt.tokens(t.token_input)}</td>
                    <td className="py-2 pr-4 text-right text-gray-300">{fmt.tokens(t.token_output)}</td>
                    <td className="py-2 pr-4 text-right text-gray-300">{fmt.tokens(t.context_window_used)}</td>
                    <td className={`py-2 pr-4 text-right ${(t.context_utilisation ?? 0) > 0.9 ? 'text-red-400' : (t.context_utilisation ?? 0) > 0.7 ? 'text-yellow-400' : 'text-green-400'}`}>
                      {fmt.utilPct(t.context_utilisation)}
                    </td>
                    <td className="py-2 pr-4 text-right text-gray-500 text-xs">{t.finish_reason ?? '—'}</td>
                    <td className="py-2 text-right text-gray-600 text-xs">{fmt.ts(t.timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}

      {turns.length === 0 && !error && (
        <p className="text-gray-600 text-sm">No LLM calls found for this trace ID.</p>
      )}
    </div>
  )
}
