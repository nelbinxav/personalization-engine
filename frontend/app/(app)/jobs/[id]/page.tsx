'use client'

import Link from 'next/link'
import { useParams } from 'next/navigation'
import { useCallback, useEffect, useState } from 'react'

import {
  Alert,
  Badge,
  Button,
  Card,
  Empty,
  PageHeader,
  Progress,
  Select,
  Spinner,
  statusTone,
} from '@/components/ui'
import { api } from '@/lib/api'
import type { Job, ProspectRow } from '@/lib/types'

export default function JobDetailPage() {
  const { id } = useParams<{ id: string }>()
  const [job, setJob] = useState<Job | null>(null)
  const [rows, setRows] = useState<ProspectRow[] | null>(null)
  const [filter, setFilter] = useState('')
  const [expanded, setExpanded] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const refresh = useCallback(async () => {
    try {
      const [jobData, rowData] = await Promise.all([
        api.get<Job>(`/jobs/${id}`),
        api.get<ProspectRow[]>(`/jobs/${id}/rows${filter ? `?status_filter=${filter}` : ''}`),
      ])
      setJob(jobData)
      setRows(rowData)
    } catch (err: any) {
      setError(err.message)
    }
  }, [id, filter])

  useEffect(() => {
    refresh()
  }, [refresh])

  useEffect(() => {
    if (job?.status !== 'queued' && job?.status !== 'running') return
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [job?.status, refresh])

  async function retry(row: ProspectRow) {
    await api.post(`/jobs/${id}/rows/${row.id}/retry`).catch((err) => setError(err.message))
    refresh()
  }

  if (!job && !error) return <Spinner />

  const isScrape = job?.type === 'scrape'
  const statusOf = (row: ProspectRow) => (isScrape ? row.scrape_status : row.personalize_status)
  const errorOf = (row: ProspectRow) => (isScrape ? row.scrape_error : row.personalize_error)

  return (
    <>
      <PageHeader
        title={`${job?.type ?? 'Job'} · ${job?.upload_name ?? ''}`}
        description={job ? `Job ${job.id}` : undefined}
        action={
          <Link href="/jobs">
            <Button variant="secondary">All jobs</Button>
          </Link>
        }
      />

      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      {job && (
        <Card className="mb-6">
          <div className="flex flex-wrap items-center gap-6">
            <Badge tone={statusTone(job.status)}>{job.status.replace('_', ' ')}</Badge>
            <Progress
              value={job.counts.done + job.counts.failed + job.counts.skipped}
              total={job.counts.total}
            />
            <span className="text-sm text-muted-foreground">
              {job.counts.done} done · {job.counts.failed} failed · {job.counts.skipped} skipped
            </span>
            {job.cost_usd > 0 && (
              <span className="text-sm text-muted-foreground">${job.cost_usd.toFixed(4)}</span>
            )}
          </div>
          {job.error && (
            <div className="mt-4">
              <Alert tone="warning">{job.error}</Alert>
            </div>
          )}
        </Card>
      )}

      <div className="mb-4 flex items-center gap-3">
        <label className="text-sm text-muted-foreground">Filter</label>
        <Select className="w-52" value={filter} onChange={(e) => setFilter(e.target.value)}>
          <option value="">All rows</option>
          <option value="done">Done</option>
          <option value="failed">Failed</option>
          <option value="skipped">Skipped</option>
          {!isScrape && <option value="thin_context">Needs review (thin context)</option>}
        </Select>
      </div>

      {!rows && <Spinner />}
      {rows?.length === 0 && <Empty>No rows match this filter.</Empty>}

      {rows && rows.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>#</th>
                <th>Prospect</th>
                <th>{isScrape ? 'Sources' : 'Message'}</th>
                <th>Status</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const status = statusOf(row)
                const rowError = errorOf(row)
                const open = expanded === row.id
                return (
                  <tr key={row.id}>
                    <td className="tabular-nums text-muted-foreground">{row.row_index + 1}</td>
                    <td>
                      <div className="font-medium">
                        {row.identity.full_name ||
                          [row.identity.first_name, row.identity.last_name].filter(Boolean).join(' ') ||
                          row.identity.email ||
                          '—'}
                      </div>
                      <div className="text-xs text-muted-foreground">{row.identity.company}</div>
                    </td>

                    <td className="max-w-lg">
                      {isScrape ? (
                        <div className="flex flex-wrap gap-1">
                          {Object.keys(row.sources).length === 0 && (
                            <span className="text-xs text-muted-foreground">nothing fetched</span>
                          )}
                          {Object.entries(row.sources).map(([key, ok]) => (
                            <Badge key={key} tone={ok ? 'success' : 'danger'}>
                              {key}
                            </Badge>
                          ))}
                        </div>
                      ) : row.body ? (
                        <div>
                          {row.subject && <div className="text-xs font-medium">{row.subject}</div>}
                          <div className={open ? 'whitespace-pre-wrap text-sm' : 'truncate text-sm'}>
                            {row.body}
                          </div>
                          {open && row.angle && (
                            <div className="mt-2 rounded border border-border bg-muted p-2 text-xs">
                              <div>
                                <span className="text-muted-foreground">Angle: </span>
                                {row.angle}
                              </div>
                              <div className="mt-1">
                                <span className="text-muted-foreground">Evidence: </span>
                                {row.evidence}
                              </div>
                            </div>
                          )}
                          <button
                            onClick={() => setExpanded(open ? null : row.id)}
                            className="mt-1 text-xs text-primary underline"
                          >
                            {open ? 'collapse' : 'expand'}
                          </button>
                        </div>
                      ) : (
                        <span className="text-xs text-muted-foreground">—</span>
                      )}
                    </td>

                    <td>
                      <Badge tone={statusTone(status)}>{status.replace('_', ' ')}</Badge>
                      {rowError && (
                        <div className="mt-1 max-w-64 text-xs text-muted-foreground">{rowError}</div>
                      )}
                    </td>

                    <td>
                      <Button size="sm" variant="ghost" onClick={() => retry(row)}>
                        {isScrape ? 'Re-scrape' : 'Regenerate'}
                      </Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
