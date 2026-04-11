'use client'

import { useEffect, useState } from 'react'
import { api, fmt, type CallRecord } from '@/lib/api'

function JsonBlock({ raw }: { raw: string }) {
  try {
    const parsed = JSON.parse(raw)
    if (Object.keys(parsed).length === 0) return <span className="text-gray-600">{'{}'}</span>
    return (
      <pre className="text-xs text-gray-400 overflow-x-auto whitespace-pre-wrap break-words max-w-xs">
        {JSON.stringify(parsed, null, 2)}
      </pre>
    )
  } catch {
    return <span className="text-gray-500 text-xs">{raw || '—'}</span>
  }
}

export default function CallsPage() {
  const [calls, setCalls] = useState<CallRecord[]>([])
  const [error, setError] = useState(false)
  const [page, setPage] = useState(0)
  const [toolFilter, setToolFilter] = useState('')
  const [lastUpdated, setLastUpdated] = useState('')
  const [expanded, setExpanded] = useState<number | null>(null)

  const PAGE_SIZE = 25

  async function load() {
    try {
      const data = await api.calls({
        tool_name: toolFilter || undefined,
        limit: PAGE_SIZE,
        offset: page * PAGE_SIZE,
      })
      setCalls(data)
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
  }, [page, toolFilter])

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <h1 className="text-xl font-bold text-white">Call Inspector</h1>
        <div className="flex items-center gap-3">
          <input
            type="text"
            placeholder="Filter by tool name…"
            value={toolFilter}
            onChange={(e) => { setToolFilter(e.target.value); setPage(0) }}
            className="bg-gray-900 border border-gray-700 rounded px-3 py-1.5 text-sm text-gray-200 placeholder-gray-600 focus:outline-none focus:border-blue-500 w-52"
          />
          {lastUpdated && <p className="text-xs text-gray-600">Updated {lastUpdated}</p>}
        </div>
      </div>

      {error && <p className="text-red-400 text-sm">Cannot reach collector at :7843</p>}

      {!error && calls.length === 0 && (
        <p className="text-gray-600 text-sm">No calls found.</p>
      )}

      {calls.length > 0 && (
        <div className="space-y-1">
          {/* header */}
          <div className="grid grid-cols-12 gap-2 text-xs text-gray-500 uppercase pb-2 border-b border-gray-800">
            <span className="col-span-3">Tool</span>
            <span className="col-span-2">Status</span>
            <span className="col-span-2 text-right">Latency</span>
            <span className="col-span-2 text-right">Tokens In/Out</span>
            <span className="col-span-2 text-right">Trace</span>
            <span className="col-span-1 text-right">Time</span>
          </div>

          {calls.map((c) => (
            <div key={c.id} className={`rounded ${c.drift_detected ? 'bg-yellow-950/20 border border-yellow-900/40' : 'hover:bg-gray-900/50'}`}>
              <button
                className="w-full grid grid-cols-12 gap-2 py-2 text-left text-sm items-center"
                onClick={() => setExpanded(expanded === c.id ? null : c.id)}
              >
                <span className="col-span-3 text-gray-200 truncate">{c.tool_name}</span>
                <span className={`col-span-2 ${c.status === 'success' ? 'text-green-400' : 'text-red-400'}`}>
                  {c.status}
                  {c.drift_detected ? <span className="ml-1 text-yellow-400 text-xs">drift</span> : null}
                </span>
                <span className="col-span-2 text-right text-gray-300">{fmt.ms(c.latency_ms)}</span>
                <span className="col-span-2 text-right text-gray-500 text-xs">
                  {fmt.tokens(c.token_usage_input)} / {fmt.tokens(c.token_usage_output)}
                </span>
                <span className="col-span-2 text-right text-gray-600 text-xs font-mono truncate">
                  {c.trace_id.slice(0, 8)}
                </span>
                <span className="col-span-1 text-right text-gray-600 text-xs">{fmt.ts(c.timestamp)}</span>
              </button>

              {expanded === c.id && (
                <div className="border-t border-gray-800 pt-3 pb-3 px-2 grid grid-cols-2 gap-4">
                  <div>
                    <p className="text-xs text-gray-500 uppercase mb-1">Input Payload</p>
                    <JsonBlock raw={c.input_payload} />
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 uppercase mb-1">Output Payload</p>
                    <JsonBlock raw={c.output_payload} />
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 uppercase mb-1">Input Schema Hash</p>
                    <code className="text-xs text-gray-400 font-mono">{c.input_schema_hash || '—'}</code>
                  </div>
                  <div>
                    <p className="text-xs text-gray-500 uppercase mb-1">Trace ID</p>
                    <code className="text-xs text-gray-400 font-mono">{c.trace_id}</code>
                  </div>
                  {c.drift_detected === 1 && (
                    <div className="col-span-2 bg-yellow-950/30 border border-yellow-900/40 rounded p-3">
                      <p className="text-xs text-yellow-400 font-semibold mb-2">Schema Drift Detected</p>
                      <div className="grid grid-cols-2 gap-4">
                        <div>
                          <p className="text-xs text-gray-500 mb-1">Missing fields</p>
                          <p className="text-xs text-red-400">
                            {c.drift_missing ? (JSON.parse(c.drift_missing) as string[]).join(', ') || '—' : '—'}
                          </p>
                        </div>
                        <div>
                          <p className="text-xs text-gray-500 mb-1">Unexpected fields</p>
                          <p className="text-xs text-blue-400">
                            {c.drift_unexpected ? (JSON.parse(c.drift_unexpected) as string[]).join(', ') || '—' : '—'}
                          </p>
                        </div>
                      </div>
                    </div>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* pagination */}
      <div className="flex items-center gap-3 pt-2">
        <button
          onClick={() => setPage((p) => Math.max(0, p - 1))}
          disabled={page === 0}
          className="text-xs text-gray-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
        >
          ← Prev
        </button>
        <span className="text-xs text-gray-600">Page {page + 1}</span>
        <button
          onClick={() => setPage((p) => p + 1)}
          disabled={calls.length < PAGE_SIZE}
          className="text-xs text-gray-400 hover:text-white disabled:opacity-30 disabled:cursor-not-allowed"
        >
          Next →
        </button>
      </div>
    </div>
  )
}
