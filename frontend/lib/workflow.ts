'use client'

import { useCallback, useEffect, useState } from 'react'

import type { StepState } from '@/components/ui'
import { api } from '@/lib/api'
import type { AiStatus, Channel, Job, SettingsResponse, Template, Upload } from '@/lib/types'

/* --------------------------------------------------------------- constants */

export const CHANNELS: { key: Channel; label: string; note: string }[] = [
  { key: 'email', label: 'Email', note: 'Needs a subject line.' },
  { key: 'linkedin', label: 'LinkedIn', note: 'Connection notes are capped at 300 characters.' },
  { key: 'whatsapp', label: 'WhatsApp', note: 'Keep it short and conversational.' },
]

export const PHASE_LABEL: Record<Job['type'], string> = {
  scrape: 'Research',
  personalize: 'Personalize',
}

/** Human names for the identity fields the column mapper offers. */
export const FIELD_META: Record<string, { label: string; help?: string }> = {
  full_name: { label: 'Full name', help: 'Used to address the message.' },
  first_name: { label: 'First name', help: 'Preferred in greetings.' },
  last_name: { label: 'Last name' },
  title: { label: 'Job title' },
  company: { label: 'Company', help: 'Drives the news and podcast searches.' },
  website: { label: 'Website', help: 'Scraped for site content and an RSS feed.' },
  linkedin_url: { label: 'LinkedIn profile URL', help: 'Scraped for the personal profile.' },
  linkedin_company_url: { label: 'LinkedIn company URL', help: 'Scraped for the company page.' },
  email: { label: 'Email' },
  phone: { label: 'Phone' },
  location: { label: 'Location' },
}

// Mirrors backend `ingest/mapping.validate_mapping`, so the operator sees the
// problem next to the selects instead of as a 400 after clicking Create.
export const IDENTIFIER_FIELDS = ['full_name', 'first_name', 'company']
export const TARGET_FIELDS = ['website', 'linkedin_url', 'linkedin_company_url']

export function mappingProblems(mapping: Record<string, string>): string[] {
  const problems: string[] = []
  if (!IDENTIFIER_FIELDS.some((f) => mapping[f])) {
    problems.push('Map a full name, first name or company so each row can be identified.')
  }
  if (!TARGET_FIELDS.some((f) => mapping[f])) {
    problems.push('Map a website or a LinkedIn URL, otherwise there is nothing to research.')
  }
  return problems
}

/* -------------------------------------------------------------- formatting */

export function money(value: number, digits = 3): string {
  if (!value) return '—'
  return value < 0.001 ? '<$0.001' : `$${value.toFixed(digits)}`
}

export function timeAgo(iso: string | null | undefined): string {
  if (!iso) return '—'
  // The API emits naive UTC timestamps; without a zone JS would read them as local.
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
  const seconds = Math.round((Date.now() - date.getTime()) / 1000)
  if (seconds < 45) return 'just now'
  const minutes = Math.round(seconds / 60)
  if (minutes < 60) return `${minutes}m ago`
  const hours = Math.round(minutes / 60)
  if (hours < 24) return `${hours}h ago`
  const days = Math.round(hours / 24)
  if (days < 7) return `${days}d ago`
  return date.toLocaleDateString()
}

export function duration(start: string | null, end: string | null): string | null {
  if (!start) return null
  const parse = (iso: string) => new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`).getTime()
  const seconds = Math.max(0, Math.round(((end ? parse(end) : Date.now()) - parse(start)) / 1000))
  if (seconds < 60) return `${seconds}s`
  const minutes = Math.floor(seconds / 60)
  if (minutes < 60) return `${minutes}m ${seconds % 60}s`
  return `${Math.floor(minutes / 60)}h ${minutes % 60}m`
}

export function isActive(job: Pick<Job, 'status'>): boolean {
  return job.status === 'queued' || job.status === 'running'
}

/** Paused for a limit (Claude usage, or the daily LinkedIn cap). It restarts by itself. */
export function isWaiting(job: Pick<Job, 'status'>): boolean {
  return job.status === 'rate_limited'
}

/** Still going to change without anyone touching it: keep polling. */
export function isLive(job: Pick<Job, 'status'>): boolean {
  return isActive(job) || isWaiting(job)
}

/** "at 3:40 PM", or with the day when it is not today. */
export function clockTime(iso: string | null | undefined): string {
  if (!iso) return 'soon'
  const date = new Date(/[zZ]|[+-]\d\d:?\d\d$/.test(iso) ? iso : `${iso}Z`)
  const time = date.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })
  const sameDay = date.toDateString() === new Date().toDateString()
  return sameDay ? `at ${time}` : `on ${date.toLocaleDateString([], { weekday: 'short' })} at ${time}`
}

/* ---------------------------------------------------------------- workflow */

export type NextAction = 'research' | 'personalize' | 'export'

/**
 * What an upload should do next. Deliberately favours the trial loop the
 * launcher encourages: research a few rows, personalize those, check them,
 * then research the rest -- rather than researching 500 rows before seeing a
 * single message.
 */
export function nextAction(upload: Upload): NextAction {
  if (upload.scraped === 0) return 'research'
  if (upload.personalized < upload.scraped) return 'personalize'
  if (upload.scraped < upload.row_count) return 'research'
  return 'export'
}

export const NEXT_ACTION_LABEL: Record<NextAction, string> = {
  research: 'Research',
  personalize: 'Personalize',
  export: 'Download',
}

/** The four pipeline steps for one upload, as Stepper input. */
export function uploadSteps(upload: Upload) {
  const next = nextAction(upload)
  const state = (count: number, of: number, step: NextAction): StepState => {
    if (of > 0 && count >= of) return 'done'
    if (next === step) return 'current'
    return count > 0 ? 'partial' : 'upcoming'
  }
  return [
    { label: 'Import', description: `${upload.row_count} rows`, state: 'done' as StepState },
    {
      label: 'Research',
      description: `${upload.scraped} of ${upload.row_count}`,
      state: state(upload.scraped, upload.row_count, 'research'),
    },
    {
      label: 'Personalize',
      description: upload.scraped ? `${upload.personalized} of ${upload.scraped} researched` : 'Needs research',
      state:
        upload.scraped > 0 && upload.personalized >= upload.scraped && next !== 'personalize'
          ? upload.scraped >= upload.row_count
            ? ('done' as StepState)
            : ('partial' as StepState)
          : state(upload.personalized, 0, 'personalize'),
    },
    {
      label: 'Download',
      description: 'CSV, original columns first',
      state: (next === 'export' ? 'current' : 'upcoming') as StepState,
    },
  ]
}

/* --------------------------------------------------------------- readiness */

export interface Check {
  key: 'claude' | 'offer' | 'sources' | 'template'
  label: string
  ok: boolean
  detail: string
  href: string
  cta: string
  /** Which phases this blocks. */
  blocks: Job['type'][]
}

export interface Readiness {
  loading: boolean
  ai: AiStatus | null
  settings: SettingsResponse | null
  templates: Template[]
  checks: Check[]
  reload: () => Promise<void>
  /** Checks that would make a job of this type fail before it starts. */
  blockersFor: (phase: Job['type'], channel?: Channel) => Check[]
}

/** Everything that has to be true before a job can do useful work. */
export function useReadiness(): Readiness {
  const [ai, setAi] = useState<AiStatus | null>(null)
  const [settings, setSettings] = useState<SettingsResponse | null>(null)
  const [templates, setTemplates] = useState<Template[]>([])
  const [loading, setLoading] = useState(true)

  const reload = useCallback(async () => {
    const [status, config, list] = await Promise.all([
      api.get<AiStatus>('/settings/ai/status').catch(() => null),
      api.get<SettingsResponse>('/settings').catch(() => null),
      api.get<Template[]>('/templates').catch(() => [] as Template[]),
    ])
    setAi(status)
    setSettings(config)
    setTemplates(list)
    setLoading(false)
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  const activeChannels = new Set(templates.filter((t) => t.is_active).map((t) => t.channel))

  const checks: Check[] = [
    {
      key: 'claude',
      label: 'Connect Claude',
      ok: !!ai?.connected && !ai?.warning,
      detail: ai?.warning
        ? ai.warning
        : ai?.connected
          ? `Connected via ${ai.mode === 'claude_code' ? 'your subscription' : ai.mode === 'api_key' ? 'API key' : 'Console sign-in'}.`
          : 'Personalization runs every row through Claude.',
      href: '/settings#claude',
      cta: ai?.warning ? 'Fix' : 'Connect',
      blocks: ['personalize'],
    },
    {
      key: 'offer',
      label: 'Describe what you sell',
      ok: !!settings?.settings.offer_context.trim(),
      detail: 'Stage 2 uses it to judge whether an angle is relevant, not merely true.',
      href: '/settings#offer',
      cta: 'Write it',
      blocks: ['personalize'],
    },
    {
      key: 'sources',
      label: 'Enable research sources',
      ok: (settings?.settings.enabled_sources.length ?? 0) > 0,
      detail: settings?.settings.enabled_sources.length
        ? `${settings.settings.enabled_sources.length} enabled.`
        : 'Pick where research comes from: websites, news, LinkedIn.',
      href: '/settings#research',
      cta: 'Choose',
      blocks: ['scrape'],
    },
    {
      key: 'template',
      label: 'Set up a message template',
      ok: activeChannels.size > 0,
      detail: activeChannels.size
        ? `Active for ${CHANNELS.filter((c) => activeChannels.has(c.key))
            .map((c) => c.label)
            .join(', ')}.`
        : 'The shape and voice of the final message.',
      href: '/templates',
      cta: 'Create',
      blocks: ['personalize'],
    },
  ]

  function blockersFor(phase: Job['type'], channel?: Channel): Check[] {
    const blockers = checks.filter((c) => !c.ok && c.blocks.includes(phase) && c.key !== 'template')
    if (phase === 'personalize' && channel && !activeChannels.has(channel)) {
      const label = CHANNELS.find((c) => c.key === channel)?.label ?? channel
      blockers.push({
        key: 'template',
        label: `No active ${label} template`,
        ok: false,
        detail: 'Create one, or pick a channel that has one.',
        href: `/templates?channel=${channel}`,
        cta: 'Create',
        blocks: ['personalize'],
      })
    }
    return blockers
  }

  return { loading, ai, settings, templates, checks, reload, blockersFor }
}
