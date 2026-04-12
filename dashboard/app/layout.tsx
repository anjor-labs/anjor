import type { Metadata } from 'next'
import Link from 'next/link'
import './globals.css'

export const metadata: Metadata = {
  title: 'AgentScope',
  description: 'Observability for AI agents',
}

const NAV = [
  { href: '/',              label: 'Overview' },
  { href: '/tools',         label: 'Tools' },
  { href: '/calls',         label: 'Calls' },
  { href: '/alerts',        label: 'Alerts' },
  { href: '/llm',           label: 'LLM' },
  { href: '/intelligence',  label: 'Intelligence' },
]

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-950 text-gray-100 font-mono">
        <nav className="sticky top-0 z-10 border-b border-gray-800 bg-gray-950/90 backdrop-blur px-6 py-3 flex items-center gap-8">
          <span className="font-bold text-white tracking-tight">
            AgentScope
          </span>
          <div className="flex items-center gap-6">
            {NAV.map(({ href, label }) => (
              <Link
                key={href}
                href={href}
                className="text-sm text-gray-400 hover:text-white transition-colors"
              >
                {label}
              </Link>
            ))}
          </div>
          <span className="ml-auto text-xs text-gray-600">:7843</span>
        </nav>
        <main className="px-6 py-8 max-w-7xl mx-auto">{children}</main>
      </body>
    </html>
  )
}
