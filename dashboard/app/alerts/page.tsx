'use client'

import { useEffect, useState } from 'react'
import { api, fmt, type CallRecord } from '@/lib/api'

export default function AlertsPage() {
  const [alerts, setAlerts] = useState<CallRecord[]>([])
  const [error, setError] = useState(false)
  const [lastUpdated, setLastUpdated] = useState('')

  async function load() {
    try {
      setAlerts(await api.calls({ drift_only: true, limit: 200 }))
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

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">Drift Alerts</h1>
          <p className="text-xs text-gray-500 mt-1">Tool calls where schema drift was detected</p>
        </div>
        {lastUpdated && <p className="text-xs text-gray-600">Updated {lastUpdated}</p>}
      </div>

      {error && <p className="text-red-400 text-sm">Cannot reach collector at :7843</p>}

      {!error && alerts.length === 0 && (
        <div className="flex flex-col items-center justify-center min-h-48 gap-3 text-center">
          <span className="text-3xl">✓</span>
          <p className="text-gray-400">No schema drift detected</p>
          <p className="text-gray-600 text-sm">Alerts appear here when a tool's input structure changes</p>
        </div>
      )}

      {alerts.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left text-xs text-gray-500 uppercase pb-3 pr-4">Tool</th>
              <th className="text-left text-xs text-gray-500 uppercase pb-3 pr-4">Missing Fields</th>
              <th className="text-left text-xs text-gray-500 uppercase pb-3 pr-4">Unexpected Fields</th>
              <th className="text-left text-xs text-gray-500 uppercase pb-3 pr-4">Expected Hash</th>
              <th className="text-left text-xs text-gray-500 uppercase pb-3 pr-4">Trace ID</th>
              <th className="text-right text-xs text-gray-500 uppercase pb-3">Time</th>
            </tr>
          </thead>
          <tbody>
            {alerts.map((c) => {
              const missing = c.drift_missing ? (JSON.parse(c.drift_missing) as string[]) : []
              const unexpected = c.drift_unexpected ? (JSON.parse(c.drift_unexpected) as string[]) : []
              return (
                <tr key={c.id} className="border-b border-gray-900 hover:bg-yellow-950/10">
                  <td className="py-3 pr-4">
                    <span className="text-yellow-400">{c.tool_name}</span>
                  </td>
                  <td className="py-3 pr-4">
                    {missing.length > 0 ? (
                      <div className="flex gap-1 flex-wrap">
                        {missing.map((f) => (
                          <span key={f} className="bg-red-950/50 text-red-400 text-xs px-1.5 py-0.5 rounded">
                            -{f}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="py-3 pr-4">
                    {unexpected.length > 0 ? (
                      <div className="flex gap-1 flex-wrap">
                        {unexpected.map((f) => (
                          <span key={f} className="bg-blue-950/50 text-blue-400 text-xs px-1.5 py-0.5 rounded">
                            +{f}
                          </span>
                        ))}
                      </div>
                    ) : (
                      <span className="text-gray-600">—</span>
                    )}
                  </td>
                  <td className="py-3 pr-4 font-mono text-gray-500 text-xs">
                    {c.drift_expected_hash?.slice(0, 8) ?? '—'}
                  </td>
                  <td className="py-3 pr-4 font-mono text-gray-600 text-xs">
                    {c.trace_id.slice(0, 8)}
                  </td>
                  <td className="py-3 text-right text-gray-500 text-xs">{fmt.ts(c.timestamp)}</td>
                </tr>
              )
            })}
          </tbody>
        </table>
      )}
    </div>
  )
}
