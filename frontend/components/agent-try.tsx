'use client'

import { Play, Shuffle } from 'lucide-react'
import { useEffect, useState } from 'react'

import { Alert, Badge, Button, Card, CardHeader, Select } from '@/components/ui'
import { api } from '@/lib/api'
import type { AgentProfile, Channel, PreviewResult, Upload } from '@/lib/types'

/**
 * Run the agent as it stands now (saved or not) on one researched row and show
 * what it would write. Nothing is saved; this is the loop for tuning an agent.
 */
export function AgentTry({ profile }: { profile: AgentProfile }) {
  const [uploads, setUploads] = useState<Upload[]>([])
  const [uploadId, setUploadId] = useState('')
  const [channel, setChannel] = useState<Channel>('email')
  const [offset, setOffset] = useState(0)
  const [busy, setBusy] = useState(false)
  const [result, setResult] = useState<PreviewResult | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .get<Upload[]>('/uploads')
      .then((all) => {
        const researched = all.filter((u) => u.scraped > 0)
        setUploads(researched)
        if (researched.length) setUploadId(researched[0].id)
      })
      .catch(() => {})
  }, [])

  async function run(nextOffset: number) {
    setBusy(true)
    setError(null)
    try {
      setOffset(nextOffset)
      setResult(
        await api.post<PreviewResult>('/preview', {
          upload_id: uploadId,
          channel,
          offset: nextOffset,
          agent_profile: profile,
        }),
      )
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  const line = result?.draft?.personal_line?.trim()
  const body = result?.draft?.body?.trim()

  return (
    <Card>
      <CardHeader
        title="Try it on a real row"
        description="Runs the agent as it is on screen now, saved or not, on a researched row. Nothing is saved. Change the agent in chat, then run it again."
      />
      {uploads.length === 0 ? (
        <p className="text-sm text-muted-foreground">
          No researched rows yet. Upload a sheet and run research on a few rows, then come back here.
        </p>
      ) : (
        <div className="flex flex-wrap items-center gap-2">
          <Select aria-label="Upload" value={uploadId} onChange={(e) => setUploadId(e.target.value)} className="max-w-xs">
            {uploads.map((u) => (
              <option key={u.id} value={u.id}>
                {u.name} ({u.scraped} researched)
              </option>
            ))}
          </Select>
          <Select aria-label="Channel" value={channel} onChange={(e) => setChannel(e.target.value as Channel)} className="w-32">
            <option value="email">Email</option>
            <option value="linkedin">LinkedIn</option>
            <option value="whatsapp">WhatsApp</option>
          </Select>
          <Button icon={Play} loading={busy && !result} disabled={!profile.offer.trim() || busy} onClick={() => run(0)}>
            Try it
          </Button>
          {result && (
            <Button variant="ghost" icon={Shuffle} disabled={busy} loading={busy} onClick={() => run(offset + 1)}>
              Another row
            </Button>
          )}
        </div>
      )}

      {error && <Alert className="mt-4">{error}</Alert>}

      {result && (
        <div className="mt-5 space-y-4 text-sm">
          <div className="flex flex-wrap items-center gap-2">
            <span className="font-medium">
              {result.prospect.name}
              {result.prospect.company ? `, ${result.prospect.company}` : ''}
            </span>
            <span className="text-muted-foreground">row {result.prospect.row_index + 1}</span>
            {result.hold && <Badge tone="danger">hold</Badge>}
            {result.thin_context && <Badge tone="warning">thin context</Badge>}
            {result.fit_established === false && <Badge tone="info">asks first</Badge>}
            {result.fit_established && <Badge tone="success">fit shown</Badge>}
          </div>

          {result.reason && <p className="text-muted-foreground">{result.reason}</p>}

          {line ? (
            <div>
              <p className="label">Personal line</p>
              <p className="whitespace-pre-wrap rounded-md border border-border bg-muted/30 p-3">{line}</p>
            </div>
          ) : (
            result.draft && (
              <p className="text-muted-foreground">
                {body ? 'No personal line for this row.' : 'Nothing written for this row: no good evidence, so the line is blank.'}
              </p>
            )
          )}

          {body && (
            <div>
              <p className="label">Message{result.draft?.subject ? `: ${result.draft.subject}` : ''}</p>
              <p className="whitespace-pre-wrap rounded-md border border-border bg-muted/30 p-3">{body}</p>
            </div>
          )}

          {result.fit_evidence && (
            <p className="text-xs text-muted-foreground">
              <span className="font-medium">Evidence of fit:</span> {result.fit_evidence}
            </p>
          )}
          {result.angles.length > 0 && (
            <ul className="space-y-1 text-xs text-muted-foreground">
              {result.angles.map((a, i) => (
                <li key={i}>
                  <span className="font-medium">Angle:</span> {a.angle} <span className="italic">({a.evidence})</span>
                </li>
              ))}
            </ul>
          )}
          {[...result.warnings, ...(result.constraint_warning ? [result.constraint_warning] : [])].map((w, i) => (
            <Alert key={i} tone="warning">
              {w}
            </Alert>
          ))}
          <p className="text-xs text-muted-foreground">Cost of this try: ${result.cost_usd.toFixed(3)}</p>
        </div>
      )}
    </Card>
  )
}
