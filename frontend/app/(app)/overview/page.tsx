'use client'

import {
  ArrowRight,
  CheckCircle2,
  Circle,
  Download,
  FileSpreadsheet,
  Microscope,
  PenLine,
  Plus,
  Sparkles,
} from 'lucide-react'
import Link from 'next/link'
import { useCallback, useEffect, useState } from 'react'

import {
  Card,
  CardHeader,
  LinkButton,
  PageHeader,
  Progress,
  Skeleton,
  StatusBadge,
  Stepper,
  cn,
} from '@/components/ui'
import { UsagePanel } from '@/components/usage-panel'
import { api } from '@/lib/api'
import type { Job, Upload } from '@/lib/types'
import {
  NEXT_ACTION_LABEL,
  PHASE_LABEL,
  isActive,
  isLive,
  nextAction,
  timeAgo,
  uploadSteps,
  useReadiness,
} from '@/lib/workflow'

const HOW_IT_WORKS = [
  { icon: FileSpreadsheet, title: 'Import', body: 'A CSV or Google Sheet of prospects. Your columns are kept as they are.' },
  { icon: Microscope, title: 'Research', body: 'Websites, news and LinkedIn are fetched for every row.' },
  {
    icon: PenLine,
    title: 'Personalize',
    body: 'Claude turns the research into facts, picks an angle it can cite, and writes the message.',
  },
  { icon: Download, title: 'Download', body: 'A CSV with your original columns first, ready to paste back.' },
]

export default function OverviewPage() {
  const readiness = useReadiness()
  const [uploads, setUploads] = useState<Upload[] | null>(null)
  const [jobs, setJobs] = useState<Job[]>([])

  const refresh = useCallback(async () => {
    const [u, j] = await Promise.all([
      api.get<Upload[]>('/uploads').catch(() => [] as Upload[]),
      api.get<Job[]>('/jobs?limit=20').catch(() => [] as Job[]),
    ])
    setUploads(u)
    setJobs(j)
  }, [])

  useEffect(() => {
    refresh()
  }, [refresh])

  const running = jobs.filter(isActive)
  // Waiting jobs restart by themselves, so keep polling for them too.
  const live = jobs.filter(isLive).length
  useEffect(() => {
    if (!live) return
    const timer = setInterval(refresh, 4000)
    return () => clearInterval(timer)
  }, [live, refresh])

  const done = readiness.checks.filter((c) => c.ok).length
  const setupComplete = !readiness.loading && done === readiness.checks.length
  const inProgress = (uploads ?? []).filter((u) => nextAction(u) !== 'export').slice(0, 4)

  return (
    <>
      <PageHeader
        title="Overview"
        description="Research prospects, then write outreach that cites something real about each one."
        action={
          <LinkButton href="/uploads/new" icon={Plus}>
            New upload
          </LinkButton>
        }
      />

      {!readiness.loading && !setupComplete && (
        <Card className="mb-8">
          <CardHeader
            icon={Sparkles}
            title="Finish setting up"
            description={`${done} of ${readiness.checks.length} done. Research works without these; personalization needs them.`}
          />
          <div className="mb-4 h-1.5 overflow-hidden rounded-full bg-muted">
            <div
              className="h-full rounded-full bg-primary transition-all"
              style={{ width: `${(done / readiness.checks.length) * 100}%` }}
            />
          </div>
          <ul className="divide-y divide-border">
            {readiness.checks.map((check) => (
              <li key={check.key} className="flex items-center gap-3 py-3">
                {check.ok ? (
                  <CheckCircle2 className="h-5 w-5 shrink-0 text-success" />
                ) : (
                  <Circle className="h-5 w-5 shrink-0 text-muted-foreground/60" />
                )}
                <div className="min-w-0 flex-1">
                  <p className={cn('text-sm font-medium', check.ok && 'text-muted-foreground line-through decoration-muted-foreground/40')}>
                    {check.label}
                  </p>
                  <p className="text-xs text-muted-foreground">{check.detail}</p>
                </div>
                {!check.ok && (
                  <LinkButton href={check.href} size="sm" variant="outline">
                    {check.cta}
                  </LinkButton>
                )}
              </li>
            ))}
          </ul>
        </Card>
      )}

      <UsagePanel />

      {uploads?.length === 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">How it works</h2>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            {HOW_IT_WORKS.map((step, i) => (
              <Card key={step.title} className="p-4">
                <div className="mb-3 flex items-center gap-2.5">
                  <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-primary/10 text-primary">
                    <step.icon className="h-4 w-4" />
                  </span>
                  <span className="text-xs font-medium text-muted-foreground">Step {i + 1}</span>
                </div>
                <p className="font-medium">{step.title}</p>
                <p className="mt-1 text-sm text-muted-foreground">{step.body}</p>
              </Card>
            ))}
          </div>
          <div className="mt-6">
            <LinkButton href="/uploads/new" size="lg">
              Import your first list <ArrowRight className="h-4 w-4" />
            </LinkButton>
          </div>
        </section>
      )}

      {running.length > 0 && (
        <section className="mb-8">
          <h2 className="mb-3 text-sm font-semibold text-muted-foreground">Running now</h2>
          <div className="space-y-2">
            {running.map((job) => (
              <Link
                key={job.id}
                href={`/jobs/${job.id}`}
                className="card flex flex-wrap items-center gap-4 p-4 transition-colors hover:border-border-strong"
              >
                <StatusBadge status={job.status} />
                <span className="min-w-0 flex-1">
                  <span className="font-medium">{PHASE_LABEL[job.type]}</span>
                  <span className="text-muted-foreground"> · {job.upload_name}</span>
                </span>
                <Progress
                  done={job.counts.done + job.counts.skipped}
                  failed={job.counts.failed}
                  total={job.counts.total}
                />
              </Link>
            ))}
          </div>
        </section>
      )}

      {!uploads && <Skeleton className="h-40 w-full" />}

      {inProgress.length > 0 && (
        <section className="mb-8">
          <div className="mb-3 flex items-baseline justify-between">
            <h2 className="text-sm font-semibold text-muted-foreground">Continue where you left off</h2>
            <Link href="/uploads" className="link text-sm">
              All uploads
            </Link>
          </div>
          <div className="space-y-3">
            {inProgress.map((upload) => {
              const next = nextAction(upload)
              return (
                <Card key={upload.id} className="p-5">
                  <div className="mb-5 flex flex-wrap items-center justify-between gap-3">
                    <div>
                      <Link href={`/uploads/${upload.id}`} className="font-medium hover:text-primary">
                        {upload.name}
                      </Link>
                      <p className="text-xs text-muted-foreground">
                        {upload.row_count} rows · added {timeAgo(upload.created_at)}
                      </p>
                    </div>
                    <LinkButton href={`/uploads/${upload.id}`} size="sm">
                      {NEXT_ACTION_LABEL[next]} <ArrowRight className="h-3.5 w-3.5" />
                    </LinkButton>
                  </div>
                  <Stepper steps={uploadSteps(upload)} />
                </Card>
              )
            })}
          </div>
        </section>
      )}

      {uploads && uploads.length > 0 && inProgress.length === 0 && running.length === 0 && (
        <Card className="flex flex-wrap items-center justify-between gap-4">
          <div>
            <p className="font-medium">All caught up</p>
            <p className="text-sm text-muted-foreground">Every upload has been researched and personalized.</p>
          </div>
          <LinkButton href="/uploads" variant="outline">
            View uploads
          </LinkButton>
        </Card>
      )}
    </>
  )
}
