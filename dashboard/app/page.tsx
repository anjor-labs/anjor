
'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { api, fmt, type HealthData, type ToolListItem, type CallRecord } from '@/lib/api'

function StatCard({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
      <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">{label}</p>
      <p className="text-2xl font-bold text-white">{value}</p>
      {sub && <p className="text-xs text-gray-500 mt-1">{sub}</p>}
    </div>
  )
}

function CollectorBanner({ health }: { health: HealthData | null; error: boolean }) {
  if (!health) return null
  return (
    <div className="flex items-center gap-3 bg-gray-900 border border-gray-800 rounded-lg px-4 py-2 text-sm">
      <span className="w-2 h-2 rounded-full bg-green-400 animate-pulse" />
      <span className="text-gray-300">
        Collector up {Math.floor(health.uptime_seconds)}s · queue {health.queue_depth} · {health.db_path}
      </span>
    </div>
  )
}

export default function OverviewPage() {
  const [health, setHealth] = useState<HealthData | null>(null)
  const [tools, setTools] = useState<ToolListItem[]>([])
  const [driftCalls, setDriftCalls] = useState<CallRecord[]>([])
  const [error, setError] = useState(false)
  const [lastUpdated, setLastUpdated] = useState<string>('')

  async function load() {
    try {
      const [h, t, d] = await Promise.all([
        api.health(),
        api.tools(),
        api.calls({ drift_only: true, limit: 5 }),
      ])
      setHealth(h)
      setTools(t)
      setDriftCalls(d)
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
  }, [])

  if (error) {
    return (
      <div className="flex flex-col items-center justify-center min-h-64 gap-4 text-center">
        <div className="w-3 h-3 rounded-full bg-red-500" />
        <p className="text-gray-300 text-lg">Collector not reachable</p>
        <p className="text-gray-500 text-sm">
          Start it with: <code className="bg-gray-900 px-2 py-1 rounded text-gray-200">python scripts/start_collector.py</code>
        </p>
      </div>
    )
  }

  const totalCalls = tools.reduce((s, t) => s + t.call_count, 0)
  const avgSuccessRate = tools.length
    ? tools.reduce((s, t) => s + t.success_rate * t.call_count, 0) / (totalCalls || 1)
    : 0
  const avgLatency = tools.length
    ? tools.reduce((s, t) => s + t.avg_latency_ms * t.call_count, 0) / (totalCalls || 1)
    : 0
  const slowestTools = [...tools].sort((a, b) => b.avg_latency_ms - a.avg_latency_ms).slice(0, 5)

  return (
    <div className="space-y-8">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Overview</h1>
          {lastUpdated && <p className="text-xs text-gray-600 mt-1">Updated {lastUpdated} · auto-refresh 5s</p>}
        </div>
        <CollectorBanner health={health} error={error} />
      </div>

      {/* stat cards */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        <StatCard label="Total Tool Calls" value={totalCalls.toLocaleString()} />
        <StatCard
          label="Success Rate"
          value={fmt.pct(avgSuccessRate)}
          sub={totalCalls === 0 ? 'no data' : undefined}
        />
        <StatCard label="Avg Latency" value={fmt.ms(avgLatency)} />
        <StatCard
          label="Active Drift Alerts"
          value={String(driftCalls.length)}
          sub={driftCalls.length > 0 ? 'last 5 shown' : 'none detected'}
        />
      </div>

      {/* slowest tools */}
      <section>
        <div className="flex items-center justify-between mb-3">
          <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Top Slowest Tools</h2>
          <Link href="/tools" className="text-xs text-blue-400 hover:text-blue-300">View all →</Link>
        </div>
        {slowestTools.length === 0 ? (
          <p className="text-gray-600 text-sm">No tool calls recorded yet.</p>
        ) : (
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Tool</th>
                <th className="text-right text-xs text-gray-500 uppercase pb-2 pr-4">Calls</th>
                <th className="text-right text-xs text-gray-500 uppercase pb-2 pr-4">Success</th>
                <th className="text-right text-xs text-gray-500 uppercase pb-2">Avg Latency</th>
              </tr>
            </thead>
            <tbody>
              {slowestTools.map((t) => (
                <tr key={t.tool_name} className="border-b border-gray-900 hover:bg-gray-900/50">
                  <td className="py-2 pr-4">
                    <Link href={`/tools/${encodeURIComponent(t.tool_name)}`} className="text-blue-400 hover:text-blue-300">
                      {t.tool_name}
                    </Link>
                  </td>
                  <td className="py-2 pr-4 text-right text-gray-300">{t.call_count}</td>
                  <td className={`py-2 pr-4 text-right ${t.success_rate >= 0.9 ? 'text-green-400' : t.success_rate >= 0.7 ? 'text-yellow-400' : 'text-red-400'}`}>
                    {fmt.pct(t.success_rate)}
                  </td>
                  <td className="py-2 text-right text-gray-300">{fmt.ms(t.avg_latency_ms)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </section>

      {/* recent drift events */}
      {driftCalls.length > 0 && (
        <section>
          <div className="flex items-center justify-between mb-3">
            <h2 className="text-sm font-semibold text-gray-300 uppercase tracking-wider">Recent Drift Events</h2>
            <Link href="/alerts" className="text-xs text-yellow-400 hover:text-yellow-300">View all →</Link>
          </div>
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Tool</th>
                <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Missing</th>
                <th className="text-left text-xs text-gray-500 uppercase pb-2 pr-4">Unexpected</th>
                <th className="text-right text-xs text-gray-500 uppercase pb-2">Time</th>
              </tr>
            </thead>
            <tbody>
              {driftCalls.map((c) => {
                const missing = c.drift_missing ? (JSON.parse(c.drift_missing) as string[]) : []
                const unexpected = c.drift_unexpected ? (JSON.parse(c.drift_unexpected) as string[]) : []
                return (
                  <tr key={c.id} className="border-b border-gray-900 hover:bg-gray-900/50">
                    <td className="py-2 pr-4 text-yellow-400">{c.tool_name}</td>
                    <td className="py-2 pr-4 text-red-400 text-xs">{missing.join(', ') || '—'}</td>
                    <td className="py-2 pr-4 text-blue-400 text-xs">{unexpected.join(', ') || '—'}</td>
                    <td className="py-2 text-right text-gray-500 text-xs">{fmt.ts(c.timestamp)}</td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </section>
      )}
    </div>
  )
}
