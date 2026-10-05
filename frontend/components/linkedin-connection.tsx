'use client'

import { ExternalLink, Linkedin, RefreshCw } from 'lucide-react'
import { useCallback, useEffect, useState } from 'react'

import { Alert, Badge, Button, toast } from '@/components/ui'
import { api } from '@/lib/api'
import { timeAgo } from '@/lib/workflow'

/**
 * Connects the LinkedIn account that the "Your LinkedIn account" provider
 * reads through. The sign-in itself happens in the LinkedIn service's own
 * browser window: this only asks for that window and shows its link, so the
 * password never passes through the app.
 */
interface LinkedInStatus {
  available: boolean
  service_running: boolean
  login_state: 'starting' | 'waiting' | 'signed-in' | 'failed' | null
  login_url: string | null
  signed_in: boolean | null
  checked_at: string | null
  reads_today: number
  daily_limit: number
  reads_per_hour: number
  pending: number
}

export function LinkedInConnection() {
  const [status, setStatus] = useState<LinkedInStatus | null>(null)
  const [busy, setBusy] = useState<'connect' | 'test' | 'clear' | null>(null)

  const refresh = useCallback(async () => {
    try {
      setStatus(await api.get<LinkedInStatus>('/settings/linkedin'))
    } catch {
      // Left as it was: the next poll or click tries again.
    }
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  // While a sign-in is in progress, follow it: the link takes a few seconds to
  // appear, and the service restarts by itself once the sign-in is saved.
  const signingIn = status?.login_state === 'starting' || status?.login_state === 'waiting'
  useEffect(() => {
    if (!signingIn) return
    const timer = setInterval(refresh, 2500)
    return () => clearInterval(timer)
  }, [signingIn, refresh])

  async function connect() {
    setBusy('connect')
    try {
      await api.post('/settings/linkedin/connect')
      await refresh()
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setBusy(null)
    }
  }

  async function test() {
    setBusy('test')
    try {
      const result = await api.post<{ account: string }>('/settings/linkedin/test')
      toast.success(`Connected as ${result.account}.`)
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setBusy(null)
      refresh()
    }
  }

  async function clearQueue() {
    setBusy('clear')
    try {
      const result = await api.post<{ cleared: number }>('/settings/linkedin/clear-queue')
      toast.success(`Stopped. ${result.cleared} lead${result.cleared === 1 ? '' : 's'} removed from the LinkedIn queue.`)
    } catch (err: any) {
      toast.error(err.message)
    } finally {
      setBusy(null)
      refresh()
    }
  }

  if (!status) return null

  const connected = status.login_state === 'signed-in' || status.signed_in === true
  const badge = !status.available || (!status.service_running && !signingIn)
    ? { tone: 'warning' as const, label: 'Service not running' }
    : signingIn
      ? { tone: 'info' as const, label: 'Signing in' }
      : connected
        ? { tone: 'success' as const, label: 'Connected' }
        : status.signed_in === false || status.login_state === 'failed'
          ? { tone: 'warning' as const, label: 'Not connected' }
          : { tone: 'neutral' as const, label: 'Not checked yet' }

  return (
    <div className="mt-5 rounded-lg border border-border p-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div className="flex items-center gap-2.5">
          <Linkedin className="h-4 w-4 text-muted-foreground" aria-hidden />
          <span className="text-sm font-medium">LinkedIn account</span>
          <Badge tone={badge.tone}>{badge.label}</Badge>
        </div>
        <span className="text-xs tabular-nums text-muted-foreground">
          {status.reads_today} of {status.daily_limit} reads used today
          {status.checked_at && ` · checked ${timeAgo(status.checked_at)}`}
        </span>
      </div>

      {!status.available || (!status.service_running && !signingIn) ? (
        <p className="hint">
          The LinkedIn service is not running on the engine. Start it on that machine with{' '}
          <code className="kbd">docker compose --profile linkedin up -d</code>, then come back here.
        </p>
      ) : (
        <>
          <p className="hint">
            Recent posts and profiles are read through this account, slowly and up to the daily limit, because
            LinkedIn restricts accounts that read too fast. Use an account you can afford to lose.
          </p>

          {status.login_state === 'starting' && (
            <Alert tone="info" className="mt-3">
              Opening the sign-in window. This takes about ten seconds.
            </Alert>
          )}
          {status.login_state === 'waiting' && status.login_url && (
            <Alert
              tone="info"
              className="mt-3"
              title="Sign in to LinkedIn in the window below"
              action={
                <a href={status.login_url} target="_blank" rel="noreferrer" className="link inline-flex items-center gap-1.5 text-sm">
                  Open the sign-in window <ExternalLink className="h-3.5 w-3.5" />
                </a>
              }
            >
              It opens only on the computer the engine runs on, and stays open for 30 minutes. Sign in there, approve
              the login in the LinkedIn app if asked, and this page updates by itself.
            </Alert>
          )}
          {status.login_state === 'failed' && (
            <Alert tone="warning" className="mt-3">
              The last sign-in was not completed. Connect again to get a fresh window.
            </Alert>
          )}

          <div className="mt-4 flex flex-wrap gap-2">
            <Button variant={connected ? 'outline' : 'primary'} onClick={connect} loading={busy === 'connect'} disabled={signingIn}>
              {connected ? 'Reconnect' : 'Connect LinkedIn'}
            </Button>
            <Button variant="secondary" icon={RefreshCw} onClick={test} loading={busy === 'test'} disabled={signingIn}>
              Test connection
            </Button>
          </div>
          <p className="hint">Testing reads your own profile once and counts as one of today&apos;s reads.</p>

          {status.pending > 0 && (
            <div className="mt-4 flex flex-wrap items-center justify-between gap-3 border-t border-border pt-4 text-sm">
              <span>
                <span className="font-medium tabular-nums">{status.pending}</span> lead{status.pending === 1 ? '' : 's'}{' '}
                waiting for a LinkedIn check, at {status.reads_per_hour} an hour. It runs in the background; research
                and personalization do not wait for it.
              </span>
              <Button size="sm" variant="ghost" onClick={clearQueue} loading={busy === 'clear'}>
                Stop and clear
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  )
}
