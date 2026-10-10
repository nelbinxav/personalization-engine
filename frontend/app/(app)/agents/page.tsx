'use client'

import { History, Plus, Save, Trash2, Undo2 } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { AgentChat } from '@/components/agent-chat'
import { AgentTry } from '@/components/agent-try'
import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  Field,
  Input,
  PageHeader,
  Spinner,
  Textarea,
  cn,
  toast,
} from '@/components/ui'
import { api } from '@/lib/api'
import type { Agent, AgentProfile } from '@/lib/types'
import { timeAgo } from '@/lib/workflow'

const EMPTY: AgentProfile = {
  offer: '',
  what_we_do: '',
  icp: '',
  proof_points: [],
  voice: '',
  sample_messages: [],
  objections: [],
  qualification: '',
  booking_link: '',
  never_claim: [],
  relevance_terms: [],
  output_mode: 'full_message',
  compact_research: false,
}

const lines = (items: string[]) => items.join('\n')
const split = (text: string) => text.split('\n')
const clean = (items: string[]) => items.map((i) => i.trim()).filter(Boolean)

/** Fields whose content differs, so the profile can show what a chat turn touched. */
function changedFields(before: AgentProfile, after: AgentProfile): (keyof AgentProfile)[] {
  return (Object.keys(after) as (keyof AgentProfile)[]).filter(
    (k) => JSON.stringify(before[k]) !== JSON.stringify(after[k]),
  )
}

export default function AgentsPage() {
  const [agents, setAgents] = useState<Agent[]>([])
  const [lineage, setLineage] = useState<string | null>(null) // null = a new agent
  const [name, setName] = useState('')
  const [profile, setProfile] = useState<AgentProfile>(EMPTY)
  const [missing, setMissing] = useState<string[]>([])
  const [ready, setReady] = useState(false)
  const [flash, setFlash] = useState<(keyof AgentProfile)[]>([])
  const [dirty, setDirty] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [loaded, setLoaded] = useState(false)
  const [fresh, setFresh] = useState(false) // editing an agent not saved yet
  const [chatKey, setChatKey] = useState(0) // a new key is a new conversation
  const profileRef = useRef(profile)
  profileRef.current = profile
  const flashTimer = useRef<ReturnType<typeof setTimeout> | undefined>(undefined)

  async function load() {
    setAgents(await api.get<Agent[]>('/agents'))
    setLoaded(true)
  }

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [])

  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  // One entry per agent: its newest version.
  const lineages = Object.values(
    agents.reduce<Record<string, Agent[]>>((acc, a) => ((acc[a.lineage_id] ||= []).push(a), acc), {}),
  ).map((versions) => versions.sort((a, b) => b.version - a.version))
  const versions = lineage ? (lineages.find((v) => v[0].lineage_id === lineage) ?? []) : []

  function reset(next: { lineage: string | null; name: string; profile: AgentProfile; fresh: boolean }) {
    setFresh(next.fresh)
    setLineage(next.lineage)
    setName(next.name)
    setProfile(next.profile)
    setMissing([])
    setReady(false)
    setFlash([])
    setDirty(false)
    setError(null)
    setChatKey((k) => k + 1)
  }

  function open(next: Agent[]) {
    if (dirty && !confirm('Discard unsaved changes?')) return
    const current = next.find((a) => a.is_active) ?? next[0]
    reset({ lineage: current.lineage_id, name: current.name, profile: current.profile, fresh: false })
  }

  function startNew() {
    if (dirty && !confirm('Discard unsaved changes?')) return
    reset({ lineage: null, name: '', profile: EMPTY, fresh: true })
  }

  function edit<K extends keyof AgentProfile>(key: K, value: AgentProfile[K]) {
    setProfile((p) => ({ ...p, [key]: value }))
    setDirty(true)
  }

  // The trainer's updated profile after a chat turn.
  const onProfile = useCallback((next: AgentProfile, stillMissing: string[], done: boolean) => {
    const changed = changedFields(profileRef.current, next)
    profileRef.current = next
    setProfile(next)
    setMissing(stillMissing)
    setReady(done)
    if (changed.length) {
      setDirty(true)
      setFlash(changed)
      clearTimeout(flashTimer.current)
      flashTimer.current = setTimeout(() => setFlash([]), 5000)
    }
  }, [])

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const saved = await api.post<Agent>('/agents', {
        lineage_id: lineage,
        name: name.trim() || 'Untitled agent',
        profile: {
          ...profile,
          proof_points: clean(profile.proof_points),
          sample_messages: clean(profile.sample_messages),
          never_claim: clean(profile.never_claim),
          relevance_terms: clean(profile.relevance_terms).map((t) => t.toLowerCase()),
          objections: profile.objections.filter((o) => o.objection.trim()),
        },
        activate: true,
      })
      setLineage(saved.lineage_id)
      setFresh(false)
      setDirty(false)
      await load()
      toast.success(`${saved.name} saved as v${saved.version} and active.`)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function activate(version: Agent) {
    try {
      await api.post(`/agents/${version.id}/activate`)
      setName(version.name)
      setProfile(version.profile)
      setDirty(false)
      await load()
      toast.success(`v${version.version} is now active.`)
    } catch (err: any) {
      toast.error(err.message)
    }
  }

  async function remove(version: Agent) {
    if (!confirm(`Delete v${version.version}?`)) return
    try {
      await api.del(`/agents/${version.id}`)
      await load()
    } catch (err: any) {
      toast.error(err.message)
    }
  }

  if (!loaded && !error) return <Spinner />

  const editing = lineage !== null || fresh
  const hl = (key: keyof AgentProfile) =>
    flash.includes(key) ? 'rounded-md ring-2 ring-primary/40 ring-offset-4 ring-offset-card transition' : undefined

  return (
    <>
      <PageHeader
        title="Agents"
        description="One agent per offer. Talk to it: tell it what you sell, who it is for, the proof you may use, your voice and what it must never say. Come back any time to change something."
        action={
          <Button icon={Plus} onClick={startNew}>
            New agent
          </Button>
        }
      />

      {error && <Alert className="mb-6">{error}</Alert>}

      {lineages.length > 0 && (
        <div className="mb-5 flex flex-wrap gap-2">
          {lineages.map((v) => (
            <button
              key={v[0].lineage_id}
              onClick={() => open(v)}
              className={cn(
                'flex items-center gap-2 rounded-full border border-border px-3 py-1.5 text-sm hover:bg-muted/50',
                lineage === v[0].lineage_id && 'border-primary/50 bg-muted/60',
              )}
            >
              <span className="font-medium">{v[0].name}</span>
              <span className="text-xs tabular-nums text-muted-foreground">v{v[0].version}</span>
            </button>
          ))}
        </div>
      )}

      {!editing ? (
        <Card>
          <p className="text-sm text-muted-foreground">Pick an agent, or start a new one.</p>
        </Card>
      ) : (
        <div className="space-y-6">
          <div className="grid h-[calc(100vh-17rem)] min-h-[34rem] gap-6 lg:grid-cols-5">
            <div className="min-h-0 lg:col-span-3">
              <AgentChat
                key={chatKey}
                profile={profile}
                onProfile={onProfile}
                storageKey={lineage ? `agent-chat:${lineage}` : null}
                greet={fresh}
              />
            </div>

            <Card className="flex min-h-0 flex-col lg:col-span-2">
              <CardHeader
                title="Profile"
                description={
                  ready
                    ? 'Ready to save. Edit anything directly, or just tell the chat.'
                    : missing.length
                      ? `Still thin: ${missing.join(', ')}.`
                      : 'Fills in as you talk. Edit anything directly. This is what personalization reads.'
                }
              />
              <div className="-mx-1 min-h-0 flex-1 space-y-4 overflow-y-auto px-1 py-1">
                <Field id="a-name" label="Name">
                  <Input
                    id="a-name"
                    value={name}
                    placeholder="Databricks cost"
                    onChange={(e) => (setName(e.target.value), setDirty(true))}
                  />
                </Field>
                <Field id="a-offer" label="What we sell" className={hl('offer')}>
                  <Textarea id="a-offer" className="h-20" value={profile.offer} onChange={(e) => edit('offer', e.target.value)} />
                </Field>
                <Field id="a-do" label="What we do" className={hl('what_we_do')}>
                  <Textarea id="a-do" className="h-20" value={profile.what_we_do} onChange={(e) => edit('what_we_do', e.target.value)} />
                </Field>
                <Field id="a-icp" label="Who it is for" className={hl('icp')}>
                  <Textarea id="a-icp" className="h-20" value={profile.icp} onChange={(e) => edit('icp', e.target.value)} />
                </Field>
                <Field id="a-proof" label="Proof we may use" hint="One per line. Only facts you can stand behind." className={hl('proof_points')}>
                  <Textarea id="a-proof" className="h-24" value={lines(profile.proof_points)} onChange={(e) => edit('proof_points', split(e.target.value))} />
                </Field>
                <Field id="a-voice" label="Voice" className={hl('voice')}>
                  <Textarea id="a-voice" className="h-20" value={profile.voice} onChange={(e) => edit('voice', e.target.value)} />
                </Field>
                <Field id="a-samples" label="Sample messages" hint="Separate with a line containing only ---." className={hl('sample_messages')}>
                  <Textarea
                    id="a-samples"
                    className="h-28"
                    value={profile.sample_messages.join('\n---\n')}
                    onChange={(e) => edit('sample_messages', e.target.value.split(/\n---\n/))}
                  />
                </Field>
                <Field id="a-qual" label="How we qualify" className={hl('qualification')}>
                  <Textarea id="a-qual" className="h-20" value={profile.qualification} onChange={(e) => edit('qualification', e.target.value)} />
                </Field>
                <Field id="a-link" label="Booking link" className={hl('booking_link')}>
                  <Input id="a-link" value={profile.booking_link} onChange={(e) => edit('booking_link', e.target.value)} />
                </Field>
                <Field id="a-never" label="Never claim or say" hint="One per line." className={hl('never_claim')}>
                  <Textarea id="a-never" className="h-24" value={lines(profile.never_claim)} onChange={(e) => edit('never_claim', split(e.target.value))} />
                </Field>

                <Field label="Objections" className={hl('objections')}>
                  <div className="space-y-2">
                    {profile.objections.map((o, i) => (
                      <div key={i} className="flex gap-2">
                        <Input
                          placeholder="Objection"
                          value={o.objection}
                          onChange={(e) => edit('objections', profile.objections.map((x, j) => (j === i ? { ...x, objection: e.target.value } : x)))}
                        />
                        <Input
                          placeholder="Our response"
                          value={o.response}
                          onChange={(e) => edit('objections', profile.objections.map((x, j) => (j === i ? { ...x, response: e.target.value } : x)))}
                        />
                        <Button variant="ghost" icon={Trash2} aria-label="Remove" onClick={() => edit('objections', profile.objections.filter((_, j) => j !== i))} />
                      </div>
                    ))}
                    <Button size="sm" variant="ghost" icon={Plus} onClick={() => edit('objections', [...profile.objections, { objection: '', response: '' }])}>
                      Add objection
                    </Button>
                  </div>
                </Field>

                <div className="space-y-3 border-t border-border pt-4">
                  <p className="text-sm font-medium">How it writes and researches</p>
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={profile.output_mode === 'full_message'}
                      onChange={(e) => edit('output_mode', e.target.checked ? 'full_message' : 'personalized_line')}
                    />
                    <span>
                      Also write the full message from the template
                      <span className="block text-xs text-muted-foreground">
                        Off: only the personal statement is written, in its own column, and your template can live in
                        the sending tool. A row with no good evidence gets a blank statement, never filler.
                      </span>
                    </span>
                  </label>
                  <label className="flex items-start gap-2 text-sm">
                    <input
                      type="checkbox"
                      className="mt-1"
                      checked={profile.compact_research}
                      onChange={(e) => edit('compact_research', e.target.checked)}
                    />
                    <span>
                      Compact research
                      <span className="block text-xs text-muted-foreground">
                        Reads about 3,000 characters per source (its most relevant paragraphs) and stops rows whose
                        only evidence is funding, awards, earnings, partnerships or certifications. Costs fewer tokens.
                      </span>
                    </span>
                  </label>
                  <Field
                    id="a-terms"
                    label="Relevant words"
                    hint="One per line: the platforms, costs and changes this offer cares about. The chat suggests them. Used by compact research to decide which paragraphs to keep."
                    className={hl('relevance_terms')}
                  >
                    <Textarea id="a-terms" className="h-24" value={lines(profile.relevance_terms)} onChange={(e) => edit('relevance_terms', split(e.target.value))} />
                  </Field>
                </div>
              </div>

              <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-border pt-4">
                <Button onClick={save} loading={busy} disabled={!dirty || !profile.offer.trim()} icon={Save}>
                  Save as v{(versions[0]?.version ?? 0) + 1}
                </Button>
                {dirty && lineage && (
                  <Button variant="ghost" icon={Undo2} onClick={() => open(versions)}>
                    Discard
                  </Button>
                )}
                {dirty && <span className="text-xs text-warning">Unsaved changes</span>}
              </div>
            </Card>
          </div>

          <AgentTry profile={profile} />

          {versions.length > 0 && (
            <Card>
              <CardHeader icon={History} title="Versions" description="Saving never overwrites an old version." />
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
                      <span className="flex gap-1">
                        <Button size="sm" variant="ghost" onClick={() => activate(version)}>
                          Make active
                        </Button>
                        <Button size="sm" variant="ghost" icon={Trash2} aria-label="Delete" onClick={() => remove(version)} />
                      </span>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          )}
        </div>
      )}
    </>
  )
}
