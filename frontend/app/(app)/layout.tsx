'use client'

import {
  FileSpreadsheet,
  LayoutDashboard,
  LogOut,
  Menu,
  MessageSquareText,
  Moon,
  PlayCircle,
  Settings,
  Sparkles,
  Sun,
  X,
  type LucideIcon,
} from 'lucide-react'
import Link from 'next/link'
import { usePathname, useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { Spinner, Toaster, cn } from '@/components/ui'
import { api, ApiError } from '@/lib/api'
import type { AiStatus } from '@/lib/types'

const NAV: { title: string; items: { href: string; label: string; icon: LucideIcon }[] }[] = [
  {
    title: 'Workflow',
    items: [
      { href: '/overview', label: 'Overview', icon: LayoutDashboard },
      { href: '/uploads', label: 'Uploads', icon: FileSpreadsheet },
      { href: '/jobs', label: 'Jobs', icon: PlayCircle },
    ],
  },
  {
    title: 'Configure',
    items: [
      { href: '/prompts', label: 'Prompts', icon: Sparkles },
      { href: '/templates', label: 'Templates', icon: MessageSquareText },
      { href: '/settings', label: 'Settings', icon: Settings },
    ],
  },
]

function useTheme() {
  const [dark, setDark] = useState(true)
  useEffect(() => setDark(document.documentElement.classList.contains('dark')), [])
  function toggle() {
    const next = !dark
    document.documentElement.classList.toggle('dark', next)
    try {
      localStorage.setItem('theme', next ? 'dark' : 'light')
    } catch {}
    setDark(next)
  }
  return { dark, toggle }
}

export default function AppLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter()
  const pathname = usePathname()
  const [operator, setOperator] = useState<{ email: string } | null>(null)
  const [ai, setAi] = useState<AiStatus | null>(null)
  const [checking, setChecking] = useState(true)
  const [menuOpen, setMenuOpen] = useState(false)
  const theme = useTheme()

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

  // Re-check the credential on navigation: fixing it in Settings should clear
  // the red pill without a full reload.
  useEffect(() => {
    if (!operator) return
    setMenuOpen(false)
    api.get<AiStatus>('/settings/ai/status').then(setAi).catch(() => null)
  }, [pathname, operator])

  async function signOut() {
    await api.post('/auth/logout').catch(() => null)
    router.replace('/login')
  }

  if (checking) return <Spinner label="Checking session" className="min-h-screen" />
  if (!operator) return null

  const claudeTone = ai?.warning ? 'danger' : ai?.connected ? 'success' : 'warning'
  const claudeLabel = ai?.warning ? 'Misconfigured' : ai?.connected ? 'Connected' : 'Not connected'

  const sidebar = (
    <div className="flex h-full flex-col">
      <Link href="/overview" className="flex items-center gap-2.5 px-3 py-1">
        <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary text-primary-foreground shadow-sm shadow-primary/30">
          <Sparkles className="h-4 w-4" strokeWidth={2.5} />
        </span>
        <span className="text-sm font-semibold leading-tight">
          Personalization
          <span className="block text-xs font-normal text-muted-foreground">Engine</span>
        </span>
      </Link>

      <nav className="mt-8 flex-1 space-y-6">
        {NAV.map((group) => (
          <div key={group.title}>
            <p className="mb-1.5 px-3 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground/80">
              {group.title}
            </p>
            <ul className="space-y-0.5">
              {group.items.map((item) => {
                const active = pathname === item.href || pathname.startsWith(`${item.href}/`)
                return (
                  <li key={item.href}>
                    <Link
                      href={item.href}
                      aria-current={active ? 'page' : undefined}
                      className={cn(
                        'group flex items-center gap-2.5 rounded-md px-3 py-2 text-sm transition-colors',
                        active
                          ? 'bg-muted font-medium text-foreground ring-1 ring-inset ring-border'
                          : 'text-muted-foreground hover:bg-muted/60 hover:text-foreground',
                      )}
                    >
                      <item.icon
                        className={cn('h-4 w-4', active ? 'text-primary' : 'text-muted-foreground group-hover:text-foreground')}
                        aria-hidden
                      />
                      {item.label}
                    </Link>
                  </li>
                )
              })}
            </ul>
          </div>
        ))}
      </nav>

      {/* Claude connection state is visible on every page: a dead credential
          parks jobs, and that should never be a surprise. */}
      {ai && (
        <Link
          href="/settings#claude"
          title={ai.warning || ai.detail}
          className="mb-3 flex items-center gap-2.5 rounded-lg border border-border bg-card px-3 py-2.5 text-xs transition-colors hover:border-border-strong"
        >
          <span
            className={cn(
              'h-2 w-2 shrink-0 rounded-full',
              claudeTone === 'success' && 'bg-success',
              claudeTone === 'warning' && 'bg-warning',
              claudeTone === 'danger' && 'bg-danger',
            )}
          />
          <span className="min-w-0">
            <span className="block font-medium">Claude</span>
            <span className="block truncate text-muted-foreground">{claudeLabel}</span>
          </span>
        </Link>
      )}

      <div className="flex items-center gap-1 border-t border-border pt-3">
        <span className="min-w-0 flex-1 truncate px-3 text-xs text-muted-foreground" title={operator.email}>
          {operator.email}
        </span>
        <button
          onClick={theme.toggle}
          className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label={theme.dark ? 'Switch to light theme' : 'Switch to dark theme'}
          title={theme.dark ? 'Light theme' : 'Dark theme'}
        >
          {theme.dark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
        </button>
        <button
          onClick={signOut}
          className="rounded-md p-2 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
          aria-label="Sign out"
          title="Sign out"
        >
          <LogOut className="h-4 w-4" />
        </button>
      </div>
    </div>
  )

  return (
    <div className="min-h-screen lg:pl-60">
      <aside className="fixed inset-y-0 left-0 z-30 hidden w-60 border-r border-border bg-card/40 px-3 py-5 lg:block">
        {sidebar}
      </aside>

      {/* Mobile: top bar + drawer */}
      <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-border bg-background/85 px-4 py-3 backdrop-blur lg:hidden">
        <button
          onClick={() => setMenuOpen(true)}
          className="rounded-md p-1.5 text-muted-foreground hover:bg-muted hover:text-foreground"
          aria-label="Open menu"
        >
          <Menu className="h-5 w-5" />
        </button>
        <span className="text-sm font-semibold">Personalization Engine</span>
        {ai && (
          <span
            className={cn(
              'ml-auto h-2 w-2 rounded-full',
              claudeTone === 'success' && 'bg-success',
              claudeTone === 'warning' && 'bg-warning',
              claudeTone === 'danger' && 'bg-danger',
            )}
            title={`Claude: ${claudeLabel}`}
          />
        )}
      </header>
      {menuOpen && (
        <div className="fixed inset-0 z-40 lg:hidden">
          <div className="absolute inset-0 bg-black/50 animate-in fade-in" onClick={() => setMenuOpen(false)} />
          <aside className="absolute inset-y-0 left-0 w-64 border-r border-border bg-background px-3 py-5 shadow-pop animate-in slide-in-from-left">
            <button
              onClick={() => setMenuOpen(false)}
              className="absolute right-3 top-4 rounded-md p-1.5 text-muted-foreground hover:bg-muted"
              aria-label="Close menu"
            >
              <X className="h-4 w-4" />
            </button>
            {sidebar}
          </aside>
        </div>
      )}

      <main className="mx-auto max-w-6xl px-4 py-8 sm:px-8 lg:py-10">{children}</main>
      <Toaster />
    </div>
  )
}
