'use client'

import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { Badge, Spinner, cn } from '@/components/ui'
import { api, ApiError } from '@/lib/api'
import type { AiStatus } from '@/lib/types'

const NAV = [
  { href: '/uploads', label: 'Uploads' },
  { href: '/jobs', label: 'Jobs' },
  { href: '/prompts', label: 'Prompts' },
  { href: '/templates', label: 'Templates' },
  { href: '/settings', label: 'Settings' },
]

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [operator, setOperator] = useState<{ email: string } | null>(null)
  const [ai, setAi] = useState<AiStatus | null>(null)
  const [checking, setChecking] = useState(true)

  useEffect(() => {
    // Client-side guard rather than middleware: in production the API lives on
    // a different host, so the session cookie is not visible to the Next server.
    api
      .get<{ email: string }>('/auth/me')
      .then((me) => {
        setOperator(me)
        return api.get<AiStatus>('/settings/ai/status').then(setAi).catch(() => null)
      })
      .catch((err) => {
        if (err instanceof ApiError && err.status === 401) router.replace('/login')
      })
      .finally(() => setChecking(false))
  }, [router])

  async function signOut() {
    await api.post('/auth/logout').catch(() => null)
    router.replace('/login')
  }

  if (checking) return <Spinner label="Checking session" />
  if (!operator) return null

  return (
    <div className="min-h-screen">
      <header className="sticky top-0 z-10 border-b border-border bg-background/95 backdrop-blur">
        <div className="mx-auto flex max-w-7xl flex-wrap items-center gap-x-6 gap-y-3 px-6 py-3">
          <span className="text-sm font-semibold">Personalization Engine</span>

          <nav className="flex flex-wrap items-center gap-1">
            {NAV.map((item) => {
              const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={cn(
                    'rounded-md px-3 py-1.5 text-sm transition-colors',
                    active
                      ? 'bg-muted font-medium text-foreground'
                      : 'text-muted-foreground hover:text-foreground',
                  )}
                >
                  {item.label}
                </Link>
              )
            })}
          </nav>

          <div className="ml-auto flex items-center gap-3">
            {/* Claude connection state is visible on every page: a dead
                credential parks jobs, and that should never be a surprise. */}
            {ai && (
              <Link href="/settings" title={ai.warning || ai.detail}>
                <Badge tone={ai.warning ? 'danger' : ai.connected ? 'success' : 'warning'}>
                  Claude: {ai.warning ? 'misconfigured' : ai.connected ? 'connected' : 'not connected'}
                </Badge>
              </Link>
            )}
            <span className="hidden text-xs text-muted-foreground sm:inline">{operator.email}</span>
            <button onClick={signOut} className="text-xs text-muted-foreground hover:text-foreground">
              Sign out
            </button>
          </div>
        </div>
      </header>

      <main className="mx-auto max-w-7xl px-6 py-8">{children}</main>
    </div>
  )
}
