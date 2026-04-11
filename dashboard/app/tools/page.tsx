'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { api, fmt, type ToolListItem } from '@/lib/api'

export default function ToolsPage() {
  const [tools, setTools] = useState<ToolListItem[]>([])
  const [error, setError] = useState(false)
  const [lastUpdated, setLastUpdated] = useState('')

  async function load() {
    try {
      setTools(await api.tools())
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

  const sorted = [...tools].sort((a, b) => b.call_count - a.call_count)

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-bold text-white">Tool Explorer</h1>
        {lastUpdated && <p className="text-xs text-gray-600">Updated {lastUpdated}</p>}
      </div>

      {error && (
        <p className="text-red-400 text-sm">Cannot reach collector at :7843</p>
      )}

      {!error && sorted.length === 0 && (
        <p className="text-gray-600 text-sm">No tool calls recorded yet.</p>
      )}

      {sorted.length > 0 && (
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-gray-800">
              <th className="text-left text-xs text-gray-500 uppercase pb-3 pr-4">Tool Name</th>
              <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Calls</th>
              <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Success %</th>
              <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Avg Latency</th>
              <th className="text-right text-xs text-gray-500 uppercase pb-3">Detail</th>
            </tr>
          </thead>
          <tbody>
            {sorted.map((t) => (
              <tr key={t.tool_name} className="border-b border-gray-900 hover:bg-gray-900/50">
                <td className="py-3 pr-4 text-gray-200">{t.tool_name}</td>
                <td className="py-3 pr-4 text-right text-gray-300">{t.call_count.toLocaleString()}</td>
                <td className={`py-3 pr-4 text-right ${t.success_rate >= 0.9 ? 'text-green-400' : t.success_rate >= 0.7 ? 'text-yellow-400' : 'text-red-400'}`}>
                  {fmt.pct(t.success_rate)}
                </td>
                <td className="py-3 pr-4 text-right text-gray-300">{fmt.ms(t.avg_latency_ms)}</td>
                <td className="py-3 text-right">
                  <Link
                    href={`/tools/${encodeURIComponent(t.tool_name)}`}
                    className="text-xs text-blue-400 hover:text-blue-300"
                  >
                    detail →
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  )
}
