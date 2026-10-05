'use client'

import { Gauge } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Card, CardHeader, cn } from '@/components/ui'
import { api } from '@/lib/api'
import { clockTime, timeAgo } from '@/lib/workflow'

/**
 * How much of the Claude plan is used, and what this app has spent. The plan
 * figures are the ones Claude Code itself reported on the last call, so they
 * include everything else that account is used for, not only this app.
 */
interface Window {
  utilization: number | null
  resets_at: string | null
}
interface Usage {
  mode: string
  limits: {
    status: string | null
    windows: Record<string, Window>
    checked_at: string | null
  } | null
  today: { rows: number; tokens: number }
  last_7_days: { rows: number; tokens: number }
  by_stage_7_days: Record<string, number>
  tokens_per_row: number | null
}

const WINDOW_LABEL: Record<string, string> = { five_hour: '5-hour window', seven_day: 'Weekly window' }
const STAGE_LABEL: Record<string, string> = { '1': 'Gather facts', '2': 'Choose the angle', '3': 'Write the message', '4': 'Angle and message' }

function compact(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`
  if (n >= 1_000) return `${Math.round(n / 1_000)}k`
  return String(n)
}

export function UsagePanel() {
  const [usage, setUsage] = useState<Usage | null>(null)

  useEffect(() => {
    const load = () => api.get<Usage>('/settings/usage').then(setUsage).catch(() => null)
    load()
    const timer = setInterval(load, 30_000)
    return () => clearInterval(timer)
  }, [])

  if (!usage) return null
  const windows = Object.entries(usage.limits?.windows ?? {})
  if (!windows.length && !usage.last_7_days.rows) return null

  const stageTotal = Object.values(usage.by_stage_7_days).reduce((a, b) => a + b, 0)

  return (
    <Card className="mb-8">
      <CardHeader
        icon={Gauge}
        title="Claude usage"
        description={
          usage.limits?.checked_at
            ? `Plan limits as Claude reported them ${timeAgo(usage.limits.checked_at)}. They cover everything this Claude account is used for.`
            : 'Plan limits appear here after the next personalization run.'
        }
      />

      {windows.length > 0 && (
        <div className="grid gap-4 sm:grid-cols-2">
          {windows.map(([name, w]) => {
            const pct = Math.round((w.utilization ?? 0) * 100)
            return (
              <div key={name}>
                <div className="mb-1.5 flex items-baseline justify-between text-sm">
                  <span className="font-medium">{WINDOW_LABEL[name] ?? name.replace(/_/g, ' ')}</span>
                  <span className="tabular-nums text-muted-foreground">{pct}% used</span>
                </div>
                <div className="h-2 overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn('h-full rounded-full', pct >= 90 ? 'bg-danger' : pct >= 70 ? 'bg-warning' : 'bg-info')}
                    style={{ width: `${Math.min(pct, 100)}%` }}
                  />
                </div>
                <p className="mt-1 text-xs text-muted-foreground">Resets {clockTime(w.resets_at)}</p>
              </div>
            )
          })}
        </div>
      )}

      <dl className={cn('grid grid-cols-2 gap-4 text-sm sm:grid-cols-4', windows.length > 0 && 'mt-5 border-t border-border pt-5')}>
        <div>
          <dt className="text-xs text-muted-foreground">Today</dt>
          <dd className="font-medium tabular-nums">{compact(usage.today.tokens)} tokens</dd>
          <dd className="text-xs text-muted-foreground">{usage.today.rows} leads</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Last 7 days</dt>
          <dd className="font-medium tabular-nums">{compact(usage.last_7_days.tokens)} tokens</dd>
          <dd className="text-xs text-muted-foreground">{usage.last_7_days.rows} leads</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Per lead</dt>
          <dd className="font-medium tabular-nums">
            {usage.tokens_per_row ? `${compact(usage.tokens_per_row)} tokens` : '—'}
          </dd>
          <dd className="text-xs text-muted-foreground">7-day average</dd>
        </div>
        <div>
          <dt className="text-xs text-muted-foreground">Where they go</dt>
          {stageTotal > 0 ? (
            Object.entries(usage.by_stage_7_days)
              .sort(([a], [b]) => a.localeCompare(b))
              .map(([stage, tokens]) => (
                <dd key={stage} className="text-xs tabular-nums text-muted-foreground">
                  {STAGE_LABEL[stage] ?? `Stage ${stage}`}: {Math.round((tokens / stageTotal) * 100)}%
                </dd>
              ))
          ) : (
            <dd className="text-xs text-muted-foreground">Shown for new runs</dd>
          )}
        </div>
      </dl>
    </Card>
  )
}
