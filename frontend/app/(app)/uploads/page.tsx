'use client'

import Link from 'next/link'
import { useEffect, useState } from 'react'

import { Alert, Badge, Button, Empty, PageHeader, Spinner } from '@/components/ui'
import { api, exportUrl } from '@/lib/api'
import type { Upload } from '@/lib/types'

export default function UploadsPage() {
  const [uploads, setUploads] = useState<Upload[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  async function load() {
    try {
      setUploads(await api.get<Upload[]>('/uploads'))
    } catch (err: any) {
      setError(err.message)
    }
  }

  useEffect(() => {
    load()
  }, [])

  async function remove(upload: Upload) {
    if (!confirm(`Delete "${upload.name}" and all ${upload.row_count} of its rows? This cannot be undone.`)) {
      return
    }
    await api.del(`/uploads/${upload.id}`)
    load()
  }

  return (
    <>
      <PageHeader
        title="Uploads"
        description="A CSV or Google Sheet of prospects. Each upload keeps its original columns, so every export can be pasted straight back into wherever it came from."
        action={
          <Link href="/uploads/new">
            <Button>New upload</Button>
          </Link>
        }
      />

      {error && <Alert>{error}</Alert>}
      {!uploads && !error && <Spinner />}

      {uploads?.length === 0 && (
        <Empty>
          No uploads yet. <Link href="/uploads/new" className="text-primary underline">Add one</Link> to get started.
        </Empty>
      )}

      {uploads && uploads.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Name</th>
                <th>Source</th>
                <th>Rows</th>
                <th>Researched</th>
                <th>Personalized</th>
                <th>Download</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {uploads.map((upload) => (
                <tr key={upload.id}>
                  <td className="font-medium">{upload.name}</td>
                  <td>
                    <Badge>{upload.source === 'gsheet' ? 'Google Sheet' : 'CSV'}</Badge>
                  </td>
                  <td className="tabular-nums">{upload.row_count}</td>
                  <td className="tabular-nums text-muted-foreground">
                    {upload.scraped}/{upload.row_count}
                  </td>
                  <td className="tabular-nums text-muted-foreground">
                    {upload.personalized}/{upload.row_count}
                  </td>
                  <td>
                    <div className="flex gap-2 text-xs">
                      {(['research', 'personalized', 'combined'] as const).map((kind) => (
                        <a
                          key={kind}
                          href={exportUrl(upload.id, kind)}
                          className="text-primary underline underline-offset-2"
                        >
                          {kind}
                        </a>
                      ))}
                    </div>
                  </td>
                  <td>
                    <div className="flex justify-end gap-2">
                      <Link href={`/jobs?upload=${upload.id}`}>
                        <Button size="sm" variant="secondary">
                          Run
                        </Button>
                      </Link>
                      <Button size="sm" variant="ghost" onClick={() => remove(upload)}>
                        Delete
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
