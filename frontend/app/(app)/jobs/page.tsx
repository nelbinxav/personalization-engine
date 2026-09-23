'use client'

import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useCallback, useEffect, useState } from 'react'

import { Alert, Badge, Button, Card, Empty, PageHeader, Progress, Select, Spinner, statusTone } from '@/components/ui'
import { api } from '@/lib/api'
import type { Channel, Job, Template, Upload } from '@/lib/types'

function JobsInner() {
  const params = useSearchParams()
  const presetUpload = params.get('upload')

  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [uploads, setUploads] = useState<Upload[]>([])
  const [templates, setTemplates] = useState<Template[]>([])
  const [sources, setSources] = useState<{ key: string; label: string }[]>([])
  const [error, setError] = useState<string | null>(null)

  const [uploadId, setUploadId] = useState(presetUpload || '')
  const [type, setType] = useState<'scrape' | 'personalize'>('scrape')
  const [channel, setChannel] = useState<Channel>('email')
  const [limit, setLimit] = useState('3')
  const [force, setForce] = useState(false)
  const [selectedSources, setSelectedSources] = useState<string[]>([])
  const [busy, setBusy] = useState(false)

  const refresh = useCallback(async () => {
    try {
      setJobs(await api.get<Job[]>('/jobs'))
    } catch (err: any) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    refresh()
    api.get<Upload[]>('/uploads').then((list) => {
      setUploads(list)
      if (!presetUpload && list.length) setUploadId((current) => current || list[0].id)
    })
    api.get<Template[]>('/templates').then(setTemplates).catch(() => null)
    api
      .get<{ sources: { key: string; label: string }[] }>('/jobs/sources')
      .then((r) => {
        setSources(r.sources)
        setSelectedSources(r.sources.map((s) => s.key))
      })
      .catch(() => null)
  }, [presetUpload, refresh])

  // Poll while anything is in flight; stop once everything has settled so an
  // idle tab is not hammering the API.
  useEffect(() => {
    const active = jobs?.some((job) => job.status === 'queued' || job.status === 'running')
    if (!active) return
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [jobs, refresh])

  async function launch() {
    setBusy(true)
    setError(null)
    try {
      await api.post('/jobs', {
        upload_id: uploadId,
        type,
        options: {
          sources: type === 'scrape' ? selectedSources : [],
          channel: type === 'personalize' ? channel : null,
          force,
          limit: limit.trim() ? Number(limit) : null,
        },
      })
      await refresh()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function act(job: Job, action: 'cancel' | 'resume') {
    await api.post(`/jobs/${job.id}/${action}`).catch((err) => setError(err.message))
    refresh()
  }

  const activeTemplate = templates.find((t) => t.channel === channel && t.is_active)

  return (
    <>
      <PageHeader
        title="Jobs"
        description="Scraping and personalization run row by row. A failed row retries on its own; the rest of the sheet keeps going."
      />

      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      <Card className="mb-8">
        <h2 className="font-semibold">Run a job</h2>

        <div className="mt-4 grid gap-4 md:grid-cols-4">
          <div className="md:col-span-2">
            <label className="label">Upload</label>
            <Select value={uploadId} onChange={(e) => setUploadId(e.target.value)}>
              {uploads.length === 0 && <option value="">No uploads yet</option>}
              {uploads.map((upload) => (
                <option key={upload.id} value={upload.id}>
                  {upload.name} ({upload.row_count} rows, {upload.scraped} researched)
                </option>
              ))}
            </Select>
          </div>

          <div>
            <label className="label">Phase</label>
            <Select value={type} onChange={(e) => setType(e.target.value as any)}>
              <option value="scrape">1 · Scrape research</option>
              <option value="personalize">2 · Personalize</option>
            </Select>
          </div>

          <div>
            <label className="label">Row limit</label>
            <Select value={limit} onChange={(e) => setLimit(e.target.value)}>
              <option value="3">First 3 (trial run)</option>
              <option value="25">First 25</option>
              <option value="100">First 100</option>
              <option value="">All rows</option>
            </Select>
            <p className="hint">Personalization costs money per row. Trial 3 first.</p>
          </div>
        </div>

        {type === 'scrape' ? (
          <div className="mt-4">
            <label className="label">Sources</label>
            <div className="flex flex-wrap gap-3">
              {sources.map((source) => (
                <label key={source.key} className="flex items-center gap-2 text-sm text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={selectedSources.includes(source.key)}
                    onChange={(e) =>
                      setSelectedSources((prev) =>
                        e.target.checked ? [...prev, source.key] : prev.filter((k) => k !== source.key),
                      )
                    }
                  />
                  {source.label}
                </label>
              ))}
            </div>
          </div>
        ) : (
          <div className="mt-4 grid gap-4 md:grid-cols-2">
            <div>
              <label className="label">Channel</label>
              <Select value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
                <option value="email">Email</option>
                <option value="linkedin">LinkedIn</option>
                <option value="whatsapp">WhatsApp</option>
              </Select>
              <p className="hint">
                {activeTemplate
                  ? `Using "${activeTemplate.name}" v${activeTemplate.version}${
                      activeTemplate.constraints.max_chars
                        ? `, max ${activeTemplate.constraints.max_chars} chars`
                        : ''
                    }.`
                  : 'No active template for this channel yet.'}
              </p>
            </div>
          </div>
        )}

        <div className="mt-4 flex flex-wrap items-center gap-4">
          <Button onClick={launch} disabled={busy || !uploadId}>
            {busy ? 'Queueing...' : `Queue ${type} job`}
          </Button>
          <label className="flex items-center gap-2 text-sm text-muted-foreground">
            <input type="checkbox" checked={force} onChange={(e) => setForce(e.target.checked)} />
            Redo rows that already have a result
          </label>
        </div>
      </Card>

      {!jobs && <Spinner />}
      {jobs?.length === 0 && <Empty>No jobs yet.</Empty>}

      {jobs && jobs.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Job</th>
                <th>Upload</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Failed</th>
                <th>Cost</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <tr key={job.id}>
                  <td>
                    <Link href={`/jobs/${job.id}`} className="font-medium text-primary underline underline-offset-2">
                      {job.type}
                    </Link>
                    <div className="text-xs text-muted-foreground">
                      {new Date(job.created_at).toLocaleString()}
                    </div>
                  </td>
                  <td className="text-muted-foreground">{job.upload_name}</td>
                  <td>
                    <Badge tone={statusTone(job.status)} title={job.error || undefined}>
                      {job.status.replace('_', ' ')}
                    </Badge>
                  </td>
                  <td>
                    <Progress
                      value={job.counts.done + job.counts.failed + job.counts.skipped}
                      total={job.counts.total}
                    />
                  </td>
                  <td className="tabular-nums">
                    {job.counts.failed > 0 ? (
                      <span className="text-danger">{job.counts.failed}</span>
                    ) : (
                      <span className="text-muted-foreground">0</span>
                    )}
                  </td>
                  <td className="tabular-nums text-muted-foreground">
                    {job.cost_usd ? `$${job.cost_usd.toFixed(3)}` : '—'}
                  </td>
                  <td>
                    <div className="flex justify-end gap-2">
                      {(job.status === 'queued' || job.status === 'running') && (
                        <Button size="sm" variant="ghost" onClick={() => act(job, 'cancel')}>
                          Cancel
                        </Button>
                      )}
                      {(job.status === 'blocked_auth' || job.status === 'cancelled') && (
                        <Button size="sm" variant="secondary" onClick={() => act(job, 'resume')}>
                          Resume
                        </Button>
                      )}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {jobs?.some((j) => j.status === 'blocked_auth') && (
        <div className="mt-4">
          <Alert tone="warning" title="A job is parked on a credential problem">
            Rows already finished kept their results. Reconnect Claude in{' '}
            <Link href="/settings" className="underline">
              Settings
            </Link>
            , then hit Resume — it picks up only the rows that never ran.
          </Alert>
        </div>
      )}
    </>
  )
}

export default function JobsPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <JobsInner />
    </Suspense>
  )
}
