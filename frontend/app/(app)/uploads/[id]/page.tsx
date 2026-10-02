'use client'

import { ArrowLeft, Download, FileSpreadsheet, History, PartyPopper, Trash2 } from 'lucide-react'
import Link from 'next/link'
import { useParams, useRouter, useSearchParams } from 'next/navigation'
import { Suspense, useCallback, useEffect, useState } from 'react'

import { LaunchJob } from '@/components/launch-job'
import {
  Alert,
  Badge,
  Card,
  CardHeader,
  PageHeader,
  Progress,
  Spinner,
  StatusBadge,
  Stepper,
  buttonClasses,
  toast,
} from '@/components/ui'
import { api, exportUrl } from '@/lib/api'
import type { Job, JobType, Upload } from '@/lib/types'
import {
  FIELD_META,
  PHASE_LABEL,
  isActive,
  isLive,
  money,
  nextAction,
  timeAgo,
  uploadSteps,
  useReadiness,
} from '@/lib/workflow'

const DOWNLOADS = [
  { kind: 'personalized', label: 'Messages', body: 'Your columns plus subject, message, angle and evidence.' },
  { kind: 'research', label: 'Research', body: 'Your columns plus what each source found.' },
  { kind: 'combined', label: 'Everything', body: 'Research and messages side by side.' },
] as const

function UploadInner() {
  const { id } = useParams<{ id: string }>()
  const params = useSearchParams()
  const router = useRouter()
  const readiness = useReadiness()

  const [upload, setUpload] = useState<Upload | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])
  const [error, setError] = useState<string | null>(null)
  const [phase, setPhase] = useState<JobType | null>((params.get('phase') as JobType) || null)

  const refresh = useCallback(async () => {
    try {
      const [u, j] = await Promise.all([
        api.get<Upload>(`/uploads/${id}`),
        api.get<Job[]>(`/jobs?upload_id=${id}`),
      ])
      setUpload(u)
      setJobs(j)
    } catch (err: any) {
      setError(err.message)
    }
  }, [id])

  useEffect(() => {
    refresh()
  }, [refresh])

  const running = jobs.filter(isActive)
  // Waiting jobs restart by themselves, so keep polling for them too.
  const live = jobs.filter(isLive).length
  useEffect(() => {
    if (!live) return
    const timer = setInterval(refresh, 3000)
    return () => clearInterval(timer)
  }, [live, refresh])

  // Preselect whichever phase the upload needs next.
  useEffect(() => {
    if (upload && phase === null) {
      setPhase(nextAction(upload) === 'personalize' ? 'personalize' : 'scrape')
    }
  }, [upload, phase])

  async function remove() {
    if (!upload) return
    if (!confirm(`Delete "${upload.name}", its ${upload.row_count} rows and every job and message? This cannot be undone.`)) {
      return
    }
    try {
      await api.del(`/uploads/${upload.id}`)
      toast.success(`Deleted “${upload.name}”.`)
      router.push('/uploads')
    } catch (err: any) {
      toast.error(err.message)
    }
  }

  if (error && !upload) return <Alert title="Could not load this upload">{error}</Alert>
  if (!upload || !phase) return <Spinner />

  const next = nextAction(upload)

  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/uploads" className="inline-flex items-center gap-1.5 hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> Uploads
          </Link>
        }
        title={upload.name}
        description={
          <>
            {upload.source === 'gsheet' ? 'Google Sheet' : 'CSV'} · {upload.row_count} rows ·{' '}
            {upload.headers.length} columns · added {timeAgo(upload.created_at)}
          </>
        }
      />

      <Card className="mb-6 px-6 py-5">
        <Stepper steps={uploadSteps(upload)} />
      </Card>

      {running.length > 0 && (
        <Alert
          tone="info"
          className="mb-6"
          title={`${PHASE_LABEL[running[0].type]} is running`}
          action={
            <Link href={`/jobs/${running[0].id}`} className="link text-sm">
              Watch progress
            </Link>
          }
        >
          <Progress
            done={running[0].counts.done + running[0].counts.skipped}
            failed={running[0].counts.failed}
            total={running[0].counts.total}
            className="mt-1.5"
          />
        </Alert>
      )}

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-3">
          {next === 'export' && (
            <Alert tone="success" title="Every row is researched and written">
              Download the messages below, or re-run a phase with “Redo” after changing a prompt.
            </Alert>
          )}
          <Card>
            <CardHeader
              title={next === 'export' ? 'Run again' : 'Next step'}
              description="Pick a phase, try a few rows, check them, then run the rest."
            />
            <LaunchJob upload={upload} phase={phase} onPhaseChange={setPhase} readiness={readiness} />
          </Card>
        </div>

        <div className="space-y-6 lg:col-span-2">
          <Card className={next === 'export' ? 'ring-1 ring-success/40' : undefined}>
            <CardHeader
              icon={next === 'export' ? PartyPopper : Download}
              title="Download"
              description="Original columns first, in order, so it pastes straight back."
            />
            <ul className="space-y-2">
              {DOWNLOADS.map((d) => {
                const empty = d.kind === 'research' ? upload.scraped === 0 : upload.personalized === 0
                return (
                  <li key={d.kind}>
                    <a
                      href={exportUrl(upload.id, d.kind)}
                      className="group flex items-center gap-3 rounded-lg border border-border px-3 py-2.5 transition-colors hover:border-border-strong hover:bg-muted/40"
                    >
                      <FileSpreadsheet className="h-4 w-4 shrink-0 text-muted-foreground group-hover:text-primary" />
                      <span className="min-w-0 flex-1">
                        <span className="block text-sm font-medium">
                          {d.label}
                          {empty && <span className="ml-2 text-xs font-normal text-muted-foreground">empty so far</span>}
                        </span>
                        <span className="block text-xs text-muted-foreground">{d.body}</span>
                      </span>
                      <Download className="h-4 w-4 shrink-0 text-muted-foreground group-hover:text-foreground" />
                    </a>
                  </li>
                )
              })}
            </ul>
          </Card>

          <Card>
            <CardHeader icon={History} title="Runs" description="Every job on this upload, newest first." />
            {jobs.length === 0 ? (
              <p className="text-sm text-muted-foreground">Nothing has run yet.</p>
            ) : (
              <ul className="-mx-2 space-y-0.5">
                {jobs.map((job) => (
                  <li key={job.id}>
                    <Link
                      href={`/jobs/${job.id}`}
                      className="flex items-center gap-3 rounded-md px-2 py-2 text-sm transition-colors hover:bg-muted/60"
                    >
                      <span className="w-24 shrink-0 font-medium">{PHASE_LABEL[job.type]}</span>
                      <StatusBadge status={job.status} />
                      <span className="ml-auto text-xs tabular-nums text-muted-foreground">
                        {job.counts.total} rows · {timeAgo(job.created_at)}
                      </span>
                    </Link>
                  </li>
                ))}
              </ul>
            )}
            {jobs.some((j) => j.cost_usd > 0) && (
              <p className="mt-3 border-t border-border pt-3 text-xs text-muted-foreground">
                Spent so far: {money(jobs.reduce((sum, j) => sum + j.cost_usd, 0))}
              </p>
            )}
          </Card>

          <Card>
            <CardHeader title="Column mapping" description="Which of your columns feed research and prompts." />
            <dl className="space-y-1.5 text-sm">
              {Object.entries(upload.column_mapping).map(([field, column]) => (
                <div key={field} className="flex items-center justify-between gap-3">
                  <dt className="text-muted-foreground">{FIELD_META[field]?.label ?? field}</dt>
                  <dd>
                    <Badge>{column}</Badge>
                  </dd>
                </div>
              ))}
            </dl>
          </Card>

          <button onClick={remove} className={buttonClasses('ghost', 'sm', 'text-danger hover:bg-danger/10 hover:text-danger')}>
            <Trash2 className="h-3.5 w-3.5" /> Delete upload
          </button>
        </div>
      </div>
    </>
  )
}

export default function UploadPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <UploadInner />
    </Suspense>
  )
}
