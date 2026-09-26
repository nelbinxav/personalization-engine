'use client'

import { Bot, Building2, KeyRound, Microscope, RefreshCw, Terminal } from 'lucide-react'
import { useEffect, useState } from 'react'

import {
  Alert,
  Badge,
  Button,
  Card,
  CardHeader,
  CopyButton,
  Field,
  Input,
  PageHeader,
  Select,
  Spinner,
  ToggleChip,
  cn,
  toast,
} from '@/components/ui'
import { api } from '@/lib/api'
import type { AiStatus, SettingsResponse } from '@/lib/types'

const KEY_FIELDS: { name: string; label: string; hint: string }[] = [
  { name: 'jina', label: 'Jina Reader', hint: 'Website content. Optional: works without a key at a lower rate limit.' },
  { name: 'serper', label: 'Serper.dev', hint: 'Google News. Required for the news source.' },
  { name: 'apify', label: 'Apify', hint: 'LinkedIn profile and company pages.' },
  {
    name: 'google_service_account_json',
    label: 'Google service account JSON',
    hint: 'One line of JSON. Share private sheets with this account’s email. Public sheets need nothing.',
  },
]

const SECTIONS = [
  { id: 'claude', label: 'Claude' },
  { id: 'offer', label: 'What you sell' },
  { id: 'research', label: 'Research' },
  { id: 'keys', label: 'Provider keys' },
]

type Mode = AiStatus['mode']

const METHODS: { mode: Mode; title: string; body: string; icon: typeof Bot }[] = [
  {
    mode: 'claude_code',
    title: 'Claude subscription',
    body: 'Pro, Max or Team. No credits; counts against plan usage limits.',
    icon: Bot,
  },
  { mode: 'oauth', title: 'Console sign-in', body: 'Anthropic Console account. Uses API credits.', icon: Building2 },
  { mode: 'api_key', title: 'API key', body: 'A Console key, stored encrypted. Uses API credits.', icon: KeyRound },
]

const LOGIN_COMMAND = 'docker compose exec -it worker claude auth login'

export default function SettingsPage() {
  const [data, setData] = useState<SettingsResponse | null>(null)
  const [ai, setAi] = useState<AiStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const [checking, setChecking] = useState(false)

  const [offer, setOffer] = useState('')
  const [concurrency, setConcurrency] = useState(4)
  const [model, setModel] = useState('claude-opus-5')
  const [enabledSources, setEnabledSources] = useState<string[]>([])
  const [linkedinProvider, setLinkedinProvider] = useState('apify')
  const [keyEdits, setKeyEdits] = useState<Record<string, string>>({})
  // Keys to delete. Explicit, because the API treats "" as "clear": sending a
  // field the operator typed into and then emptied would wipe the stored key.
  const [cleared, setCleared] = useState<string[]>([])

  // Which connection method the operator is looking at; defaults to the live one.
  const [method, setMethod] = useState<Mode | null>(null)
  const [flow, setFlow] = useState<{ flow_id: string; authorize_url: string } | null>(null)
  const [code, setCode] = useState('')
  const [apiKey, setApiKey] = useState('')

  async function load() {
    const [settings, status] = await Promise.all([
      api.get<SettingsResponse>('/settings'),
      api.get<AiStatus>('/settings/ai/status').catch(() => null),
    ])
    setData(settings)
    setAi(status)
    setOffer(settings.settings.offer_context)
    setConcurrency(settings.settings.concurrency)
    setModel(settings.settings.ai.model)
    setEnabledSources(settings.settings.enabled_sources)
    setLinkedinProvider(settings.settings.linkedin_provider)
    setMethod((current) => current ?? status?.mode ?? 'claude_code')
  }

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [])

  const saved = data?.settings
  const dirty =
    !!saved &&
    (offer !== saved.offer_context ||
      concurrency !== saved.concurrency ||
      model !== saved.ai.model ||
      linkedinProvider !== saved.linkedin_provider ||
      [...enabledSources].sort().join() !== [...saved.enabled_sources].sort().join() ||
      Object.values(keyEdits).some(Boolean) ||
      cleared.length > 0)

  useEffect(() => {
    if (!dirty) return
    const warn = (e: BeforeUnloadEvent) => e.preventDefault()
    window.addEventListener('beforeunload', warn)
    return () => window.removeEventListener('beforeunload', warn)
  }, [dirty])

  function discard() {
    if (!saved) return
    setOffer(saved.offer_context)
    setConcurrency(saved.concurrency)
    setModel(saved.ai.model)
    setEnabledSources(saved.enabled_sources)
    setLinkedinProvider(saved.linkedin_provider)
    setKeyEdits({})
    setCleared([])
  }

  async function save() {
    setBusy(true)
    setError(null)
    try {
      const keys: Record<string, string> = Object.fromEntries(Object.entries(keyEdits).filter(([, v]) => v))
      for (const name of cleared) if (!keys[name]) keys[name] = ''
      await api.put('/settings', {
        offer_context: offer,
        concurrency,
        enabled_sources: enabledSources,
        linkedin_provider: linkedinProvider,
        ai: { model },
        provider_keys: Object.keys(keys).length ? keys : undefined,
      })
      setKeyEdits({})
      setCleared([])
      await load()
      toast.success('Settings saved.')
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function run(action: () => Promise<unknown>, success: string) {
    setBusy(true)
    setError(null)
    try {
      await action()
      await load()
      toast.success(success)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function startOauth() {
    setError(null)
    try {
      setFlow(await api.post<{ flow_id: string; authorize_url: string }>('/settings/ai/oauth/start'))
    } catch (err: any) {
      setError(err.message)
    }
  }

  async function completeOauth() {
    if (!flow) return
    await run(async () => {
      await api.post('/settings/ai/oauth/complete', { flow_id: flow.flow_id, code })
      setFlow(null)
      setCode('')
    }, 'Claude connected.')
  }

  async function checkSignIn() {
    setChecking(true)
    await load().catch((err) => setError(err.message))
    setChecking(false)
  }

  if (!data && !error) return <Spinner />

  const liveMode = ai?.mode
  const modeLabel = METHODS.find((m) => m.mode === liveMode)?.title ?? 'Unknown'

  return (
    <>
      <PageHeader title="Settings" description="How Claude is reached, what you sell, and where research comes from." />

      <nav className="-mt-4 mb-8 flex flex-wrap gap-1 border-b border-border" aria-label="Settings sections">
        {SECTIONS.map((s) => (
          <a
            key={s.id}
            href={`#${s.id}`}
            className="-mb-px border-b-2 border-transparent px-3 py-2 text-sm text-muted-foreground transition-colors hover:border-border-strong hover:text-foreground"
          >
            {s.label}
          </a>
        ))}
      </nav>

      {error && <Alert className="mb-6">{error}</Alert>}
      {ai?.warning && (
        <Alert className="mb-6" title="Credential conflict">
          {ai.warning}
        </Alert>
      )}

      <div className="space-y-8 pb-24">
        {/* ---------------------------------------------------------- Claude */}
        <section id="claude" className="scroll-mt-8">
          <Card>
            <CardHeader
              title="Claude connection"
              description="Pick how the chain reaches Claude. Only one method is live at a time."
              action={
                <Badge tone={ai?.warning ? 'danger' : ai?.connected ? 'success' : 'warning'} dot>
                  {modeLabel} · {ai?.connected ? 'connected' : 'not connected'}
                </Badge>
              }
            />

            <div className="grid gap-2 sm:grid-cols-3" role="radiogroup" aria-label="Connection method">
              {METHODS.map((m) => {
                const selected = method === m.mode
                const live = liveMode === m.mode
                return (
                  <button
                    key={m.mode}
                    type="button"
                    role="radio"
                    aria-checked={selected}
                    onClick={() => setMethod(m.mode)}
                    className={cn(
                      'relative flex flex-col items-start gap-2 rounded-lg border p-3.5 text-left transition-colors',
                      selected
                        ? 'border-primary/60 bg-primary/[0.06] ring-1 ring-primary/30'
                        : 'border-border hover:border-border-strong hover:bg-muted/40',
                    )}
                  >
                    <span className="flex w-full items-center justify-between">
                      <m.icon className={cn('h-4 w-4', selected ? 'text-primary' : 'text-muted-foreground')} />
                      {live && (
                        <Badge tone={ai?.connected ? 'success' : 'warning'} className="text-[10px]">
                          In use
                        </Badge>
                      )}
                    </span>
                    <span className="text-sm font-medium">{m.title}</span>
                    <span className="text-xs text-muted-foreground">{m.body}</span>
                  </button>
                )
              })}
            </div>

            <div className="mt-5 rounded-lg border border-border bg-muted/30 p-4">
              {method === 'claude_code' && (
                <div className="space-y-3 text-sm">
                  <p className="text-muted-foreground">
                    Runs each stage through the official Claude Code tool, signed in with your own account. When a
                    plan limit is hit, the job pauses; resume it once the limit resets.
                  </p>
                  {liveMode === 'claude_code' ? (
                    <>
                      <p className="font-medium">
                        {ai?.connected
                          ? `Signed in${ai.organization ? ` as ${ai.organization}` : ''}${ai.workspace ? ` (${ai.workspace})` : ''}.`
                          : 'Not signed in yet.'}
                      </p>
                      {!ai?.connected && (
                        <ol className="space-y-2">
                          <li>
                            <span className="text-muted-foreground">1.</span> In a terminal, in the project folder, run:
                            <div className="mt-1.5 flex items-center gap-2 rounded-md border border-border bg-background py-1 pl-3 pr-1">
                              <Terminal className="h-3.5 w-3.5 shrink-0 text-muted-foreground" />
                              <code className="flex-1 overflow-x-auto whitespace-nowrap font-mono text-xs">{LOGIN_COMMAND}</code>
                              <CopyButton text={LOGIN_COMMAND} />
                            </div>
                          </li>
                          <li>
                            <span className="text-muted-foreground">2.</span> Follow Claude’s sign-in steps there, then
                            check below.
                          </li>
                        </ol>
                      )}
                      <Button variant="secondary" icon={RefreshCw} onClick={checkSignIn} loading={checking}>
                        Check sign-in
                      </Button>
                    </>
                  ) : (
                    <>
                      <Button
                        onClick={() => run(() => api.put('/settings', { ai: { mode: 'claude_code' } }), 'Now using your Claude subscription.')}
                        loading={busy}
                        disabled={!ai?.claude_code_installed}
                      >
                        Use my Claude subscription
                      </Button>
                      {ai && !ai.claude_code_installed && (
                        <p className="hint">Claude Code is not installed in the container. Rebuild the image.</p>
                      )}
                    </>
                  )}
                </div>
              )}

              {method === 'oauth' && (
                <div className="space-y-3 text-sm">
                  {!ai?.ant_installed && (
                    <Alert tone="warning">
                      The <code className="kbd">ant</code> CLI is not in the API container, so Console sign-in is
                      unavailable. Rebuild the image, or use an API key.
                    </Alert>
                  )}
                  {liveMode === 'oauth' && ai?.connected && (
                    <p className="text-muted-foreground">
                      {ai.organization && `Org: ${ai.organization}. `}
                      {ai.workspace && `Workspace: ${ai.workspace}. `}
                      The token refreshes automatically.
                    </p>
                  )}
                  {!flow ? (
                    <div className="flex flex-wrap gap-2">
                      <Button onClick={startOauth} disabled={!ai?.ant_installed || busy}>
                        {ai?.connected && liveMode === 'oauth' ? 'Reconnect' : 'Connect with Console'}
                      </Button>
                      {ai?.connected && liveMode === 'oauth' && (
                        <Button
                          variant="outline"
                          disabled={busy}
                          onClick={() => run(() => api.post('/settings/ai/oauth/disconnect'), 'Disconnected.')}
                        >
                          Disconnect
                        </Button>
                      )}
                    </div>
                  ) : (
                    <ol className="space-y-3">
                      <li>
                        <span className="text-muted-foreground">1.</span>{' '}
                        <a href={flow.authorize_url} target="_blank" rel="noreferrer" className="link">
                          Open the authorization page
                        </a>{' '}
                        and approve access.
                      </li>
                      <li>
                        <span className="text-muted-foreground">2.</span> Paste the code it gives you:
                        <div className="mt-1.5 flex flex-wrap gap-2">
                          <Input
                            value={code}
                            onChange={(e) => setCode(e.target.value)}
                            placeholder="Authorization code"
                            className="max-w-sm flex-1"
                            aria-label="Authorization code"
                          />
                          <Button onClick={completeOauth} loading={busy} disabled={!code}>
                            Finish
                          </Button>
                          <Button variant="ghost" onClick={() => setFlow(null)}>
                            Cancel
                          </Button>
                        </div>
                        <p className="hint">This attempt expires after 15 minutes.</p>
                      </li>
                    </ol>
                  )}
                  {liveMode === 'claude_code' && (
                    <p className="hint">Connecting here switches away from your subscription.</p>
                  )}
                </div>
              )}

              {method === 'api_key' && (
                <Field
                  id="api-key"
                  label="Anthropic API key"
                  hint="Stored encrypted and picked up by the worker without a restart. Saving one makes API key the live method."
                >
                  <div className="flex flex-wrap gap-2">
                    <Input
                      id="api-key"
                      type="password"
                      autoComplete="off"
                      placeholder={liveMode === 'api_key' && ai?.connected ? 'A key is set. Paste to replace it.' : 'sk-ant-…'}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      className="max-w-md flex-1"
                    />
                    <Button
                      onClick={() =>
                        run(async () => {
                          await api.put('/settings/ai/api-key', { api_key: apiKey })
                          setApiKey('')
                        }, 'API key saved and in use.')
                      }
                      loading={busy}
                      disabled={!apiKey}
                    >
                      Save & use
                    </Button>
                  </div>
                </Field>
              )}
            </div>

            <div className="mt-5 border-t border-border pt-5">
              <Field id="model" label="Model" hint="Used for all three stages. Saved with the bar at the bottom.">
                <Select id="model" value={model} onChange={(e) => setModel(e.target.value)} className="max-w-sm">
                  {data?.catalog.models.map((m) => (
                    <option key={m.id} value={m.id}>
                      {m.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
          </Card>
        </section>

        {/* ----------------------------------------------------------- Offer */}
        <section id="offer" className="scroll-mt-8">
          <Card>
            <CardHeader
              title="What you sell"
              description="Stage 2 uses this to judge whether an angle is relevant, not merely true. Personalization will not start without it."
              action={!offer.trim() && <Badge tone="warning">Required</Badge>}
            />
            <textarea
              id="offer-text"
              aria-label="What you sell"
              className="input h-36 resize-y leading-relaxed"
              value={offer}
              onChange={(e) => setOffer(e.target.value)}
              placeholder="We help data teams cut Databricks spend by up to 75% without changing their stack…"
            />
            <p className="hint">
              One or two short paragraphs: who it is for, the outcome, and the proof. It is shared across every row, so
              it stays cached.
            </p>
          </Card>
        </section>

        {/* -------------------------------------------------------- Research */}
        <section id="research" className="scroll-mt-8">
          <Card>
            <CardHeader icon={Microscope} title="Research" description="Defaults for new research jobs." />

            <Field label="Enabled sources" hint="Each job can still switch sources on or off for that run.">
              <div className="flex flex-wrap gap-2">
                {data?.catalog.sources.map((source) => (
                  <ToggleChip
                    key={source.key}
                    checked={enabledSources.includes(source.key)}
                    onChange={(on) =>
                      setEnabledSources((prev) => (on ? [...prev, source.key] : prev.filter((k) => k !== source.key)))
                    }
                  >
                    {source.label}
                  </ToggleChip>
                ))}
              </div>
            </Field>

            <div className="mt-5 grid gap-5 sm:grid-cols-2">
              <Field
                id="linkedin-provider"
                label="LinkedIn provider"
                hint={data?.catalog.linkedin_providers.find((p) => p.key === linkedinProvider)?.note}
              >
                <Select id="linkedin-provider" value={linkedinProvider} onChange={(e) => setLinkedinProvider(e.target.value)}>
                  {data?.catalog.linkedin_providers.map((provider) => (
                    <option key={provider.key} value={provider.key}>
                      {provider.label}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field
                id="concurrency"
                label="Rows in parallel"
                hint="Higher is faster, and also the rate at which spend accrues."
              >
                <Input
                  id="concurrency"
                  type="number"
                  min={1}
                  max={32}
                  value={concurrency}
                  onChange={(e) => setConcurrency(Number(e.target.value))}
                />
              </Field>
            </div>
          </Card>
        </section>

        {/* ------------------------------------------------------------ Keys */}
        <section id="keys" className="scroll-mt-8">
          <Card>
            <CardHeader
              icon={KeyRound}
              title="Provider keys"
              description="Stored encrypted. Leave a field blank to keep the current value."
            />
            <div className="space-y-5">
              {KEY_FIELDS.map((field) => {
                const current = data?.settings.provider_keys[field.name]
                const removing = cleared.includes(field.name)
                return (
                  <Field
                    key={field.name}
                    id={`key-${field.name}`}
                    label={field.label}
                    hint={field.hint}
                    aside={
                      removing ? (
                        <span className="flex items-center gap-2">
                          <Badge tone="danger">Will be removed</Badge>
                          <button
                            className="link text-xs"
                            onClick={() => setCleared((prev) => prev.filter((k) => k !== field.name))}
                          >
                            Undo
                          </button>
                        </span>
                      ) : current ? (
                        <span className="flex items-center gap-2">
                          <Badge tone="success" dot>
                            Set · <span className="font-mono">{current}</span>
                          </Badge>
                          <button
                            className="text-xs text-muted-foreground hover:text-danger"
                            onClick={() => setCleared((prev) => [...prev, field.name])}
                          >
                            Remove
                          </button>
                        </span>
                      ) : (
                        <Badge>Not set</Badge>
                      )
                    }
                  >
                    <Input
                      id={`key-${field.name}`}
                      type="password"
                      autoComplete="off"
                      placeholder={current ? 'Unchanged' : 'Paste a key'}
                      value={keyEdits[field.name] ?? ''}
                      onChange={(e) => setKeyEdits((prev) => ({ ...prev, [field.name]: e.target.value }))}
                    />
                  </Field>
                )
              })}
            </div>
          </Card>
        </section>
      </div>

      {dirty && (
        <div className="fixed inset-x-4 bottom-4 z-30 mx-auto flex max-w-2xl items-center gap-3 rounded-xl border border-border bg-elevated/95 px-4 py-3 shadow-pop backdrop-blur animate-in fade-in slide-in-from-bottom-2 lg:left-60">
          <span className="h-2 w-2 shrink-0 rounded-full bg-warning" />
          <span className="flex-1 text-sm">You have unsaved changes</span>
          <Button variant="ghost" onClick={discard} disabled={busy}>
            Discard
          </Button>
          <Button onClick={save} loading={busy}>
            Save changes
          </Button>
        </div>
      )}
    </>
  )
}
