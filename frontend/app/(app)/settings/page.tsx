'use client'

import { useEffect, useState } from 'react'

import { Alert, Badge, Button, Card, Input, PageHeader, Select, Spinner } from '@/components/ui'
import { api } from '@/lib/api'
import type { AiStatus, SettingsResponse } from '@/lib/types'

const KEY_FIELDS: { name: string; label: string; hint: string }[] = [
  { name: 'jina', label: 'Jina Reader', hint: 'Website content. Optional - works without a key at a lower rate limit.' },
  { name: 'serper', label: 'Serper.dev', hint: 'Google News. Required for the news source.' },
  { name: 'apify', label: 'Apify', hint: 'LinkedIn profile and company pages.' },
  {
    name: 'google_service_account_json',
    label: 'Google service account JSON',
    hint: 'One line of JSON. Share private sheets with this account email. Public sheets need nothing.',
  },
]

export default function SettingsPage() {
  const [data, setData] = useState<SettingsResponse | null>(null)
  const [ai, setAi] = useState<AiStatus | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [notice, setNotice] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  const [offer, setOffer] = useState('')
  const [concurrency, setConcurrency] = useState(4)
  const [model, setModel] = useState('claude-opus-5')
  const [enabledSources, setEnabledSources] = useState<string[]>([])
  const [linkedinProvider, setLinkedinProvider] = useState('apify')
  const [keyEdits, setKeyEdits] = useState<Record<string, string>>({})

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
  }

  useEffect(() => {
    load().catch((err) => setError(err.message))
  }, [])

  async function save() {
    setBusy(true)
    setError(null)
    setNotice(null)
    try {
      await api.put('/settings', {
        offer_context: offer,
        concurrency,
        enabled_sources: enabledSources,
        linkedin_provider: linkedinProvider,
        ai: { model },
        provider_keys: Object.keys(keyEdits).length ? keyEdits : undefined,
      })
      setKeyEdits({})
      setNotice('Saved.')
      await load()
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
    setBusy(true)
    setError(null)
    try {
      await api.post('/settings/ai/oauth/complete', { flow_id: flow.flow_id, code })
      setFlow(null)
      setCode('')
      setNotice('Claude connected.')
      await load()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function saveApiKey() {
    setBusy(true)
    setError(null)
    try {
      await api.put('/settings/ai/api-key', { api_key: apiKey })
      setApiKey('')
      setNotice('API key saved and activated.')
      await load()
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  if (!data && !error) return <Spinner />

  return (
    <>
      <PageHeader title="Settings" />

      <div className="mb-4 space-y-3">
        {error && <Alert>{error}</Alert>}
        {notice && <Alert tone="success">{notice}</Alert>}
        {ai?.warning && <Alert title="Credential conflict">{ai.warning}</Alert>}
      </div>

      <div className="space-y-6">
        <Card>
          <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
            <h2 className="font-semibold">Claude connection</h2>
            <Badge tone={ai?.connected ? 'success' : 'warning'}>
              {ai?.mode === 'api_key' ? 'API key' : 'OAuth'} ·{' '}
              {ai?.connected ? 'connected' : 'not connected'}
            </Badge>
          </div>

          {ai?.connected && ai.mode === 'oauth' && (
            <p className="mb-4 text-sm text-muted-foreground">
              {ai.organization && `Org: ${ai.organization}. `}
              {ai.workspace && `Workspace: ${ai.workspace}. `}
              The token refreshes automatically.
            </p>
          )}

          {!ai?.ant_installed && (
            <div className="mb-4">
              <Alert tone="warning">
                The <code>ant</code> CLI is not present in the API container, so the OAuth flow is
                unavailable. Rebuild the image, or use an API key below.
              </Alert>
            </div>
          )}

          {!flow ? (
            <div className="flex flex-wrap gap-3">
              <Button onClick={startOauth} disabled={!ai?.ant_installed}>
                {ai?.connected && ai.mode === 'oauth' ? 'Reconnect' : 'Connect Claude'}
              </Button>
              {ai?.connected && ai.mode === 'oauth' && (
                <Button
                  variant="secondary"
                  onClick={async () => {
                    await api.post('/settings/ai/oauth/disconnect')
                    load()
                  }}
                >
                  Disconnect
                </Button>
              )}
            </div>
          ) : (
            <div className="space-y-3 rounded-md border border-border bg-muted p-4">
              <p className="text-sm">
                1. Open this URL and authorize:
                <br />
                <a
                  href={flow.authorize_url}
                  target="_blank"
                  rel="noreferrer"
                  className="break-all text-primary underline"
                >
                  {flow.authorize_url}
                </a>
              </p>
              <p className="text-sm">2. Paste the code it gives you:</p>
              <div className="flex gap-2">
                <Input value={code} onChange={(e) => setCode(e.target.value)} placeholder="Authorization code" />
                <Button onClick={completeOauth} disabled={busy || !code}>
                  Finish
                </Button>
                <Button variant="ghost" onClick={() => setFlow(null)}>
                  Cancel
                </Button>
              </div>
              <p className="hint">This attempt expires after 15 minutes.</p>
            </div>
          )}

          <div className="mt-6 border-t border-border pt-4">
            <label className="label">API key (fallback)</label>
            <div className="flex gap-2">
              <Input
                type="password"
                placeholder="sk-ant-..."
                value={apiKey}
                onChange={(e) => setApiKey(e.target.value)}
              />
              <Button variant="secondary" onClick={saveApiKey} disabled={busy || !apiKey}>
                Save &amp; use
              </Button>
            </div>
            <p className="hint">
              Stored encrypted and picked up by the worker without a restart. Saving one switches the
              credential mode to API key.
            </p>
          </div>

          <div className="mt-6 border-t border-border pt-4">
            <label className="label">Model</label>
            <Select value={model} onChange={(e) => setModel(e.target.value)} className="max-w-sm">
              {data?.catalog.models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                </option>
              ))}
            </Select>
          </div>
        </Card>

        <Card>
          <h2 className="font-semibold">What we sell</h2>
          <p className="hint">
            Stage 2 uses this to judge whether an angle is actually relevant rather than merely true.
            Personalization jobs will not start until it is filled in.
          </p>
          <textarea
            className="input mt-3 h-32"
            value={offer}
            onChange={(e) => setOffer(e.target.value)}
            placeholder="We help data teams cut Databricks spend by up to 75% without changing their stack..."
          />
        </Card>

        <Card>
          <h2 className="font-semibold">Scraping</h2>

          <div className="mt-4">
            <label className="label">Enabled sources</label>
            <div className="flex flex-wrap gap-3">
              {data?.catalog.sources.map((source) => (
                <label key={source.key} className="flex items-center gap-2 text-sm text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={enabledSources.includes(source.key)}
                    onChange={(e) =>
                      setEnabledSources((prev) =>
                        e.target.checked ? [...prev, source.key] : prev.filter((k) => k !== source.key),
                      )
                    }
                  />
                  {source.label}
                </label>
              ))}
            </div>
          </div>

          <div className="mt-4 grid gap-4 sm:grid-cols-2">
            <div>
              <label className="label">LinkedIn provider</label>
              <Select value={linkedinProvider} onChange={(e) => setLinkedinProvider(e.target.value)}>
                {data?.catalog.linkedin_providers.map((provider) => (
                  <option key={provider.key} value={provider.key}>
                    {provider.label}
                  </option>
                ))}
              </Select>
              <p className="hint">
                {data?.catalog.linkedin_providers.find((p) => p.key === linkedinProvider)?.note}
              </p>
            </div>
            <div>
              <label className="label">Concurrency</label>
              <Input
                type="number"
                min={1}
                max={32}
                value={concurrency}
                onChange={(e) => setConcurrency(Number(e.target.value))}
              />
              <p className="hint">Rows processed in parallel. Also the rate at which spend accrues.</p>
            </div>
          </div>
        </Card>

        <Card>
          <h2 className="font-semibold">Provider keys</h2>
          <p className="hint">Stored encrypted. Existing values show masked; leave blank to keep them.</p>

          <div className="mt-4 space-y-4">
            {KEY_FIELDS.map((field) => (
              <div key={field.name}>
                <label className="label">
                  {field.label}
                  {data?.settings.provider_keys[field.name] && (
                    <span className="ml-2 font-mono text-xs text-muted-foreground">
                      {data.settings.provider_keys[field.name]}
                    </span>
                  )}
                </label>
                <Input
                  type="password"
                  placeholder={data?.settings.provider_keys[field.name] ? 'unchanged' : 'not set'}
                  value={keyEdits[field.name] ?? ''}
                  onChange={(e) => setKeyEdits((prev) => ({ ...prev, [field.name]: e.target.value }))}
                />
                <p className="hint">{field.hint}</p>
              </div>
            ))}
          </div>
        </Card>

        <Button onClick={save} disabled={busy}>
          {busy ? 'Saving...' : 'Save settings'}
        </Button>
      </div>
    </>
  )
}
