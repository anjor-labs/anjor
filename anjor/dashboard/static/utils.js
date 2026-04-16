// Shared utilities for the Anjor dashboard.
// Included by every page via <script src="utils.js"></script>.

const API = window.location.origin

const fmt = {
  pct:     (v) => v == null ? '—' : (v * 100).toFixed(1) + '%',
  ms:      (v) => v == null ? '—' : v >= 1000 ? (v / 1000).toFixed(2) + 's' : v.toFixed(0) + 'ms',
  tokens:  (v) => v == null ? '—' : v >= 1000 ? (v / 1000).toFixed(1) + 'k' : String(v),
  num:     (v) => v == null ? '—' : v >= 1_000_000 ? (v / 1_000_000).toFixed(2) + 'M' : v >= 1_000 ? (v / 1_000).toFixed(1) + 'k' : String(v),
  ts:      (v) => v == null ? '—' : new Date(v).toLocaleTimeString(),
  utilPct: (v) => v == null ? '—' : (v * 100).toFixed(1) + '%',
}

function successColor(rate) {
  return rate >= 0.9 ? 'text-green-400' : rate >= 0.7 ? 'text-yellow-400' : 'text-red-400'
}

function utilColor(u) {
  return u > 0.9 ? 'text-red-400' : u > 0.7 ? 'text-yellow-400' : 'text-green-400'
}

function gradeBadge(grade) {
  const cls = {
    A: 'bg-green-900 text-green-300 border-green-700',
    B: 'bg-blue-900 text-blue-300 border-blue-700',
    C: 'bg-yellow-900 text-yellow-300 border-yellow-700',
    D: 'bg-orange-900 text-orange-300 border-orange-700',
    F: 'bg-red-900 text-red-300 border-red-700',
  }[grade] || 'bg-gray-800 text-gray-300 border-gray-600'
  return `<span class="inline-flex items-center px-2 py-0.5 rounded border text-xs font-bold ${cls}">${grade}</span>`
}

function scoreBar(score, label) {
  const pct = Math.round(score * 100)
  const color = pct >= 90 ? 'bg-green-500' : pct >= 75 ? 'bg-blue-500' : pct >= 60 ? 'bg-yellow-500' : pct >= 40 ? 'bg-orange-500' : 'bg-red-500'
  return `<div class="flex items-center gap-2">
    <span class="text-xs text-gray-400 w-28 truncate shrink-0">${label}</span>
    <div class="flex-1 bg-gray-800 rounded-full h-1.5">
      <div class="${color} h-1.5 rounded-full" style="width:${pct}%"></div>
    </div>
    <span class="text-xs text-gray-300 w-8 text-right">${pct}%</span>
  </div>`
}

const NAV_LINKS = [
  ['/', 'Overview'],
  ['/ui/projects.html', 'Projects'],
  ['/ui/tools.html', 'Tools'],
  ['/ui/mcp.html', 'MCP'],
  ['/ui/calls.html', 'Calls'],
  ['/ui/alerts.html', 'Alerts'],
  ['/ui/llm.html', 'Usage'],
  ['/ui/intelligence.html', 'Intelligence'],
  ['/ui/traces.html', 'Traces'],
]

function spanKindIcon(kind) {
  return { root: '◆', orchestrator: '⬡', subagent: '○', tool: '▸' }[kind] || '·'
}

function durationBar(durationMs, maxMs) {
  if (!maxMs || maxMs <= 0) return ''
  const pct = Math.min(100, Math.round((durationMs / maxMs) * 100))
  const color = pct >= 90 ? 'bg-red-500' : pct >= 60 ? 'bg-yellow-500' : 'bg-blue-500'
  return `<div class="flex items-center gap-2">
    <div class="flex-1 bg-gray-800 rounded-full h-1.5">
      <div class="\${color} h-1.5 rounded-full" style="width:\${pct}%"></div>
    </div>
    <span class="text-xs text-gray-400 w-14 text-right">\${fmt.ms(durationMs)}</span>
  </div>`
}

function statusDot(status) {
  return status === 'error'
    ? '<span class="inline-block w-2 h-2 rounded-full bg-red-500 mr-1.5"></span>'
    : '<span class="inline-block w-2 h-2 rounded-full bg-green-500 mr-1.5"></span>'
}

function buildNav(current) {
  const links = NAV_LINKS.map(([href, label]) => {
    const active = window.location.pathname === href || (href === '/' && window.location.pathname === '/ui/index.html')
    return `<a href="${href}" class="text-sm ${active ? 'text-white' : 'text-gray-400 hover:text-white'} transition-colors">${label}</a>`
  }).join('')
  return `<nav class="sticky top-0 z-10 border-b border-gray-800 bg-gray-950/90 backdrop-blur px-6 py-3 flex items-center gap-8">
    <span class="font-bold text-white tracking-tight">Anjor</span>
    <div class="flex items-center gap-6">${links}</div>
    <span class="ml-auto text-xs text-gray-600">:${window.location.port || 80}</span>
  </nav>`
}

function statCard(label, value, sub) {
  return `<div class="bg-gray-900 border border-gray-800 rounded-lg p-5">
    <p class="text-xs text-gray-500 uppercase tracking-wider mb-1">${label}</p>
    <p class="text-2xl font-bold text-white">${value}</p>
    ${sub ? `<p class="text-xs text-gray-500 mt-1">${sub}</p>` : ''}
  </div>`
}

function errorBanner(msg) {
  return `<p class="text-red-400 text-sm">${msg}</p>`
}

function sourceBadge(source) {
  const labels = {
    '':            ['live',                 'bg-gray-800 text-gray-400 border border-gray-700'],
    'mcp':         ['MCP',                  'bg-purple-900/50 text-purple-300 border border-purple-800'],
    'claude_code': ['transcript · Claude',  'bg-blue-900/50 text-blue-300 border border-blue-800'],
    'gemini_cli':  ['transcript · Gemini',  'bg-teal-900/50 text-teal-300 border border-teal-800'],
    'openai_codex':['transcript · Codex',   'bg-green-900/50 text-green-300 border border-green-800'],
  }
  const [label, cls] = labels[source] || ['unknown', 'bg-gray-800 text-gray-400']
  return `<span class="inline-flex items-center px-2 py-0.5 rounded border text-xs font-mono ${cls}">${label}</span>`
}

function lastUpdatedBadge(t) {
  return t ? `<p class="text-xs text-gray-600">Updated ${t}</p>` : ''
}
