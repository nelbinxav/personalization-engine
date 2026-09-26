'use client'

import { PlayCircle, Plus, X } from 'lucide-react'
import Link from 'next/link'
import { useSearchParams } from 'next/navigation'
import { Suspense, useCallback, useEffect, useState } from 'react'

import { LaunchJob } from '@/components/launch-job'
import {
  Alert,
  Button,
  Card,
  CardHeader,
  Empty,
  Field,
  LinkButton,
  PageHeader,
  Progress,
  Segmented,
  Select,
  Skeleton,
  Spinner,
  StatusBadge,
  toast,
} from '@/components/ui'
import { api } from '@/lib/api'
import type { Job, JobType, Upload } from '@/lib/types'
import { PHASE_LABEL, duration, isActive, money, nextAction, timeAgo, useReadiness } from '@/lib/workflow'

type Filter = 'all' | 'active' | 'attention'

function needsAttention(job: Job) {
  return job.status === 'blocked_auth' || job.status === 'failed' || job.counts.failed > 0
}

function JobsInner() {
  const params = useSearchParams()
  const presetUpload = params.get('upload')
  const readiness = useReadiness()

  const [jobs, setJobs] = useState<Job[] | null>(null)
  const [uploads, setUploads] = useState<Upload[]>([])
  const [error, setError] = useState<string | null>(null)
  const [filter, setFilter] = useState<Filter>('all')

  const [launching, setLaunching] = useState(!!presetUpload)
  const [uploadId, setUploadId] = useState(presetUpload || '')
  const [phase, setPhase] = useState<JobType>('scrape')

  const refresh = useCallback(async () => {
    try {
      setJobs(await api.get<Job[]>('/jobs'))
    } catch (err: any) {
      setError(err.message)
    }
  }, [])

  useEffect(() => {
    refresh()
    api
      .get<Upload[]>('/uploads')
      .then((list) => {
        setUploads(list)
        if (!presetUpload && list.length) setUploadId((current) => current || list[0].id)
      })
      .catch(() => null)
  }, [presetUpload, refresh])

  const selectedUpload = uploads.find((u) => u.id === uploadId)

  // Follow the selected upload's next step unless the operator picks one.
  useEffect(() => {
    if (selectedUpload) setPhase(nextAction(selectedUpload) === 'personalize' ? 'personalize' : 'scrape')
  }, [selectedUpload])

  // Poll while anything is in flight; stop once everything has settled so an
  // idle tab is not hammering the API.
  const anyActive = jobs?.some(isActive)
  useEffect(() => {
    if (!anyActive) return
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [anyActive, refresh])

  async function act(job: Job, action: 'cancel' | 'resume') {
    try {
      await api.post(`/jobs/${job.id}/${action}`)
      toast.success(action === 'cancel' ? 'Job cancelled. Finished rows keep their results.' : 'Job resumed.')
    } catch (err: any) {
      toast.error(err.message)
    }
    refresh()
  }

  const visible =
    jobs?.filter((job) =>
      filter === 'active' ? isActive(job) : filter === 'attention' ? needsAttention(job) : true,
    ) ?? []
  const parked = jobs?.filter((j) => j.status === 'blocked_auth') ?? []

  return (
    <>
      <PageHeader
        title="Jobs"
        description="Every research and personalization run. Rows run one at a time: a failed row retries on its own and the rest of the sheet keeps going."
        action={
          !launching && (
            <Button icon={Plus} onClick={() => setLaunching(true)} disabled={!uploads.length}>
              New job
            </Button>
          )
        }
      />

      {error && <Alert className="mb-6">{error}</Alert>}

      {parked.length > 0 && (
        <Alert
          tone="warning"
          className="mb-6"
          title={`${parked.length === 1 ? 'A job is' : `${parked.length} jobs are`} paused`}
          action={
            <LinkButton href="/settings#claude" size="sm" variant="outline">
              Claude settings
            </LinkButton>
          }
        >
          {parked[0].error ?? 'Claude could not be reached.'} Finished rows kept their results, and Resume picks up
          only the rows that never ran.
        </Alert>
      )}

      {launching && (
        <Card className="mb-8 animate-in fade-in slide-in-from-top-1">
          <CardHeader
            icon={PlayCircle}
            title="Start a job"
            description="Usually you would do this from the upload itself. This is the shortcut."
            action={
              <Button size="icon" variant="ghost" aria-label="Close" onClick={() => setLaunching(false)}>
                <X className="h-4 w-4" />
              </Button>
            }
          />
          <Field id="upload" label="Upload" className="mb-5 max-w-md">
            <Select id="upload" value={uploadId} onChange={(e) => setUploadId(e.target.value)}>
              {uploads.map((upload) => (
                <option key={upload.id} value={upload.id}>
                  {upload.name} · {upload.row_count} rows
                </option>
              ))}
            </Select>
          </Field>
          {selectedUpload && (
            <LaunchJob upload={selectedUpload} phase={phase} onPhaseChange={setPhase} readiness={readiness} />
          )}
        </Card>
      )}

      {jobs && jobs.length > 0 && (
        <Segmented
          label="Filter jobs"
          className="mb-4"
          size="sm"
          value={filter}
          onChange={setFilter}
          options={[
            { value: 'all', label: 'All', count: jobs.length },
            { value: 'active', label: 'Running', count: jobs.filter(isActive).length },
            { value: 'attention', label: 'Needs attention', count: jobs.filter(needsAttention).length },
          ]}
        />
      )}

      {!jobs && (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-14 w-full" />
          ))}
        </div>
      )}

      {jobs?.length === 0 && (
        <Empty
          icon={PlayCircle}
          title="No jobs yet"
          action={
            uploads.length ? (
              <Button icon={Plus} onClick={() => setLaunching(true)}>
                Start one
              </Button>
            ) : (
              <LinkButton href="/uploads/new" icon={Plus}>
                Add an upload first
              </LinkButton>
            )
          }
        >
          A job researches or personalizes the rows of one upload.
        </Empty>
      )}

      {jobs && jobs.length > 0 && visible.length === 0 && (
        <Empty className="py-10">Nothing here.</Empty>
      )}

      {visible.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Job</th>
                <th>Status</th>
                <th>Progress</th>
                <th>Cost</th>
                <th>Started</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {visible.map((job) => (
                <tr key={job.id}>
                  <td>
                    <Link href={`/jobs/${job.id}`} className="font-medium hover:text-primary">
                      {PHASE_LABEL[job.type]}
                      {job.options.channel && job.type === 'personalize' && (
                        <span className="font-normal text-muted-foreground"> · {job.options.channel}</span>
                      )}
                    </Link>
                    <div className="text-xs text-muted-foreground">
                      <Link href={`/uploads/${job.upload_id}`} className="hover:text-foreground">
                        {job.upload_name ?? 'Deleted upload'}
                      </Link>
                    </div>
                  </td>
                  <td>
                    <StatusBadge status={job.status} title={job.error || undefined} />
                  </td>
                  <td>
                    <Progress
                      done={job.counts.done + job.counts.skipped}
                      failed={job.counts.failed}
                      total={job.counts.total}
                    />
                    {job.counts.failed > 0 && (
                      <div className="mt-1 text-xs text-danger">{job.counts.failed} failed</div>
                    )}
                  </td>
                  <td className="tabular-nums text-muted-foreground">{money(job.cost_usd)}</td>
                  <td className="whitespace-nowrap text-xs text-muted-foreground">
                    {timeAgo(job.created_at)}
                    {job.started_at && (job.finished_at || isActive(job)) && (
                      <div className="tabular-nums">
                        {job.finished_at ? 'took' : 'for'} {duration(job.started_at, job.finished_at)}
                      </div>
                    )}
                  </td>
                  <td>
                    <div className="flex justify-end gap-2">
                      {isActive(job) && (
                        <Button size="sm" variant="ghost" onClick={() => act(job, 'cancel')}>
                          Cancel
                        </Button>
                      )}
                      {(job.status === 'blocked_auth' || job.status === 'cancelled') && (
                        <Button size="sm" variant="secondary" onClick={() => act(job, 'resume')}>
                          Resume
                        </Button>
                      )}
                      <LinkButton href={`/jobs/${job.id}`} size="sm" variant="outline">
                        Open
                      </LinkButton>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
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
