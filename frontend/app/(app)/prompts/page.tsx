'use client'

import { ChevronRight, FlaskConical, History, Save, Undo2 } from 'lucide-react'
import { useEffect, useRef, useState } from 'react'

import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  Field,
  Input,
  PageHeader,
  Segmented,
  Select,
  Spinner,
  cn,
  toast,
} from '@/components/ui'
import { api } from '@/lib/api'
import type { Channel, PreviewResult, Prompt, Upload } from '@/lib/types'
import { CHANNELS, money, timeAgo } from '@/lib/workflow'

const STAGE_INFO: Record<number, { name: string; job: string }> = {
  1: { name: 'Dossier', job: 'Scraped text → facts, each tagged with its source.' },
  2: { name: 'Angle', job: 'Facts + what you sell → 1–2 angles, each citing a fact.' },
  3: { name: 'Draft', job: 'Angle + template → the message.' },
}

const PLACEHOLDERS: { token: string; help: string; stages?: number[]; perRow?: boolean }[] = [
  { token: '{{offer_context}}', help: 'What you sell, from Settings. Same for every row, so it stays cached.' },
  { token: '{{template}}', help: 'The channel template.', stages: [3] },
  { token: '{{constraints}}', help: 'The channel character limits.', stages: [3] },
  { token: '{{identity.first_name}}', help: 'Per prospect. Turns caching off for this stage.', perRow: true },
  { token: '{{raw.Any Column}}', help: 'Per prospect: any original sheet column.', perRow: true },
]

// Mirrors backend `chain._split_stable`: per-prospect data in the prompt body
// makes the cached prefix differ on every row.
const PER_ROW = /\{\{\s*(research|dossier|angles|identity\.\w+|raw\.[^}]+)\s*\}\}/

export default function PromptsPage() {
  const [stages, setStages] = useState<{ stage: number; label: string }[]>([])
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [stage, setStage] = useState(1)
  const [name, setName] = useState('')
  const [body, setBody] = useState('')
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const editor = useRef<HTMLTextAreaElement>(null)

  const [uploads, setUploads] = useState<Upload[]>([])
  const [uploadId, setUploadId] = useState('')
  const [channel, setChannel] = useState<Channel>('email')
  const [preview, setPreview] = useState<PreviewResult | null>(null)
  const [previewing, setPreviewing] = useState(false)

  async function load() {
    const [stageList, promptList, uploadList] = await Promise.all([
      api.get<{ stage: number; label: string }[]>('/prompts/stages'),
      api.get<Prompt[]>('/prompts'),
      api.get<Upload[]>('/uploads').catch(() => [] as Upload[]),
    ])
    setStages(stageList)
    setPrompts(promptList)
    const researched = uploadList.filter((u) => u.scraped > 0)
    setUploads(researched)
    if (researched.length) setUploadId((current) => current || researched[0].id)
  }

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [])

  // Load the active version whenever the stage changes, unless there are
  // unsaved edits that would be silently thrown away.
  useEffect(() => {
    if (dirty) return
    const active = prompts.find((p) => p.stage === stage && p.is_active)
    setName(active?.name ?? '')
    setBody(active?.body ?? '')
  }, [stage, prompts, dirty])

  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const versions = prompts.filter((p) => p.stage === stage).sort((a, b) => b.version - a.version)
  const active = versions.find((p) => p.is_active)
  const cacheBreaker = PER_ROW.test(body)

  function switchStage(next: number) {
    if (next === stage) return
    if (dirty && !confirm('Discard unsaved changes to this prompt?')) return
    setDirty(false)
    setStage(next)
  }

  function insert(token: string) {
    const el = editor.current
    const start = el?.selectionStart ?? body.length
    const end = el?.selectionEnd ?? body.length
    setBody(body.slice(0, start) + token + body.slice(end))
    setDirty(true)
    requestAnimationFrame(() => {
      el?.focus()
      el?.setSelectionRange(start + token.length, start + token.length)
    })
  }

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.post('/prompts', { stage, name: name || `Stage ${stage} prompt`, body, activate: true })
      setDirty(false)
      await load()
      toast.success(`Saved stage ${stage} as a new version and made it active.`)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function activate(version: Prompt) {
    try {
      await api.post(`/prompts/${version.id}/activate`)
      setDirty(false)
      await load()
      toast.success(`v${version.version} is now active.`)
    } catch (err: any) {
      toast.error(err.message)
    }
  }

  async function runPreview() {
    setPreviewing(true)
    setError(null)
    setPreview(null)
    try {
      setPreview(
        await api.post<PreviewResult>('/preview', {
          upload_id: uploadId,
          channel,
          // Send the unsaved body so a prompt can be tried before committing
          // a new version.
          prompt_bodies: { [String(stage)]: body },
        }),
      )
    } catch (err: any) {
      setError(err.message)
    } finally {
      setPreviewing(false)
    }
  }

  if (!stages.length && !error) return <Spinner />

  return (
    <>
      <PageHeader
        title="Prompts"
        description="Three stages run in a chain for every row. Saving never overwrites: it creates a new version and activates it, so any past download can be traced to the exact prompt behind it."
      />

      {error && <Alert className="mb-6">{error}</Alert>}

      {/* The chain, doubling as the stage switcher. */}
      <div className="mb-6 grid gap-2 md:grid-cols-3" role="tablist" aria-label="Stage">
        {stages.map((s, i) => {
          const info = STAGE_INFO[s.stage]
          const selected = s.stage === stage
          return (
            <div key={s.stage} className="relative flex items-center">
              <button
                role="tab"
                aria-selected={selected}
                onClick={() => switchStage(s.stage)}
                className={cn(
                  'flex-1 rounded-lg border p-3.5 text-left transition-colors',
                  selected
                    ? 'border-primary/60 bg-primary/[0.06] ring-1 ring-primary/30'
                    : 'border-border bg-card hover:border-border-strong',
                )}
              >
                <span className="flex items-center gap-2 text-sm font-medium">
                  <span
                    className={cn(
                      'flex h-5 w-5 items-center justify-center rounded-full text-[11px] font-semibold',
                      selected ? 'bg-primary text-primary-foreground' : 'bg-muted text-muted-foreground',
                    )}
                  >
                    {s.stage}
                  </span>
                  {info?.name ?? s.label}
                </span>
                <span className="mt-1 block text-xs text-muted-foreground">{info?.job ?? s.label}</span>
              </button>
              {i < stages.length - 1 && (
                <ChevronRight className="absolute -right-2.5 z-10 hidden h-4 w-4 rounded-full bg-background text-muted-foreground md:block" />
              )}
            </div>
          )
        })}
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-6 lg:col-span-3">
          <Card>
            <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
              <Field id="prompt-name" label="Name" className="min-w-56 flex-1">
                <Input
                  id="prompt-name"
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value)
                    setDirty(true)
                  }}
                />
              </Field>
              {active && (
                <Badge tone="success" dot className="mb-2.5">
                  v{active.version} active
                </Badge>
              )}
            </div>

            <Field id="prompt-body" label="Prompt" aside={<span className="text-xs tabular-nums text-muted-foreground">{body.length} chars</span>}>
              <textarea
                id="prompt-body"
                ref={editor}
                className="input h-[26rem] resize-y font-mono text-xs leading-relaxed"
                value={body}
                spellCheck={false}
                onChange={(e) => {
                  setBody(e.target.value)
                  setDirty(true)
                }}
              />
            </Field>

            {cacheBreaker && (
              <Alert tone="warning" className="mt-3" title="This prompt will not be cached">
                It uses per-prospect data, so the prefix differs on every row and each call pays full price.
                Per-prospect data already arrives in the user turn; the prompt body only needs the instructions.
              </Alert>
            )}

            <div className="mt-4 flex flex-wrap items-center gap-2">
              <Button onClick={save} loading={busy} disabled={!dirty} icon={Save}>
                Save as v{(versions[0]?.version ?? 0) + 1}
              </Button>
              {dirty && (
                <Button variant="ghost" icon={Undo2} onClick={() => setDirty(false)}>
                  Discard
                </Button>
              )}
              {dirty && <span className="text-xs text-warning">Unsaved changes</span>}
            </div>
          </Card>

          <Card>
            <CardHeader title="Placeholders" description="Click one to insert it at the cursor." />
            <ul className="space-y-2">
              {PLACEHOLDERS.filter((p) => !p.stages || p.stages.includes(stage)).map((p) => (
                <li key={p.token} className="flex flex-wrap items-center gap-x-3 gap-y-1">
                  <button
                    onClick={() => insert(p.token)}
                    className={cn(
                      'rounded-md border px-2 py-1 font-mono text-xs transition-colors',
                      p.perRow
                        ? 'border-warning/30 text-warning hover:bg-warning/10'
                        : 'border-primary/30 text-primary hover:bg-primary/10',
                    )}
                  >
                    {p.token}
                  </button>
                  <span className="text-xs text-muted-foreground">{p.help}</span>
                </li>
              ))}
            </ul>
          </Card>

          {versions.length > 1 && (
            <Card>
              <CardHeader icon={History} title="Versions" />
              <ul className="-mx-2 space-y-0.5 text-sm">
                {versions.map((version) => (
                  <li key={version.id} className="flex items-center justify-between gap-3 rounded-md px-2 py-1.5 hover:bg-muted/50">
                    <span className="min-w-0 truncate">
                      <span className="font-medium tabular-nums">v{version.version}</span>
                      <span className="text-muted-foreground"> · {version.name} · {timeAgo(version.created_at)}</span>
                    </span>
                    {version.is_active ? (
                      <Badge tone="success">active</Badge>
                    ) : (
                      <Button size="sm" variant="ghost" onClick={() => activate(version)}>
                        Make active
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>

        <div className="lg:col-span-2">
          <div className="space-y-6 lg:sticky lg:top-8">
            <Card>
              <CardHeader
                icon={FlaskConical}
                title="Try it on a real row"
                description="Runs all three stages on the first researched row, using the prompt on the left, saved or not."
              />

              {uploads.length === 0 ? (
                <Alert tone="neutral">Research at least one row of an upload first. Previews need real research.</Alert>
              ) : (
                <div className="space-y-3">
                  <Field id="preview-upload" label="Upload">
                    <Select id="preview-upload" value={uploadId} onChange={(e) => setUploadId(e.target.value)}>
                      {uploads.map((upload) => (
                        <option key={upload.id} value={upload.id}>
                          {upload.name} ({upload.scraped} researched)
                        </option>
                      ))}
                    </Select>
                  </Field>
                  <Field label="Channel">
                    <Segmented
                      label="Channel"
                      size="sm"
                      value={channel}
                      onChange={setChannel}
                      options={CHANNELS.map((c) => ({ value: c.key, label: c.label }))}
                    />
                  </Field>
                  <Button onClick={runPreview} loading={previewing} disabled={!uploadId} className="w-full">
                    {previewing ? 'Running the chain' : 'Run preview'}
                  </Button>
                  <p className="text-center text-xs text-muted-foreground">Makes three real Claude calls.</p>
                </div>
              )}
            </Card>

            {previewing && (
              <Card className="space-y-3">
                <div className="h-4 w-1/3 animate-pulse rounded bg-muted" />
                <div className="h-20 animate-pulse rounded bg-muted" />
                <div className="h-32 animate-pulse rounded bg-muted" />
              </Card>
            )}

            {preview && <PreviewCard preview={preview} />}
          </div>
        </div>
      </div>
    </>
  )
}

function PreviewCard({ preview }: { preview: PreviewResult }) {
  return (
    <Card className="animate-in fade-in">
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="font-medium">{preview.prospect.name}</p>
          {preview.prospect.company && <p className="text-xs text-muted-foreground">{preview.prospect.company}</p>}
        </div>
        <span className="text-xs tabular-nums text-muted-foreground">{money(preview.cost_usd, 4)}</span>
      </div>

      {preview.warnings.map((warning) => (
        <Alert key={warning} tone="warning" className="mb-3">
          {warning}
        </Alert>
      ))}

      <ol className="space-y-4">
        <li>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">1 · Dossier</p>
          {preview.dossier ? (
            <details className="rounded-lg border border-border bg-muted/40 p-3 text-xs">
              <summary className="cursor-pointer text-muted-foreground">
                {preview.dossier.facts.length} facts, {preview.dossier.recent_events.length} recent events
              </summary>
              <p className="mt-2 text-foreground/90">{preview.dossier.summary}</p>
              <ul className="mt-2 space-y-1.5 text-muted-foreground">
                {[...preview.dossier.facts, ...preview.dossier.recent_events].map((fact, i) => (
                  <li key={i}>
                    {fact.text} <Badge className="ml-1">{fact.source_key}</Badge>
                  </li>
                ))}
              </ul>
            </details>
          ) : (
            <p className="text-xs text-muted-foreground">No dossier.</p>
          )}
        </li>

        <li>
          <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">2 · Angle</p>
          {preview.thin_context ? (
            <Alert tone="warning" title="Needs review: not enough to personalize">
              {preview.reason}
            </Alert>
          ) : preview.angles.length > 0 ? (
            <div className="rounded-lg border border-border bg-muted/40 p-3 text-xs">
              <p className="font-medium text-foreground">{preview.angles[0].angle}</p>
              <p className="mt-1.5 text-muted-foreground">
                “{preview.angles[0].evidence}” <Badge className="ml-1">{preview.angles[0].source_key}</Badge>
              </p>
            </div>
          ) : (
            <p className="text-xs text-muted-foreground">No angle.</p>
          )}
        </li>

        {preview.draft && (
          <li>
            <p className="mb-1.5 text-[11px] font-semibold uppercase tracking-wider text-muted-foreground">3 · Draft</p>
            <div className="rounded-lg border border-border p-3.5">
              {preview.draft.subject && <p className="mb-2 text-sm font-medium">{preview.draft.subject}</p>}
              <p className="whitespace-pre-wrap text-sm leading-relaxed">{preview.draft.body}</p>
              <p className="mt-2 text-xs tabular-nums text-muted-foreground">{preview.draft.body.length} characters</p>
            </div>
            {preview.constraint_warning && (
              <Alert tone="warning" className="mt-3">
                {preview.constraint_warning}
              </Alert>
            )}
          </li>
        )}
      </ol>
    </Card>
  )
}
