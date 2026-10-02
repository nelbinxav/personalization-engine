'use client'

import { History, Save, Undo2 } from 'lucide-react'
import { useSearchParams } from 'next/navigation'
import { Suspense, useEffect, useRef, useState } from 'react'

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
  Spinner,
  toast,
} from '@/components/ui'
import { api } from '@/lib/api'
import type { Channel, Template } from '@/lib/types'
import { CHANNELS, timeAgo } from '@/lib/workflow'

const SUGGESTED_MAX: Record<Channel, string> = { linkedin: '300', email: '', whatsapp: '' }
const TOKENS = ['{{personalization}}', '{{identity.first_name}}', '{{identity.company}}', '{{identity.title}}']

function TemplatesInner() {
  const params = useSearchParams()
  const [templates, setTemplates] = useState<Template[]>([])
  const [channel, setChannel] = useState<Channel>((params.get('channel') as Channel) || 'email')
  const [name, setName] = useState('')
  const [body, setBody] = useState('')
  const [fallbackBody, setFallbackBody] = useState('')
  const [maxChars, setMaxChars] = useState('')
  const [dirty, setDirty] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [loaded, setLoaded] = useState(false)
  const editor = useRef<HTMLTextAreaElement>(null)

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
    setName(active?.name ?? '')
    setBody(active?.body ?? '')
    setFallbackBody(active?.fallback_body ?? '')
    setMaxChars(active ? (active.constraints.max_chars ? String(active.constraints.max_chars) : '') : SUGGESTED_MAX[channel])
  }, [channel, templates, dirty])

  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  const versions = templates.filter((t) => t.channel === channel).sort((a, b) => b.version - a.version)
  const active = versions.find((t) => t.is_active)
  const meta = CHANNELS.find((c) => c.key === channel)!

  function switchChannel(next: Channel) {
    if (next === channel) return
    if (dirty && !confirm('Discard unsaved changes?')) return
    setDirty(false)
    setChannel(next)
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
      await api.post('/templates', {
        channel,
        name: name || `${meta.label} template`,
        body,
        fallback_body: fallbackBody,
        constraints: {
          max_chars: maxChars ? Number(maxChars) : null,
          has_subject: channel === 'email',
          subject_max_chars: channel === 'email' ? 78 : null,
        },
        activate: true,
      })
      setDirty(false)
      await load()
      toast.success(`${meta.label} template saved and active.`)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function activate(version: Template) {
    try {
      await api.post(`/templates/${version.id}/activate`)
      setDirty(false)
      await load()
      toast.success(`v${version.version} is now active.`)
    } catch (err: any) {
      toast.error(err.message)
    }
  }

  if (!loaded && !error) return <Spinner />

  return (
    <>
      <PageHeader
        title="Templates"
        description="The shape and voice of the final message, one per channel. Stage 3 of the chain writes to this template."
      />

      {error && <Alert className="mb-6">{error}</Alert>}

      <Segmented
        label="Channel"
        className="mb-6"
        value={channel}
        onChange={switchChannel}
        options={CHANNELS.map((c) => {
          const has = templates.some((t) => t.channel === c.key && t.is_active)
          return {
            value: c.key,
            label: (
              <>
                {c.label}
                <span
                  className={has ? 'h-1.5 w-1.5 rounded-full bg-success' : 'h-1.5 w-1.5 rounded-full bg-warning'}
                  title={has ? 'Has an active template' : 'No template yet'}
                />
              </>
            ),
          }
        })}
      />

      <div className="grid gap-6 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          {!active && !dirty && (
            <Alert tone="info" className="mb-5" title={`No ${meta.label} template yet`}>
              Personalization jobs for {meta.label} cannot start until one is saved. Write it below.
            </Alert>
          )}

          <div className="mb-4 grid gap-4 sm:grid-cols-3">
            <Field id="tpl-name" label="Name" className="sm:col-span-2">
              <Input
                id="tpl-name"
                value={name}
                placeholder={`${meta.label} template`}
                onChange={(e) => {
                  setName(e.target.value)
                  setDirty(true)
                }}
              />
            </Field>
            <Field id="tpl-max" label="Max characters" aside={<span className="text-xs text-muted-foreground">Optional</span>}>
              <Input
                id="tpl-max"
                type="number"
                min={1}
                placeholder="No limit"
                value={maxChars}
                onChange={(e) => {
                  setMaxChars(e.target.value)
                  setDirty(true)
                }}
              />
            </Field>
          </div>

          <Field
            id="tpl-body"
            label="Template"
            aside={<span className="text-xs tabular-nums text-muted-foreground">{body.length} chars</span>}
            hint={`${meta.note} Generated messages are checked against the limit, with one automatic rewrite if they go over.`}
          >
            <textarea
              id="tpl-body"
              ref={editor}
              className="input h-80 resize-y font-mono text-xs leading-relaxed"
              value={body}
              placeholder={
                channel === 'email'
                  ? 'Hi {{identity.first_name}},\n\n<one line on the angle>\n\n<why it matters to them>\n\n<soft ask>'
                  : 'Hi {{identity.first_name}}, <one line on the angle>. <soft ask>'
              }
              onChange={(e) => {
                setBody(e.target.value)
                setDirty(true)
              }}
            />
          </Field>

          <div className="mt-3 flex flex-wrap items-center gap-2">
            <span className="text-xs text-muted-foreground">Insert:</span>
            {TOKENS.map((token) => (
              <button
                key={token}
                onClick={() => insert(token)}
                className="rounded-md border border-primary/30 px-2 py-0.5 font-mono text-[11px] text-primary transition-colors hover:bg-primary/10"
              >
                {token}
              </button>
            ))}
          </div>
          <p className="hint">
            {'{{personalization}}'} marks the one line the model writes; everything else is sent as written. Leave
            placeholders as they are: they are filled per row, and keeping them literal is what lets the prompt stay
            cached across every row.
          </p>

          <Field
            id="tpl-fallback"
            label="Ask-first copy"
            className="mt-6"
            aside={
              <span className="text-xs tabular-nums text-muted-foreground">
                {fallbackBody.trim() ? `${fallbackBody.length} chars` : 'Optional'}
              </span>
            }
            hint="Sent instead of the template above when the research does not show the prospect has the problem you solve, for example that they use the platform you cut costs on. Being on the list is not evidence, so this copy should ask rather than assume. It can carry its own {{personalization}} line and Subject. Leave it empty to send the template above to every row."
          >
            <textarea
              id="tpl-fallback"
              className="input h-56 resize-y font-mono text-xs leading-relaxed"
              value={fallbackBody}
              placeholder={
                channel === 'email'
                  ? 'Subject: quick question\n\nHi {{firstName|there}},\n\n{{personalization}}\n\n<ask whether they have the problem, before offering anything>'
                  : 'Hi {{firstName|there}},\n\n{{personalization}}\n\n<ask whether they have the problem, before offering anything>'
              }
              onChange={(e) => {
                setFallbackBody(e.target.value)
                setDirty(true)
              }}
            />
          </Field>

          <div className="mt-5 flex flex-wrap items-center gap-2 border-t border-border pt-5">
            <Button onClick={save} loading={busy} disabled={!dirty || !body.trim()} icon={Save}>
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

        <Card className="self-start">
          <CardHeader icon={History} title="Versions" description="Saving never overwrites an old version." />
          {versions.length === 0 && <p className="text-sm text-muted-foreground">None yet.</p>}
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
      </div>
    </>
  )
}

export default function TemplatesPage() {
  return (
    <Suspense fallback={<Spinner />}>
      <TemplatesInner />
    </Suspense>
  )
}
