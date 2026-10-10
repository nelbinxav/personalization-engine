'use client'

import { ArrowRight, Microscope, PenLine } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { requestNotifications } from '@/components/job-watcher'
import {
  Alert,
  Button,
  CheckboxRow,
  Field,
  Segmented,
  Select,
  ToggleChip,
  cn,
  toast,
} from '@/components/ui'
import { api } from '@/lib/api'
import type { Channel, Job, JobType, Upload } from '@/lib/types'
import { CHANNELS, type Readiness } from '@/lib/workflow'

const LIMITS = [
  { value: '3', label: 'Trial · 3' },
  { value: '10', label: '10' },
  { value: '25', label: '25' },
  // About a day of LinkedIn reads at the default daily limit.
  { value: '75', label: '75' },
  { value: '100', label: '100' },
  { value: 'all', label: 'All' },
] as const
type Limit = (typeof LIMITS)[number]['value']

/**
 * Configure and queue one phase for one upload. Shared by the upload page and
 * the Jobs page so both run the same checks: anything that would make every
 * row fail (no Claude, no offer text, no template for the channel) is shown
 * up front instead of surfacing as N failed rows afterwards.
 */
export function LaunchJob({
  upload,
  phase,
  onPhaseChange,
  readiness,
  compact = false,
}: {
  upload: Upload
  phase: JobType
  onPhaseChange: (phase: JobType) => void
  readiness: Readiness
  compact?: boolean
}) {
  const router = useRouter()
  const { settings, templates, agents, ai } = readiness

  const [channel, setChannel] = useState<Channel>('email')
  const [limit, setLimit] = useState<Limit>('3')
  const [agentId, setAgentId] = useState('')
  const [force, setForce] = useState(false)
  const [sources, setSources] = useState<string[] | null>(null)
  const [busy, setBusy] = useState(false)

  const catalog = settings?.catalog.sources ?? []

  // Default to the sources enabled in Settings, once they have loaded.
  useEffect(() => {
    if (settings && sources === null) setSources(settings.settings.enabled_sources)
  }, [settings, sources])

  // Default to an agent: they carry the offer and how rows are written.
  useEffect(() => {
    if (!agentId && agents.length) setAgentId(agents.find((a) => a.is_active)?.id ?? agents[0].id)
  }, [agents, agentId])

  // Default the channel to one that actually has a template.
  useEffect(() => {
    const active = templates.filter((t) => t.is_active).map((t) => t.channel)
    if (active.length && !active.includes(channel)) setChannel(active[0])
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [templates])

  const template = templates.find((t) => t.channel === channel && t.is_active)
  const blockers = readiness.loading ? [] : readiness.blockersFor(phase, channel)
  const noSources = phase === 'scrape' && sources !== null && sources.length === 0

  // Rough count of what the backend will pick: rows without a result for this
  // phase (or all eligible rows with "redo"), capped by the limit.
  const eligible =
    phase === 'scrape'
      ? force
        ? upload.row_count
        : upload.row_count - upload.scraped
      : force
        ? upload.scraped
        : Math.max(0, upload.scraped - upload.personalized)
  const rows = limit === 'all' ? eligible : Math.min(Number(limit), eligible)

  async function launch() {
    setBusy(true)
    // Asked here because it needs a click, and this is the moment it matters.
    requestNotifications()
    try {
      const job = await api.post<Job>('/jobs', {
        upload_id: upload.id,
        type: phase,
        options: {
          sources: phase === 'scrape' ? sources ?? [] : [],
          channel: phase === 'personalize' ? channel : null,
          agent_id: phase === 'personalize' && agentId ? agentId : null,
          force,
          limit: limit === 'all' ? null : Number(limit),
        },
      })
      toast.success(`Queued ${job.counts.total} row${job.counts.total === 1 ? '' : 's'}.`)
      router.push(`/jobs/${job.id}`)
    } catch (err: any) {
      toast.error(err.message)
      setBusy(false)
    }
  }

  return (
    <div className="space-y-5">
      {!compact && (
        <div className="grid gap-2 sm:grid-cols-2">
          {(
            [
              {
                key: 'scrape',
                icon: Microscope,
                title: 'Research',
                body: 'Fetch websites, news and LinkedIn for each row.',
                progress: `${upload.scraped}/${upload.row_count} researched`,
              },
              {
                key: 'personalize',
                icon: PenLine,
                title: 'Personalize',
                body: 'Write a message from each row’s research.',
                progress: `${upload.personalized}/${upload.scraped} written`,
              },
            ] as const
          ).map((option, index) => {
            const selected = phase === option.key
            return (
              <button
                key={option.key}
                type="button"
                onClick={() => onPhaseChange(option.key)}
                aria-pressed={selected}
                className={cn(
                  'flex items-start gap-3 rounded-lg border p-3.5 text-left transition-colors',
                  selected
                    ? 'border-primary/60 bg-primary/[0.06] ring-1 ring-primary/30'
                    : 'border-border hover:border-border-strong hover:bg-muted/40',
                )}
              >
                <span
                  className={cn(
                    'flex h-8 w-8 shrink-0 items-center justify-center rounded-lg',
                    selected ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
                  )}
                >
                  <option.icon className="h-4 w-4" />
                </span>
                <span className="min-w-0">
                  <span className="block text-sm font-medium">
                    <span className="text-muted-foreground">{index + 1}.</span> {option.title}
                  </span>
                  <span className="block text-xs text-muted-foreground">{option.body}</span>
                  <span className="mt-1.5 block text-xs font-medium tabular-nums text-foreground/80">
                    {option.progress}
                  </span>
                </span>
              </button>
            )
          })}
        </div>
      )}

      {phase === 'scrape' ? (
        <Field
          label="Sources"
          hint={
            <>
              Defaults come from{' '}
              <Link href="/settings#research" className="link">
                Settings
              </Link>
              . Sources that need a key are skipped when it is missing.
            </>
          }
        >
          <div className="flex flex-wrap gap-2">
            {catalog.map((source) => (
              <ToggleChip
                key={source.key}
                checked={sources?.includes(source.key) ?? false}
                onChange={(on) =>
                  setSources((prev) =>
                    on ? [...(prev ?? []), source.key] : (prev ?? []).filter((k) => k !== source.key),
                  )
                }
              >
                {source.label}
              </ToggleChip>
            ))}
          </div>
        </Field>
      ) : (
        <Field
          label="Channel"
          hint={
            template ? (
              <>
                Using <span className="font-medium text-foreground">{template.name}</span> v{template.version}
                {template.constraints.max_chars ? `, max ${template.constraints.max_chars} characters` : ''}.{' '}
                <Link href={`/templates?channel=${channel}`} className="link">
                  Edit
                </Link>
              </>
            ) : undefined
          }
        >
          <Segmented
            label="Channel"
            value={channel}
            onChange={setChannel}
            options={CHANNELS.map((c) => ({
              value: c.key,
              label: (
                <>
                  {c.label}
                  {!templates.some((t) => t.channel === c.key && t.is_active) && (
                    <span className="h-1.5 w-1.5 rounded-full bg-warning" title="No active template" />
                  )}
                </>
              ),
            }))}
          />
        </Field>
      )}

      {phase === 'personalize' && (
        <Field
          label="Agent"
          hint={
            <>
              Who we are writing for.{' '}
              <Link href="/agents" className="link">
                {agents.length ? 'Edit agents' : 'Train one'}
              </Link>
              
            </>
          }
        >
          <Select value={agentId} onChange={(e) => setAgentId(e.target.value)}>
            {agents.length === 0 && <option value="">No agent yet</option>}
            {agents.map((a) => (
              <option key={a.id} value={a.id}>
                {a.name} · v{a.version}
              </option>
            ))}
          </Select>
        </Field>
      )}

      <Field
        label="How many rows"
        hint={
          phase === 'personalize'
            ? ai?.mode === 'claude_code'
              ? 'Each row makes three Claude calls against your plan’s usage. Check a trial before running everything.'
              : 'Each row makes three paid Claude calls. Check a trial before running everything.'
            : 'Start with a trial to check the sources find something useful.'
        }
      >
        <Segmented
          label="Row limit"
          value={limit}
          onChange={setLimit}
          options={LIMITS.map((l) => ({ value: l.value, label: l.label }))}
        />
      </Field>

      <CheckboxRow
        checked={force}
        onChange={setForce}
        label="Redo rows that already have a result"
        description={
          phase === 'scrape'
            ? 'Otherwise only rows that have not been researched are picked.'
            : 'Otherwise only rows without a message are picked. Redoing is billed again.'
        }
      />

      {blockers.length > 0 && (
        <div className="space-y-2">
          {blockers.map((b) => (
            <Alert
              key={b.key}
              tone="warning"
              title={b.label}
              action={
                <Link href={b.href} className="link text-sm">
                  {b.cta}
                </Link>
              }
            >
              {b.detail}
            </Alert>
          ))}
        </div>
      )}

      {phase === 'personalize' && upload.scraped === 0 && (
        <Alert tone="neutral" title="Nothing researched yet">
          Personalization writes from research, so run step 1 first.
        </Alert>
      )}

      <div className="flex flex-wrap items-center gap-3 border-t border-border pt-5">
        <Button
          size="lg"
          onClick={launch}
          loading={busy}
          disabled={blockers.length > 0 || noSources || (phase === 'personalize' && upload.scraped === 0)}
        >
          {phase === 'scrape' ? 'Start research' : 'Start personalizing'}
          <ArrowRight className="h-4 w-4" />
        </Button>
        <span className="text-sm text-muted-foreground">
          {noSources
            ? 'Pick at least one source.'
            : rows > 0
              ? `About ${rows} row${rows === 1 ? '' : 's'}${eligible > rows ? ` of ${eligible} remaining` : ''}.`
              : force
                ? 'No eligible rows.'
                : 'Every row already has a result. Tick “Redo” to run them again.'}
        </span>
      </div>
    </div>
  )
}
