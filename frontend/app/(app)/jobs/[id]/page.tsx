'use client'

import { ArrowLeft, ArrowRight, ChevronDown, ChevronLeft, ChevronRight, Download, RotateCcw } from 'lucide-react'
import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

import {
  Alert,
  Badge,
  Button,
  CopyButton,
  Empty,
  LinkButton,
  PageHeader,
  Progress,
  Segmented,
  Spinner,
  Stat,
  StatusBadge,
  buttonClasses,
  cn,
  toast,
} from '@/components/ui'
import { api, exportUrl } from '@/lib/api'
import type { Job, ProspectRow } from '@/lib/types'
import { PHASE_LABEL, clockTime, duration, isActive, isLive, isWaiting, money, timeAgo } from '@/lib/workflow'

// The rows endpoint pages at 50 by default; without paging here, rows 51+ of
// a large sheet were simply invisible.
const PAGE_SIZE = 50

// What to do with a personalized row. Mirrors `outreach_of` in the backend.
const OUTREACH = {
  personalised: { label: 'Personalised', tone: 'success', title: 'A line was written for this lead. Ready to send.' },
  generic: { label: 'Generic message', tone: 'neutral', title: 'No personal line, but your approved copy is there. Fine to send.' },
  hold: { label: 'Hold: check first', tone: 'warning', title: 'Do not send until someone has read the reason.' },
} as const

function prospectName(row: ProspectRow) {
  return (
    row.identity.full_name ||
    [row.identity.first_name, row.identity.last_name].filter(Boolean).join(' ') ||
    row.identity.email ||
    row.identity.company ||
    `Row ${row.row_index + 1}`
  )
}

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [job, setJob] = useState<Job | null>(null)
  const [rows, setRows] = useState<ProspectRow[] | null>(null)
  const [filter, setFilter] = useState('')
  const [page, setPage] = useState(0)
  const [expanded, setExpanded] = useState<Set<string>>(new Set())
  const [sourceLabels, setSourceLabels] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const query = new URLSearchParams({ skip: String(page * PAGE_SIZE), limit: String(PAGE_SIZE) })
      if (filter) query.set('status_filter', filter)
      const [jobData, rowData] = await Promise.all([
        api.get<Job>(`/jobs/${id}`),
        api.get<ProspectRow[]>(`/jobs/${id}/rows?${query}`),
      ])
      setJob(jobData)
      setRows(rowData)
    } catch (err: any) {
      setError(err.message)
    }
  }, [id, filter, page])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    api
      .get<{ sources: { key: string; label: string }[] }>('/jobs/sources')
      .then((r) => setSourceLabels(Object.fromEntries(r.sources.map((s) => [s.key, s.label]))))
      .catch(() => null)
  }, [])

  const active = job ? isActive(job) : false
  const waiting = job ? isWaiting(job) : false
  // Keep polling while waiting too, so the page picks up the automatic restart.
  const live = job ? isLive(job) : false
  useEffect(() => {
    if (!live) return
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [live, refresh])

  async function retry(row: ProspectRow) {
    try {
      await api.post(`/jobs/${id}/rows/${row.id}/retry`)
      toast.success(`Row ${row.row_index + 1} queued again.`)
    } catch (err: any) {
      toast.error(err.message)
    }
    refresh()
  }

  async function act(action: 'cancel' | 'resume') {
    try {
      await api.post(`/jobs/${id}/${action}`)
      toast.success(action === 'cancel' ? 'Cancelled. Finished rows keep their results.' : 'Resumed.')
    } catch (err: any) {
      toast.error(err.message)
    }
    refresh()
  }

  function toggle(rowId: string) {
    setExpanded((prev) => {
      const next = new Set(prev)
      if (next.has(rowId)) next.delete(rowId)
      else next.add(rowId)
      return next
    })
  }

  if (error && !job) return <Alert title="Could not load this job">{error}</Alert>
  if (!job) return <Spinner />

  const isScrape = job.type === 'scrape'
  const statusOf = (row: ProspectRow) => (isScrape ? row.scrape_status : row.personalize_status)
  const errorOf = (row: ProspectRow) => (isScrape ? row.scrape_error : row.personalize_error)
  const processed = job.counts.done + job.counts.failed + job.counts.skipped
  const finished = job.status === 'done'

  return (
    <>
      <PageHeader
        eyebrow={
          <Link href={`/uploads/${job.upload_id}`} className="inline-flex items-center gap-1.5 hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> {job.upload_name ?? 'Upload'}
          </Link>
        }
        title={
          <span className="flex flex-wrap items-center gap-3">
            {PHASE_LABEL[job.type]}
            {job.options.channel && !isScrape && (
              <span className="text-lg font-normal capitalize text-muted-foreground">{job.options.channel}</span>
            )}
            <StatusBadge status={job.status} />
          </span>
        }
        description={`Started ${timeAgo(job.created_at)}${job.options.limit ? ` · first ${job.options.limit} rows` : ''}${job.options.force ? ' · redo' : ''}`}
        action={
          <>
            {live && (
              <Button variant="outline" onClick={() => act('cancel')}>
                Cancel
              </Button>
            )}
            {(job.status === 'blocked_auth' || job.status === 'cancelled' || waiting) && (
              <Button icon={RotateCcw} variant={waiting ? 'outline' : 'primary'} onClick={() => act('resume')}>
                {waiting ? 'Resume now' : 'Resume'}
              </Button>
            )}
          </>
        }
      />

      <div className="mb-6 grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-5">
        <Stat
          label="Progress"
          value={`${processed}/${job.counts.total}`}
          hint={<Progress done={job.counts.done + job.counts.skipped} failed={job.counts.failed} total={job.counts.total} showLabel={false} className="mt-1.5" />}
        />
        <Stat label="Done" value={job.counts.done} tone={job.counts.done ? 'success' : undefined} />
        <Stat label="Failed" value={job.counts.failed} tone={job.counts.failed ? 'danger' : undefined} />
        <Stat label="Skipped" value={job.counts.skipped} hint={isScrape ? 'Nothing to fetch' : undefined} />
        <Stat
          label={isScrape ? 'Time' : job.cost_usd || !job.tokens ? 'Cost' : 'Tokens'}
          value={
            isScrape
              ? (job.finished_at || active ? duration(job.started_at, job.finished_at) : null) ?? '—'
              : job.cost_usd
                ? money(job.cost_usd, 4)
                : job.tokens
                  ? `${Math.round(job.tokens / 1000)}k`
                  : '—'
          }
          hint={
            !isScrape
              ? [
                  !job.cost_usd && job.tokens ? 'on your Claude plan' : null,
                  job.finished_at ? `in ${duration(job.started_at, job.finished_at)}` : null,
                ]
                  .filter(Boolean)
                  .join(' · ') || undefined
              : undefined
          }
        />
      </div>

      {waiting && (
        <Alert tone="info" className="mb-6" title={`Waiting for a limit to reset, resumes ${clockTime(job.resume_at)}`}>
          {job.error} Nothing to do: the job restarts by itself and picks up only the rows that have not run. Finished
          rows kept their results.
        </Alert>
      )}

      {job.limit_events?.length > 0 && !waiting && (
        <p className="mb-6 text-xs text-muted-foreground">
          Paused for a limit {job.limit_events.length} time{job.limit_events.length === 1 ? '' : 's'}, last{' '}
          {timeAgo(job.limit_events[job.limit_events.length - 1].at)}, and carried on by itself.
        </p>
      )}

      {job.error && !waiting && (
        <Alert
          tone="warning"
          className="mb-6"
          title={job.status === 'blocked_auth' ? 'Paused' : 'Job error'}
          action={
            job.status === 'blocked_auth' && (
              <LinkButton href="/settings#claude" size="sm" variant="outline">
                Claude settings
              </LinkButton>
            )
          }
        >
          {job.error}
          {job.status === 'blocked_auth' && ' Finished rows kept their results, and Resume picks up only the rows that never ran.'}
        </Alert>
      )}

      {finished && (
        <Alert
          tone="success"
          className="mb-6"
          title={isScrape ? 'Research finished' : 'Messages written'}
          action={
            isScrape ? (
              <LinkButton href={`/uploads/${job.upload_id}?phase=personalize`} size="sm">
                Personalize <ArrowRight className="h-3.5 w-3.5" />
              </LinkButton>
            ) : (
              <a href={exportUrl(job.upload_id, 'personalized')} className={buttonClasses('primary', 'sm')}>
                <Download className="h-3.5 w-3.5" /> Download CSV
              </a>
            )
          }
        >
          {isScrape
            ? 'Spot-check a few rows below, then write messages from this research.'
            : 'Personalised rows have a line written for that lead. Generic rows carry your approved copy with no personal line, and are fine to send. Hold rows should not go out until someone has read the reason next to them.'}
        </Alert>
      )}

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Segmented
          label="Filter rows"
          size="sm"
          value={filter}
          onChange={(value) => {
            setFilter(value)
            setPage(0)
          }}
          options={[
            { value: '', label: 'All' },
            { value: 'done', label: isScrape ? 'Done' : 'Personalised' },
            ...(!isScrape
              ? [
                  { value: 'thin_context', label: 'Generic' },
                  { value: 'needs_review', label: 'Hold' },
                ]
              : []),
            { value: 'failed', label: 'Failed' },
            { value: 'skipped', label: 'Skipped' },
            { value: 'pending', label: 'Not run' },
          ]}
        />
        {!isScrape && rows && rows.some((r) => r.body) && (
          <Button
            size="sm"
            variant="ghost"
            icon={ChevronDown}
            onClick={() =>
              setExpanded((prev) => (prev.size ? new Set() : new Set(rows.filter((r) => r.body).map((r) => r.id))))
            }
          >
            {expanded.size ? 'Collapse all' : 'Expand all'}
          </Button>
        )}
      </div>

      {!rows && <Spinner />}
      {rows?.length === 0 && <Empty>No rows match this filter.</Empty>}

      {rows && rows.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th className="w-12">#</th>
                <th>Prospect</th>
                <th>{isScrape ? 'What was found' : 'Message'}</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const status = statusOf(row)
                const rowError = errorOf(row)
                const open = expanded.has(row.id)
                const busy = status === 'queued' || status === 'running'
                return (
                  <tr key={row.id}>
                    <td className="tabular-nums text-muted-foreground">{row.row_index + 1}</td>
                    <td className="min-w-40">
                      <div className="font-medium">{prospectName(row)}</div>
                      <div className="text-xs text-muted-foreground">
                        {[row.identity.title, row.identity.company].filter(Boolean).join(' · ')}
                      </div>
                    </td>

                    <td className="w-full max-w-xl">
                      {isScrape ? (
                        <div className="flex flex-wrap gap-1.5">
                          {Object.keys(row.sources).length === 0 && (
                            <span className="text-xs text-muted-foreground">Nothing fetched yet</span>
                          )}
                          {Object.entries(row.sources).map(([key, ok]) => (
                            <Badge key={key} tone={ok ? 'success' : 'danger'} dot title={ok ? 'Fetched' : 'Failed'}>
                              {sourceLabels[key] ?? key}
                            </Badge>
                          ))}
                        </div>
                      ) : row.body ? (
                        <div>
                          {row.subject && <div className="mb-1 text-sm font-medium">{row.subject}</div>}
                          <p className={cn('text-sm leading-relaxed text-foreground/90', open ? 'whitespace-pre-wrap' : 'line-clamp-2')}>
                            {row.body}
                          </p>
                          {open && row.angle && (
                            <div className="mt-3 space-y-1.5 rounded-lg border border-border bg-muted/50 p-3 text-xs">
                              <p>
                                <span className="font-medium text-muted-foreground">Angle </span>
                                {row.angle}
                              </p>
                              <p>
                                <span className="font-medium text-muted-foreground">Evidence </span>
                                {row.evidence}
                              </p>
                            </div>
                          )}
                          <div className="mt-1.5 flex flex-wrap items-center gap-1">
                            <button onClick={() => toggle(row.id)} className="link text-xs">
                              {open ? 'Show less' : 'Show full message & evidence'}
                            </button>
                            <span className="text-xs text-muted-foreground">· {row.body.length} chars</span>
                            {open && (
                              <CopyButton
                                text={row.subject ? `${row.subject}\n\n${row.body}` : row.body}
                                label="Copy message"
                              />
                            )}
                          </div>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>

                    <td>
                      {!isScrape && row.outreach ? (
                        <Badge tone={OUTREACH[row.outreach].tone} dot title={OUTREACH[row.outreach].title}>
                          {OUTREACH[row.outreach].label}
                        </Badge>
                      ) : (
                        <StatusBadge status={status} />
                      )}
                      {rowError && <div className="mt-1.5 max-w-64 text-xs text-muted-foreground">{rowError}</div>}
                    </td>

                    <td>
                      <Button
                        size="sm"
                        variant="ghost"
                        icon={RotateCcw}
                        onClick={() => retry(row)}
                        disabled={busy}
                        title={isScrape ? 'Research this row again' : 'Write this message again'}
                      >
                        {status === 'failed' ? 'Retry' : 'Redo'}
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}

      {rows && (page > 0 || rows.length === PAGE_SIZE) && (
        <div className="mt-4 flex items-center justify-between text-sm text-muted-foreground">
          <span>
            Rows {page * PAGE_SIZE + 1}–{page * PAGE_SIZE + rows.length}
          </span>
          <div className="flex gap-2">
            <Button size="sm" variant="outline" icon={ChevronLeft} disabled={page === 0} onClick={() => setPage(page - 1)}>
              Previous
            </Button>
            <Button size="sm" variant="outline" disabled={rows.length < PAGE_SIZE} onClick={() => setPage(page + 1)}>
              Next <ChevronRight className="h-4 w-4" />
            </Button>
          </div>
        </div>
      )}
    </>
  )
}
