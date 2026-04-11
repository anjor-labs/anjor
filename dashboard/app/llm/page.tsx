'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'
import { api, fmt, type LLMSummaryItem } from '@/lib/api'

export default function LLMPage() {
  const [summaries, setSummaries] = useState<LLMSummaryItem[]>([])
  const [error, setError] = useState(false)
  const [lastUpdated, setLastUpdated] = useState('')

  async function load() {
    try {
      setSummaries(await api.llm())
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

  const totalCalls = summaries.reduce((s, m) => s + m.call_count, 0)
  const avgUtil = summaries.length
    ? summaries.reduce((s, m) => s + m.avg_context_utilisation * m.call_count, 0) / (totalCalls || 1)
    : 0

  return (
    <div className="space-y-8">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-bold text-white">LLM Calls</h1>
          <p className="text-xs text-gray-500 mt-1">Aggregated stats per model</p>
        </div>
        {lastUpdated && <p className="text-xs text-gray-600">Updated {lastUpdated}</p>}
      </div>

      {error && <p className="text-red-400 text-sm">Cannot reach collector at :7843</p>}

      {!error && summaries.length === 0 && (
        <p className="text-gray-600 text-sm">No LLM calls recorded yet.</p>
      )}

      {summaries.length > 0 && (
        <>
          {/* summary stats */}
          <div className="grid grid-cols-2 md:grid-cols-3 gap-4">
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Total LLM Calls</p>
              <p className="text-2xl font-bold text-white">{totalCalls.toLocaleString()}</p>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Models Used</p>
              <p className="text-2xl font-bold text-white">{summaries.length}</p>
            </div>
            <div className="bg-gray-900 border border-gray-800 rounded-lg p-5">
              <p className="text-xs text-gray-500 uppercase tracking-wider mb-1">Avg Context Util.</p>
              <p className={`text-2xl font-bold ${avgUtil > 0.9 ? 'text-red-400' : avgUtil > 0.7 ? 'text-yellow-400' : 'text-white'}`}>
                {fmt.pct(avgUtil)}
              </p>
            </div>
          </div>

          {/* per-model table */}
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-gray-800">
                <th className="text-left text-xs text-gray-500 uppercase pb-3 pr-4">Model</th>
                <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Calls</th>
                <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Avg Latency</th>
                <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Avg Tokens In</th>
                <th className="text-right text-xs text-gray-500 uppercase pb-3 pr-4">Avg Tokens Out</th>
                <th className="text-right text-xs text-gray-500 uppercase pb-3">Avg Context Util.</th>
              </tr>
            </thead>
            <tbody>
              {summaries.map((m) => (
                <tr key={m.model} className="border-b border-gray-900 hover:bg-gray-900/50">
                  <td className="py-3 pr-4 text-gray-200 font-mono text-xs">{m.model}</td>
                  <td className="py-3 pr-4 text-right text-gray-300">{m.call_count.toLocaleString()}</td>
                  <td className="py-3 pr-4 text-right text-gray-300">{fmt.ms(m.avg_latency_ms)}</td>
                  <td className="py-3 pr-4 text-right text-gray-300">{m.avg_token_input.toFixed(0)}</td>
                  <td className="py-3 pr-4 text-right text-gray-300">{m.avg_token_output.toFixed(0)}</td>
                  <td className={`py-3 text-right ${m.avg_context_utilisation > 0.9 ? 'text-red-400' : m.avg_context_utilisation > 0.7 ? 'text-yellow-400' : 'text-green-400'}`}>
                    {fmt.pct(m.avg_context_utilisation)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>

          <p className="text-xs text-gray-600">
            To view per-trace context growth, use{' '}
            <code className="bg-gray-900 px-1.5 py-0.5 rounded">/llm/trace/&lt;trace_id&gt;</code>.
            Trace IDs appear in LLM calls when passed via{' '}
            <code className="bg-gray-900 px-1.5 py-0.5 rounded">metadata.trace_id</code>.
          </p>
        </>
      )}
    </div>
  )
}
