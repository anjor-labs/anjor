'use client'

import { useParams } from 'next/navigation'
import { useEffect, useState } from 'react'
import { api, fmt, type ToolDetail, type CallRecord } from '@/lib/api'

function LatencyBar({ value, max }: { value: number; max: number }) {
  const pct = max > 0 ? Math.min((value / max) * 100, 100) : 0
  return (
    <div className="flex items-center gap-3">
      <div className="flex-1 h-1.5 bg-gray-800 rounded-full overflow-hidden">
        <div className="h-full bg-blue-500 rounded-full" style={{ width: `${pct}%` }} />
      </div>
      <span className="text-gray-300 text-sm w-20 text-right">{fmt.ms(value)}</span>
    </div>
  )
}

export default function ToolDetailPage() {
  const { name } = useParams<{ name: string }>()
  const toolName = decodeURIComponent(name)

  const [detail, setDetail] = useState<ToolDetail | null>(null)
  const [calls, setCalls] = useState<CallRecord[]>([])
  const [error, setError] = useState(false)
  const [lastUpdated, setLastUpdated] = useState('')

  async function load() {
    try {
      const [d, c] = await Promise.all([
        api.tool(toolName),
        api.calls({ tool_name: toolName, limit: 20 }),
      ])
      setDetail(d)
      setCalls(c)
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
  }, [toolName])

  if (error) {
    return <p className="text-red-400 text-sm">Cannot reach collector or tool not found.</p>
  }

  const driftCalls = calls.filter((c) => c.drift_detected === 1)

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">{toolName}</h1>
        {lastUpdated && <p className="text-xs text-gray-600">Updated {lastUpdated}</p>}
      </div>

      {detail && (
        <>
          {/* summary cards */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
            {[
              { label: 'Total Calls', value: detail.call_count.toLocaleString() },
              { label: 'Success', value: detail.success_count.toLocaleString() },
              { label: 'Failures', value: detail.failure_count.toLocaleString() },
              { label: 'Success Rate', value: fmt.pct(detail.success_rate) },
            ].map(({ label, value }) => (
              <div key={label} className="bg-gray-900 border border-gray-800 rounded-lg p-4">
                <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</p>
                <p className="text-xl font-bold text-white">{value}</p>
              </div>
            ))}
          </div>

          {/* latency percentiles */}
          <section className="bg-gray-900 border border-gray-800 rounded-lg p-5">
            <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-4">Latency Percentiles</h2>
            <div className="space-y-3">
              {(['p50', 'p95', 'p99'] as const).map((p) => {
                const key = `${p}_latency_ms` as keyof ToolDetail
                return (
                  <div key={p} className="flex items-center gap-4">
                    <span className="text-xs text-gray-500 w-8">{p.toUpperCase()}</span>
                    <div className="flex-1">
                      <LatencyBar value={detail[key] as number} max={detail.p99_latency_ms} />
                    </div>
                  </div>
                )
              })}
              <div className="flex items-center gap-4 pt-2 border-t border-gray-800">
                <span className="text-xs text-gray-500 w-8">AVG</span>
                <div className="flex-1">
                  <LatencyBar value={detail.avg_latency_ms} max={detail.p99_latency_ms} />
                </div>
              </div>
            </div>
          </section>

          {/* schema drift history */}
          <section>
            <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">
              Schema Drift History
              {driftCalls.length > 0 && (
                <span className="ml-2 text-yellow-400 text-xs">({driftCalls.length} events)</span>
              )}
            </h2>
            {driftCalls.length === 0 ? (
              <p className="text-gray-600 text-sm">No drift detected in last 20 calls.</p>
            ) : (
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-gray-800">
                    <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Missing Fields</th>
                    <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Unexpected Fields</th>
                    <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Expected Hash</th>
                    <th className="text-right text-xs text-gray-500 uppercase pb-2">Time</th>
                  </tr>
                </thead>
                <tbody>
                  {driftCalls.map((c) => {
                    const missing = c.drift_missing ? (JSON.parse(c.drift_missing) as string[]) : []
                    const unexpected = c.drift_unexpected ? (JSON.parse(c.drift_unexpected) as string[]) : []
                    return (
                      <tr key={c.id} className="border-b border-gray-900">
                        <td className="py-2 pr-4 text-red-400 text-xs">{missing.join(', ') || '—'}</td>
                        <td className="py-2 pr-4 text-blue-400 text-xs">{unexpected.join(', ') || '—'}</td>
                        <td className="py-2 pr-4 text-gray-500 text-xs font-mono">
                          {c.drift_expected_hash?.slice(0, 8) ?? '—'}
                        </td>
                        <td className="py-2 text-right text-gray-500 text-xs">{fmt.ts(c.timestamp)}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            )}
          </section>

          {/* recent calls */}
          <section>
            <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider mb-3">Recent Calls</h2>
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-gray-800">
                  <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Status</th>
                  <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Failure</th>
                  <th className="text-right text-xs text-gray-500 uppercase pb-2 pr-4">Latency</th>
                  <th className="text-right text-xs text-gray-500 uppercase pb-2 pr-4">Tokens In/Out</th>
                  <th className="text-right text-xs text-gray-500 uppercase pb-2">Time</th>
                </tr>
              </thead>
              <tbody>
                {calls.map((c) => (
                  <tr key={c.id} className={`border-b border-gray-900 ${c.drift_detected ? 'bg-yellow-950/20' : ''}`}>
                    <td className={`py-2 pr-4 ${c.status === 'success' ? 'text-green-400' : 'text-red-400'}`}>
                      {c.status}
                    </td>
                    <td className="py-2 pr-4 text-gray-500 text-xs">{c.failure_type ?? '—'}</td>
                    <td className="py-2 pr-4 text-right text-gray-300">{fmt.ms(c.latency_ms)}</td>
                    <td className="py-2 pr-4 text-right text-gray-500 text-xs">
                      {fmt.tokens(c.token_usage_input)} / {fmt.tokens(c.token_usage_output)}
                    </td>
                    <td className="py-2 text-right text-gray-500 text-xs">{fmt.ts(c.timestamp)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </section>
        </>
      )}
    </div>
  )
}
