'use client'

import { ArrowLeft, ArrowRight, FileUp, Link2, Sheet, UploadCloud, X } from 'lucide-react'
import Link from 'next/link'
import { useRouter } from 'next/navigation'
import { useEffect, useRef, useState } from 'react'

import {
  Alert,
  Button,
  Card,
  CardHeader,
  Field,
  Input,
  PageHeader,
  Segmented,
  Select,
  Stepper,
  cn,
  toast,
} from '@/components/ui'
import { api } from '@/lib/api'
import type { Upload, UploadPreview } from '@/lib/types'
import { FIELD_META, IDENTIFIER_FIELDS, TARGET_FIELDS, mappingProblems } from '@/lib/workflow'

const UNMAPPED = ''

// Mapping grouped by what the field is for, so the "at least one of" rules
// read as a sentence rather than a list of eleven selects.
const GROUPS = [
  {
    title: 'Who they are',
    description: 'Map at least one of full name, first name or company.',
    fields: ['full_name', 'first_name', 'last_name', 'title', 'company'],
  },
  {
    title: 'Where to research',
    description: 'Map at least one: this is what the scrapers fetch.',
    fields: ['website', 'linkedin_url', 'linkedin_company_url'],
  },
  {
    title: 'Contact details',
    description: 'Optional. Carried through to the export.',
    fields: ['email', 'phone', 'location'],
  },
]

export default function NewUploadPage() {
  const router = useRouter()
  const [mode, setMode] = useState<'csv' | 'sheet'>('csv')
  const [sheetUrl, setSheetUrl] = useState('')
  const [sheetTab, setSheetTab] = useState('')
  const [file, setFile] = useState<File | null>(null)
  const [dragging, setDragging] = useState(false)
  const fileInput = useRef<HTMLInputElement>(null)

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
        setName(file.name.replace(/\.(csv|tsv)$/i, ''))
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
      const upload = await api.post<Upload>('/uploads/commit', {
        staging_id: preview.staging_id,
        name,
        column_mapping: mapping,
      })
      toast.success(`Imported ${upload.row_count} rows.`)
      router.push(`/uploads/${upload.id}?phase=scrape`)
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

  function pickFile(next: File | undefined | null) {
    if (!next) return
    if (!/\.(csv|tsv|txt)$/i.test(next.name)) {
      setError('That does not look like a CSV. Export the sheet as .csv and try again.')
      return
    }
    setError(null)
    setFile(next)
  }

  const problems = preview ? mappingProblems(mapping) : []
  const mappedColumns = new Set(Object.values(mapping))
  const sample = preview?.sample_rows.find((row) => Object.values(row).some(Boolean))
  const grouped = new Set(GROUPS.flatMap((g) => g.fields))
  const extraFields = fields.filter((f) => !grouped.has(f))

  return (
    <>
      <PageHeader
        eyebrow={
          <Link href="/uploads" className="inline-flex items-center gap-1.5 hover:text-foreground">
            <ArrowLeft className="h-3.5 w-3.5" /> Uploads
          </Link>
        }
        title="New upload"
        description="Load your prospects, confirm which column is which, then research them."
      />

      <Card className="mb-6 px-6 py-5">
        <Stepper
          steps={[
            { label: 'Choose a source', description: 'CSV or Google Sheet', state: preview ? 'done' : 'current' },
            {
              label: 'Match the columns',
              description: 'Remembered for next time',
              state: preview ? 'current' : 'upcoming',
            },
            { label: 'Research', description: 'Try 3 rows first', state: 'upcoming' },
          ]}
        />
      </Card>

      {error && <Alert className="mb-6">{error}</Alert>}

      {!preview && (
        <Card className="max-w-2xl">
          <Segmented
            label="Source"
            value={mode}
            onChange={setMode}
            className="mb-6"
            options={[
              {
                value: 'csv',
                label: (
                  <>
                    <FileUp className="h-4 w-4" /> CSV file
                  </>
                ),
              },
              {
                value: 'sheet',
                label: (
                  <>
                    <Sheet className="h-4 w-4" /> Google Sheet
                  </>
                ),
              },
            ]}
          />

          <form onSubmit={loadPreview} className="space-y-5">
            {mode === 'csv' ? (
              <div>
                <input
                  ref={fileInput}
                  id="file"
                  type="file"
                  accept=".csv,.tsv,text/csv"
                  className="sr-only"
                  onChange={(e) => pickFile(e.target.files?.[0])}
                />
                {file ? (
                  <div className="flex items-center gap-3 rounded-lg border border-border bg-muted/50 px-4 py-3">
                    <FileUp className="h-5 w-5 shrink-0 text-primary" />
                    <div className="min-w-0 flex-1">
                      <p className="truncate text-sm font-medium">{file.name}</p>
                      <p className="text-xs text-muted-foreground">{(file.size / 1024).toFixed(0)} KB</p>
                    </div>
                    <Button
                      size="icon"
                      variant="ghost"
                      aria-label="Remove file"
                      onClick={() => {
                        setFile(null)
                        if (fileInput.current) fileInput.current.value = ''
                      }}
                    >
                      <X className="h-4 w-4" />
                    </Button>
                  </div>
                ) : (
                  <label
                    htmlFor="file"
                    onDragOver={(e) => {
                      e.preventDefault()
                      setDragging(true)
                    }}
                    onDragLeave={() => setDragging(false)}
                    onDrop={(e) => {
                      e.preventDefault()
                      setDragging(false)
                      pickFile(e.dataTransfer.files?.[0])
                    }}
                    className={cn(
                      'flex cursor-pointer flex-col items-center justify-center rounded-xl border-2 border-dashed px-6 py-12 text-center transition-colors',
                      dragging
                        ? 'border-primary bg-primary/[0.06]'
                        : 'border-border-strong/60 hover:border-primary/60 hover:bg-muted/40',
                    )}
                  >
                    <UploadCloud className={cn('h-8 w-8', dragging ? 'text-primary' : 'text-muted-foreground')} />
                    <p className="mt-3 text-sm font-medium">Drop a CSV here, or click to browse</p>
                    <p className="mt-1 text-xs text-muted-foreground">
                      Comma, semicolon and tab separated all work. Max 25MB.
                    </p>
                  </label>
                )}
              </div>
            ) : (
              <>
                <Field
                  id="sheet"
                  label="Sheet URL"
                  hint={
                    <>
                      Set link sharing to “Anyone with the link”, or share the sheet with the service account in{' '}
                      <Link href="/settings#keys" className="link">
                        Settings
                      </Link>
                      .
                    </>
                  }
                >
                  <div className="relative">
                    <Link2 className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                      id="sheet"
                      className="pl-9"
                      placeholder="https://docs.google.com/spreadsheets/d/…"
                      value={sheetUrl}
                      onChange={(e) => setSheetUrl(e.target.value)}
                    />
                  </div>
                </Field>
                <Field id="tab" label="Tab name" aside={<span className="text-xs text-muted-foreground">Optional</span>} hint="Defaults to the first tab.">
                  <Input id="tab" placeholder="Sheet1" value={sheetTab} onChange={(e) => setSheetTab(e.target.value)} />
                </Field>
              </>
            )}

            <Button
              type="submit"
              loading={busy}
              disabled={mode === 'csv' ? !file : !sheetUrl.trim()}
            >
              {busy ? 'Reading rows' : 'Continue'}
              {!busy && <ArrowRight className="h-4 w-4" />}
            </Button>
          </form>
        </Card>
      )}

      {preview && (
        <div className="space-y-6">
          <Card>
            <div className="flex flex-wrap items-end justify-between gap-4">
              <Field id="name" label="Name this upload" className="min-w-64 flex-1">
                <Input id="name" value={name} onChange={(e) => setName(e.target.value)} />
              </Field>
              <p className="pb-2 text-sm text-muted-foreground">
                <span className="font-medium text-foreground">{preview.row_count}</span> rows ·{' '}
                <span className="font-medium text-foreground">{preview.headers.length}</span> columns
              </p>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Match your columns"
              description="We guessed from the headers. Check each one against the sample value on the right."
            />

            <div className="space-y-8">
              {[...GROUPS, ...(extraFields.length ? [{ title: 'Other', description: '', fields: extraFields }] : [])].map(
                (group) => {
                  const groupFields = group.fields.filter((f) => fields.includes(f))
                  if (!groupFields.length) return null
                  const required =
                    group.fields === GROUPS[0].fields
                      ? IDENTIFIER_FIELDS
                      : group.fields === GROUPS[1].fields
                        ? TARGET_FIELDS
                        : null
                  const satisfied = required ? required.some((f) => mapping[f]) : true
                  return (
                    <section key={group.title}>
                      <div className="mb-3 flex items-baseline gap-3 border-b border-border pb-2">
                        <h3 className="text-sm font-semibold">{group.title}</h3>
                        {group.description && (
                          <p className={cn('text-xs', satisfied ? 'text-muted-foreground' : 'text-warning')}>
                            {group.description}
                          </p>
                        )}
                      </div>
                      <div className="grid gap-x-6 gap-y-4 md:grid-cols-2">
                        {groupFields.map((field) => {
                          const column = mapping[field] || UNMAPPED
                          const conflict = column ? takenBy(column, field) : null
                          const example = column && sample ? sample[column] : null
                          const meta = FIELD_META[field]
                          return (
                            <Field
                              key={field}
                              id={`map-${field}`}
                              label={meta?.label ?? field}
                              error={conflict ? `Also mapped to ${FIELD_META[conflict]?.label ?? conflict}.` : undefined}
                              hint={
                                example ? (
                                  <>
                                    e.g. <span className="font-medium text-foreground">{example}</span>
                                  </>
                                ) : (
                                  meta?.help
                                )
                              }
                            >
                              <Select
                                id={`map-${field}`}
                                value={column}
                                className={cn(!column && 'text-muted-foreground')}
                                onChange={(e) =>
                                  setMapping((prev) => {
                                    const next = { ...prev }
                                    if (e.target.value) next[field] = e.target.value
                                    else delete next[field]
                                    return next
                                  })
                                }
                              >
                                <option value={UNMAPPED}>Not in this sheet</option>
                                {preview.headers.map((header) => (
                                  <option key={header} value={header}>
                                    {header}
                                  </option>
                                ))}
                              </Select>
                            </Field>
                          )
                        })}
                      </div>
                    </section>
                  )
                },
              )}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="First rows"
              description="Mapped columns are highlighted."
            />
            <div className="table-wrap shadow-none">
              <table className="data">
                <thead>
                  <tr>
                    {preview.headers.map((header) => (
                      <th key={header} className={cn(mappedColumns.has(header) && 'bg-primary/10 text-primary')}>
                        {header}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {preview.sample_rows.map((row, index) => (
                    <tr key={index}>
                      {preview.headers.map((header) => (
                        <td
                          key={header}
                          className={cn(
                            'max-w-56 truncate',
                            mappedColumns.has(header) ? 'text-foreground' : 'text-muted-foreground',
                          )}
                          title={row[header]}
                        >
                          {row[header]}
                        </td>
                      ))}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </Card>

          <div className="sticky bottom-4 z-10 flex flex-wrap items-center gap-3 rounded-xl border border-border bg-elevated/95 px-4 py-3 shadow-pop backdrop-blur">
            <Button variant="ghost" onClick={() => setPreview(null)} disabled={busy}>
              <ArrowLeft className="h-4 w-4" /> Back
            </Button>
            <div className="min-w-0 flex-1 text-sm">
              {problems.length ? (
                <span className="text-warning">{problems[0]}</span>
              ) : (
                <span className="text-muted-foreground">Looks good. Next you will choose what to research.</span>
              )}
            </div>
            <Button onClick={commit} loading={busy} disabled={problems.length > 0}>
              Import {preview.row_count} rows
              {!busy && <ArrowRight className="h-4 w-4" />}
            </Button>
          </div>
        </div>
      )}
    </>
  )
}
