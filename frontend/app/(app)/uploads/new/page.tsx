'use client'

import { useRouter } from 'next/navigation'
import { useEffect, useState } from 'react'

import { Alert, Button, Card, Input, PageHeader, Select } from '@/components/ui'
import { api } from '@/lib/api'
import type { UploadPreview } from '@/lib/types'

const UNMAPPED = ''

// Fields the scraping engine and the prompts actually read.
const FIELD_HELP: Record<string, string> = {
  full_name: 'Used to address the message.',
  first_name: 'Preferred in greetings.',
  company: 'Drives the Google News search.',
  website: 'Scraped for site content and an RSS feed.',
  linkedin_url: 'Scraped for the personal profile.',
  linkedin_company_url: 'Scraped for the company page.',
}

export default function NewUploadPage() {
  const router = useRouter()
  const [mode, setMode] = useState<'csv' | 'sheet'>('csv')
  const [sheetUrl, setSheetUrl] = useState('')
  const [sheetTab, setSheetTab] = useState('')
  const [file, setFile] = useState<File | null>(null)

  const [preview, setPreview] = useState<UploadPreview | null>(null)
  const [fields, setFields] = useState<string[]>([])
  const [mapping, setMapping] = useState<Record<string, string>>({})
  const [name, setName] = useState('')

  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => {
    api
      .get<{ fields: string[] }>('/uploads/identity-fields')
      .then((r) => setFields(r.fields))
      .catch(() => null)
  }, [])

  async function loadPreview(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      let result: UploadPreview
      if (mode === 'csv') {
        if (!file) throw new Error('Choose a CSV file first.')
        const form = new FormData()
        form.append('file', file)
        result = await api.upload<UploadPreview>('/uploads/preview/csv', form)
        setName(file.name.replace(/\.csv$/i, ''))
      } else {
        result = await api.post<UploadPreview>('/uploads/preview/sheet', {
          sheet_url: sheetUrl,
          sheet_tab: sheetTab || null,
        })
        setName(sheetTab || 'Google Sheet')
      }
      setPreview(result)
      setMapping(result.suggested_mapping)
    } catch (err: any) {
      setError(err.message)
    } finally {
      setBusy(false)
    }
  }

  async function commit() {
    if (!preview) return
    setBusy(true)
    setError(null)
    try {
      await api.post('/uploads/commit', {
        staging_id: preview.staging_id,
        name,
        column_mapping: mapping,
      })
      router.push('/uploads')
    } catch (err: any) {
      setError(err.message)
      setBusy(false)
    }
  }

  // A column already claimed by another field, so the same header is not
  // silently mapped twice.
  function takenBy(column: string, field: string): string | null {
    const owner = Object.entries(mapping).find(([f, c]) => c === column && f !== field)
    return owner ? owner[0] : null
  }

  return (
    <>
      <PageHeader
        title="New upload"
        description="Load the rows, then confirm which column means what. The mapping is remembered for the next sheet with the same headers."
      />

      {error && (
        <div className="mb-4">
          <Alert>{error}</Alert>
        </div>
      )}

      {!preview && (
        <Card className="max-w-2xl">
          <div className="mb-4 flex gap-2">
            <Button variant={mode === 'csv' ? 'primary' : 'secondary'} size="sm" onClick={() => setMode('csv')}>
              Upload CSV
            </Button>
            <Button variant={mode === 'sheet' ? 'primary' : 'secondary'} size="sm" onClick={() => setMode('sheet')}>
              Google Sheet URL
            </Button>
          </div>

          <form onSubmit={loadPreview} className="space-y-4">
            {mode === 'csv' ? (
              <div>
                <label className="label" htmlFor="file">
                  CSV file
                </label>
                <input
                  id="file"
                  type="file"
                  accept=".csv,.tsv,text/csv"
                  onChange={(e) => setFile(e.target.files?.[0] || null)}
                  className="input file:mr-3 file:rounded file:border-0 file:bg-border file:px-3 file:py-1 file:text-xs file:text-foreground"
                />
                <p className="hint">Comma, semicolon and tab separated files all work. Max 25MB.</p>
              </div>
            ) : (
              <>
                <div>
                  <label className="label" htmlFor="sheet">
                    Sheet URL
                  </label>
                  <Input
                    id="sheet"
                    placeholder="https://docs.google.com/spreadsheets/d/..."
                    value={sheetUrl}
                    onChange={(e) => setSheetUrl(e.target.value)}
                  />
                  <p className="hint">
                    Either set link sharing to &quot;Anyone with the link&quot;, or share the sheet with the
                    service account configured in Settings.
                  </p>
                </div>
                <div>
                  <label className="label" htmlFor="tab">
                    Tab name (optional)
                  </label>
                  <Input
                    id="tab"
                    placeholder="Sheet1"
                    value={sheetTab}
                    onChange={(e) => setSheetTab(e.target.value)}
                  />
                </div>
              </>
            )}

            <Button type="submit" disabled={busy}>
              {busy ? 'Loading...' : 'Load rows'}
            </Button>
          </form>
        </Card>
      )}

      {preview && (
        <div className="space-y-6">
          <Card>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <div className="min-w-64 flex-1">
                <label className="label" htmlFor="name">
                  Upload name
                </label>
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
              </div>
              <p className="text-sm text-muted-foreground">
                {preview.row_count} rows, {preview.headers.length} columns
              </p>
            </div>
          </Card>

          <Card>
            <h2 className="font-semibold">Map the columns</h2>
            <p className="mt-1 text-sm text-muted-foreground">
              Map at least one identifier (name or company) and at least one thing to scrape (website or a
              LinkedIn URL).
            </p>

            <div className="mt-4 grid gap-4 sm:grid-cols-2">
              {fields.map((field) => {
                const column = mapping[field] || UNMAPPED
                const conflict = column ? takenBy(column, field) : null
                return (
                  <div key={field}>
                    <label className="label" htmlFor={`map-${field}`}>
                      {field}
                    </label>
                    <Select
                      id={`map-${field}`}
                      value={column}
                      onChange={(e) =>
                        setMapping((prev) => {
                          const next = { ...prev }
                          if (e.target.value) next[field] = e.target.value
                          else delete next[field]
                          return next
                        })
                      }
                    >
                      <option value={UNMAPPED}>— not mapped —</option>
                      {preview.headers.map((header) => (
                        <option key={header} value={header}>
                          {header}
                        </option>
                      ))}
                    </Select>
                    {conflict ? (
                      <p className="hint text-warning">Also mapped to &quot;{conflict}&quot;.</p>
                    ) : (
                      FIELD_HELP[field] && <p className="hint">{FIELD_HELP[field]}</p>
                    )}
                  </div>
                )
              })}
            </div>
          </Card>

          <Card>
            <h2 className="mb-3 font-semibold">First rows</h2>
            <div className="table-wrap">
              <table className="data">
                <thead>
                  <tr>
                    {preview.headers.map((header) => (
                      <th key={header}>{header}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample_rows.map((row, index) => (
                    <tr key={index}>
                      {preview.headers.map((header) => (
                        <td key={header} className="max-w-56 truncate text-muted-foreground">
                          {row[header]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="flex gap-3">
            <Button onClick={commit} disabled={busy}>
              {busy ? 'Saving...' : `Create upload with ${preview.row_count} rows`}
            </Button>
            <Button variant="secondary" onClick={() => setPreview(null)} disabled={busy}>
              Back
            </Button>
          </div>
        </div>
      )}
    </>
  )
}
