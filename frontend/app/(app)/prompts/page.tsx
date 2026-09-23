'use client'

import { useEffect, useState } from 'react'

import { Alert, Badge, Button, Card, Input, PageHeader, Select, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import type { Channel, PreviewResult, Prompt, Upload } from '@/lib/types'

const PLACEHOLDER_HELP = [
  ['{{offer_context}}', 'What we sell, from Settings. Same for every row, so it stays cacheable.'],
  ['{{template}}', 'The channel template (stage 3 only).'],
  ['{{constraints}}', 'The channel character limits (stage 3 only).'],
  ['{{identity.first_name}}', 'Per-prospect. Using one here disables prompt caching for that stage.'],
  ['{{raw.Any Column}}', 'Per-prospect. Any original sheet column.'],
]

export default function PromptsPage() {
  const [stages, setStages] = useState<{ stage: number; label: string }[]>([])
  const [prompts, setPrompts] = useState<Prompt[]>([])
  const [stage, setStage] = useState(1)
  const [name, setName] = useState('')
  const [body, setBody] = useState('')
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

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
    setUploads(uploadList)
    if (uploadList.length) setUploadId((current) => current || uploadList[0].id)
  }

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [])

  // Load the active version whenever the stage changes, unless there are
  // unsaved edits that would be silently thrown away.
  useEffect(() => {
    if (dirty) return
    const active = prompts.find((p) => p.stage === stage && p.is_active)
    if (active) {
      setName(active.name)
      setBody(active.body)
    }
  }, [stage, prompts, dirty])

  const versions = prompts.filter((p) => p.stage === stage)
  const active = versions.find((p) => p.is_active)

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.post('/prompts', { stage, name: name || `Stage ${stage} prompt`, body, activate: true })
      setDirty(false)
      await load()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
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
        description="Three chained stages. Saving never overwrites: each save creates a new version and activates it, so any past export can be traced to the exact prompt that produced it."
      />

      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      <div className="mb-6 flex flex-wrap gap-2">
        {stages.map((s) => (
          <Button
            key={s.stage}
            size="sm"
            variant={stage === s.stage ? 'primary' : 'secondary'}
            onClick={() => {
              if (dirty && !confirm('Discard unsaved changes to this prompt?')) return
              setDirty(false)
              setStage(s.stage)
            }}
          >
            {s.label}
          </Button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <Card>
            <div className="mb-4 flex flex-wrap items-end justify-between gap-3">
              <div className="min-w-56 flex-1">
                <label className="label">Name</label>
                <Input
                  value={name}
                  onChange={(e) => {
                    setName(e.target.value)
                    setDirty(true)
                  }}
                />
              </div>
              {active && (
                <Badge tone="info">
                  active: v{active.version}
                </Badge>
              )}
            </div>

            <label className="label">Prompt</label>
            <textarea
              className="input h-96 font-mono text-xs leading-relaxed"
              value={body}
              onChange={(e) => {
                setBody(e.target.value)
                setDirty(true)
              }}
            />

            <div className="mt-4 flex items-center gap-3">
              <Button onClick={save} disabled={busy || !dirty}>
                {busy ? 'Saving...' : 'Save as new version'}
              </Button>
              {dirty && <span className="text-xs text-warning">Unsaved changes</span>}
            </div>
          </Card>

          <Card>
            <h3 className="mb-2 text-sm font-semibold">Placeholders</h3>
            <dl className="space-y-1.5 text-xs">
              {PLACEHOLDER_HELP.map(([token, help]) => (
                <div key={token} className="flex gap-3">
                  <dt className="w-52 shrink-0 font-mono text-primary">{token}</dt>
                  <dd className="text-muted-foreground">{help}</dd>
                </div>
              ))}
            </dl>
          </Card>

          {versions.length > 1 && (
            <Card>
              <h3 className="mb-3 text-sm font-semibold">Version history</h3>
              <ul className="space-y-2 text-sm">
                {versions.map((version) => (
                  <li key={version.id} className="flex items-center justify-between gap-3">
                    <span className="text-muted-foreground">
                      v{version.version} · {version.name} ·{' '}
                      {new Date(version.created_at).toLocaleDateString()}
                    </span>
                    {version.is_active ? (
                      <Badge tone="success">active</Badge>
                    ) : (
                      <Button
                        size="sm"
                        variant="ghost"
                        onClick={async () => {
                          await api.post(`/prompts/${version.id}/activate`)
                          setDirty(false)
                          load()
                        }}
                      >
                        Activate
                      </Button>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>

        <div className="space-y-4 lg:col-span-2">
          <Card>
            <h3 className="text-sm font-semibold">Test on a real row</h3>
            <p className="hint">
              Runs the full chain on the first researched row of an upload using the prompt above,
              saved or not. This calls the API and costs money.
            </p>

            <div className="mt-3 space-y-3">
              <Select value={uploadId} onChange={(e) => setUploadId(e.target.value)}>
                {uploads.length === 0 && <option value="">No uploads</option>}
                {uploads.map((upload) => (
                  <option key={upload.id} value={upload.id}>
                    {upload.name} ({upload.scraped} researched)
                  </option>
                ))}
              </Select>
              <Select value={channel} onChange={(e) => setChannel(e.target.value as Channel)}>
                <option value="email">Email</option>
                <option value="linkedin">LinkedIn</option>
                <option value="whatsapp">WhatsApp</option>
              </Select>
              <Button onClick={runPreview} disabled={previewing || !uploadId} className="w-full">
                {previewing ? 'Running...' : 'Run preview'}
              </Button>
            </div>
          </Card>

          {preview && (
            <Card>
              <div className="mb-3 flex items-center justify-between">
                <h3 className="text-sm font-semibold">{preview.prospect.name}</h3>
                <span className="text-xs text-muted-foreground">
                  ${preview.cost_usd.toFixed(4)}
                </span>
              </div>

              {preview.warnings.map((warning) => (
                <div key={warning} className="mb-3">
                  <Alert tone="warning">{warning}</Alert>
                </div>
              ))}

              {preview.thin_context ? (
                <Alert tone="warning" title="Flagged: not enough to personalize">
                  {preview.reason}
                </Alert>
              ) : (
                <>
                  {preview.angles.length > 0 && (
                    <div className="mb-3 rounded border border-border bg-muted p-3 text-xs">
                      <p className="font-medium">{preview.angles[0].angle}</p>
                      <p className="mt-1 text-muted-foreground">
                        Evidence: {preview.angles[0].evidence}{' '}
                        <Badge>{preview.angles[0].source_key}</Badge>
                      </p>
                    </div>
                  )}
                  {preview.draft && (
                    <div className="rounded border border-border p-3">
                      {preview.draft.subject && (
                        <p className="mb-2 text-sm font-medium">{preview.draft.subject}</p>
                      )}
                      <pre className="whitespace-pre-wrap font-sans text-sm">{preview.draft.body}</pre>
                      <p className="hint">{preview.draft.body.length} characters</p>
                    </div>
                  )}
                  {preview.constraint_warning && (
                    <div className="mt-3">
                      <Alert tone="warning">{preview.constraint_warning}</Alert>
                    </div>
                  )}
                </>
              )}

              {preview.dossier && (
                <details className="mt-3">
                  <summary className="cursor-pointer text-xs text-muted-foreground">
                    Dossier ({preview.dossier.facts.length} facts,{' '}
                    {preview.dossier.recent_events.length} recent)
                  </summary>
                  <div className="mt-2 space-y-1 text-xs text-muted-foreground">
                    <p>{preview.dossier.summary}</p>
                    {[...preview.dossier.facts, ...preview.dossier.recent_events].map((fact, i) => (
                      <p key={i}>
                        · {fact.text} <Badge>{fact.source_key}</Badge>
                      </p>
                    ))}
                  </div>
                </details>
              )}
            </Card>
          )}
        </div>
      </div>
    </>
  )
}
