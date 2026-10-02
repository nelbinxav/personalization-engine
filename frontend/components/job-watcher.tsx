'use client'

import { Bell } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'

import { toast } from '@/components/ui'
import { api } from '@/lib/api'
import type { Job } from '@/lib/types'
import { clockTime, isLive } from '@/lib/workflow'

/**
 * Tells the operator when a job finishes or pauses, wherever they are in the
 * app, so a long run does not have to be watched.
 *
 * It lives in the app layout and compares each poll of /jobs with the last
 * status this browser saw for every job. A change worth knowing about raises
 * an in-app notice and, when the tab is in the background and the operator
 * allowed it, a browser notification. The last-seen statuses are kept in
 * localStorage, so a job that finished while the tab was closed is reported on
 * the next visit.
 */
const SEEN_KEY = 'pe.jobs.seen'
const FAST_POLL = 5_000
const IDLE_POLL = 30_000

type Seen = Record<string, { status: Job['status']; pauseNotified?: boolean }>
type Notice = { title: string; message: string; href: string; label: string }

function readSeen(): Seen | null {
  try {
    const raw = localStorage.getItem(SEEN_KEY)
    return raw ? (JSON.parse(raw) as Seen) : null
  } catch {
    return null
  }
}

function writeSeen(seen: Seen) {
  try {
    localStorage.setItem(SEEN_KEY, JSON.stringify(seen))
  } catch {}
}

function supported(): boolean {
  return typeof window !== 'undefined' && 'Notification' in window
}

/** Ask once, from a click: browsers ignore a request that is not user-initiated. */
export async function requestNotifications(): Promise<NotificationPermission | 'unsupported'> {
  if (!supported()) return 'unsupported'
  if (Notification.permission !== 'default') return Notification.permission
  try {
    return await Notification.requestPermission()
  } catch {
    return Notification.permission
  }
}

function noticeFor(job: Job, previous: Job['status'] | undefined, pauseNotified: boolean): Notice | null {
  const name = job.upload_name ?? 'Upload'
  const rows = `${job.counts.done + job.counts.skipped} of ${job.counts.total} rows`
  const failed = job.counts.failed ? `, ${job.counts.failed} failed` : ''
  // Only report a job this browser saw in flight (or never saw at all, which is
  // one started elsewhere). A job already seen as finished is old news.
  const wasLive = previous === undefined || previous === 'queued' || previous === 'running' || previous === 'rate_limited'

  if (job.status === 'done' && wasLive) {
    return job.type === 'scrape'
      ? {
          title: 'Research finished',
          message: `${name}: ${rows} researched${failed}. Next: write the messages.`,
          href: `/uploads/${job.upload_id}?phase=personalize`,
          label: 'Personalize',
        }
      : {
          title: 'Messages written',
          message: `${name}: ${rows} done${failed}.`,
          href: `/jobs/${job.id}`,
          label: 'Review them',
        }
  }
  if (job.status === 'failed' && wasLive) {
    return {
      title: job.type === 'scrape' ? 'Research failed' : 'Personalization failed',
      message: `${name}: every row failed. Open the job to see why.`,
      href: `/jobs/${job.id}`,
      label: 'Open the job',
    }
  }
  if (job.status === 'blocked_auth' && previous !== 'blocked_auth') {
    return {
      title: 'Job paused: Claude needs reconnecting',
      message: `${name}: ${job.error ?? 'Claude could not be reached.'}`,
      href: '/settings#claude',
      label: 'Claude settings',
    }
  }
  // Once per job: a long wait re-pauses on every probe, and that is not news.
  if (job.status === 'rate_limited' && !pauseNotified) {
    return {
      title: 'Job waiting for a limit to reset',
      message: `${name}: it restarts by itself ${clockTime(job.resume_at)}. Nothing to do.`,
      href: `/jobs/${job.id}`,
      label: 'Open the job',
    }
  }
  return null
}

export function JobWatcher() {
  const router = useRouter()
  const routerRef = useRef(router)
  routerRef.current = router

  useEffect(() => {
    let stopped = false
    let timer: ReturnType<typeof setTimeout> | undefined

    async function poll() {
      let delay = IDLE_POLL
      try {
        const jobs = await api.get<Job[]>('/jobs?limit=50')
        const before = readSeen()
        const seen: Seen = {}

        for (const job of jobs) {
          const last = before?.[job.id]
          const pauseNotified = !!last?.pauseNotified || job.status === 'rate_limited'
          seen[job.id] = { status: job.status, pauseNotified }

          // First visit from this browser: record what exists, announce nothing.
          if (!before || last?.status === job.status) continue
          const notice = noticeFor(job, last?.status, !!last?.pauseNotified)
          if (!notice) continue

          toast.notice(notice.title, notice.message, { href: notice.href, label: notice.label })
          if (supported() && Notification.permission === 'granted' && document.visibilityState !== 'visible') {
            try {
              const popup = new Notification(notice.title, { body: notice.message, tag: `pe-job-${job.id}` })
              popup.onclick = () => {
                window.focus()
                routerRef.current.push(notice.href)
                popup.close()
              }
            } catch {}
          }
        }

        writeSeen(seen)
        if (jobs.some(isLive)) delay = FAST_POLL
      } catch {
        // Signed out or offline: try again at the idle pace.
      }
      if (!stopped) timer = setTimeout(poll, delay)
    }

    poll()
    return () => {
      stopped = true
      if (timer) clearTimeout(timer)
    }
  }, [])

  return null
}

/** Sidebar prompt, shown only until the operator has answered the browser. */
export function NotificationPrompt() {
  const [permission, setPermission] = useState<NotificationPermission | 'unsupported'>('unsupported')

  useEffect(() => {
    if (supported()) setPermission(Notification.permission)
  }, [])

  if (permission !== 'default') return null

  return (
    <button
      onClick={async () => setPermission(await requestNotifications())}
      className="mb-3 flex w-full items-center gap-2.5 rounded-lg border border-dashed border-border px-3 py-2.5 text-left text-xs text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground"
    >
      <Bell className="h-4 w-4 shrink-0" aria-hidden />
      <span>
        <span className="block font-medium text-foreground">Notify me when jobs finish</span>
        Works while this tab is open, even in the background.
      </span>
    </button>
  )
}
