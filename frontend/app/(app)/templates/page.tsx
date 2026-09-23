'use client'

import { useEffect, useState } from 'react'

import { Alert, Badge, Button, Card, Input, PageHeader, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import type { Channel, Template } from '@/lib/types'

const CHANNELS: { key: Channel; label: string; note: string }[] = [
  { key: 'linkedin', label: 'LinkedIn', note: 'Connection notes are capped at 300 characters.' },
  { key: 'email', label: 'Email', note: 'Needs a subject line.' },
  { key: 'whatsapp', label: 'WhatsApp', note: 'Keep it short and conversational.' },
]

export default function TemplatesPage() {
  const [templates, setTemplates] = useState<Template[]>([])
  const [channel, setChannel] = useState<Channel>('email')
  const [name, setName] = useState('')
  const [body, setBody] = useState('')
  const [maxChars, setMaxChars] = useState('')
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)

  async function load() {
    setTemplates(await api.get<Template[]>('/templates'))
    setLoaded(true)
  }

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    if (dirty) return
    const active = templates.find((t) => t.channel === channel && t.is_active)
    if (active) {
      setName(active.name)
      setBody(active.body)
      setMaxChars(active.constraints.max_chars ? String(active.constraints.max_chars) : '')
    }
  }, [channel, templates, dirty])

  const versions = templates.filter((t) => t.channel === channel)
  const active = versions.find((t) => t.is_active)
  const meta = CHANNELS.find((c) => c.key === channel)!

  async function save() {
    setBusy(true)
    setError(null)
    try {
      await api.post('/templates', {
        channel,
        name: name || `${channel} template`,
        body,
        constraints: {
          max_chars: maxChars ? Number(maxChars) : null,
          has_subject: channel === 'email',
          subject_max_chars: channel === 'email' ? 78 : null,
        },
        activate: true,
      })
      setDirty(false)
      await load()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!loaded && !error) return <Spinner />

  return (
    <>
      <PageHeader
        title="Templates"
        description="The shape and voice of the final message. Leave {{identity.first_name}} placeholders in place - the model fills them, and keeping them literal is what lets the prompt prefix stay cached across every row."
      />

      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      <div className="mb-6 flex flex-wrap gap-2">
        {CHANNELS.map((c) => (
          <Button
            key={c.key}
            size="sm"
            variant={channel === c.key ? 'primary' : 'secondary'}
            onClick={() => {
              if (dirty && !confirm('Discard unsaved changes?')) return
              setDirty(false)
              setChannel(c.key)
            }}
          >
            {c.label}
          </Button>
        ))}
      </div>

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="mb-4 grid gap-4 sm:grid-cols-3">
            <div className="sm:col-span-2">
              <label className="label">Name</label>
              <Input
                value={name}
                onChange={(e) => {
                  setName(e.target.value)
                  setDirty(true)
                }}
              />
            </div>
            <div>
              <label className="label">Max characters</label>
              <Input
                type="number"
                value={maxChars}
                onChange={(e) => {
                  setMaxChars(e.target.value)
                  setDirty(true)
                }}
              />
            </div>
          </div>

          <label className="label">Template</label>
          <textarea
            className="input h-80 font-mono text-xs leading-relaxed"
            value={body}
            onChange={(e) => {
              setBody(e.target.value)
              setDirty(true)
            }}
          />
          <p className="hint">{meta.note} Generated messages are checked against the limit, with one automatic rewrite if they exceed it.</p>

          <div className="mt-4 flex items-center gap-3">
            <Button onClick={save} disabled={busy || !dirty}>
              {busy ? 'Saving...' : 'Save as new version'}
            </Button>
            {active && <Badge tone="info">active: v{active.version}</Badge>}
            {dirty && <span className="text-xs text-warning">Unsaved changes</span>}
          </div>
        </Card>

        <Card>
          <h3 className="mb-3 text-sm font-semibold">Versions</h3>
          {versions.length === 0 && <p className="text-sm text-muted-foreground">None yet.</p>}
          <ul className="space-y-2 text-sm">
            {versions.map((version) => (
              <li key={version.id} className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">
                  v{version.version} · {version.name}
                </span>
                {version.is_active ? (
                  <Badge tone="success">active</Badge>
                ) : (
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={async () => {
                      await api.post(`/templates/${version.id}/activate`)
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
      </div>
    </>
  )
}
