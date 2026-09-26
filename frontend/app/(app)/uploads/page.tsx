'use client'

import { ArrowRight, FileSpreadsheet, Plus } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useState } from 'react'

import { Alert, Badge, Empty, LinkButton, PageHeader, Progress, Skeleton } from '@/components/ui'
import { api } from '@/lib/api'
import type { Upload } from '@/lib/types'
import { NEXT_ACTION_LABEL, nextAction, timeAgo } from '@/lib/workflow'

export default function UploadsPage() {
  const [uploads, setUploads] = useState<Upload[] | null>(null)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    api
      .get<Upload[]>('/uploads')
      .then(setUploads)
      .catch((err) => setError(err.message))
  }, [])

  return (
    <>
      <PageHeader
        title="Uploads"
        description="Each upload is one list of prospects. It keeps your original columns, so every download pastes straight back to wherever it came from."
        action={
          <LinkButton href="/uploads/new" icon={Plus}>
            New upload
          </LinkButton>
        }
      />

      {error && <Alert title="Could not load uploads">{error}</Alert>}

      {!uploads && !error && (
        <div className="space-y-2">
          {[0, 1, 2].map((i) => (
            <Skeleton key={i} className="h-16 w-full" />
          ))}
        </div>
      )}

      {uploads?.length === 0 && (
        <Empty
          icon={FileSpreadsheet}
          title="No uploads yet"
          action={
            <LinkButton href="/uploads/new" icon={Plus}>
              Add your first list
            </LinkButton>
          }
        >
          Bring a CSV or a Google Sheet of prospects. You will confirm which column is which before
          anything runs.
        </Empty>
      )}

      {uploads && uploads.length > 0 && (
        <div className="table-wrap">
          <table className="data">
            <thead>
              <tr>
                <th>Name</th>
                <th>Rows</th>
                <th>Researched</th>
                <th>Messages</th>
                <th className="text-right">Next step</th>
              </tr>
            </thead>
            <tbody>
              {uploads.map((upload) => {
                const next = nextAction(upload)
                return (
                  <tr key={upload.id}>
                    <td>
                      <Link href={`/uploads/${upload.id}`} className="font-medium hover:text-primary">
                        {upload.name}
                      </Link>
                      <div className="mt-0.5 flex items-center gap-2 text-xs text-muted-foreground">
                        <Badge>{upload.source === 'gsheet' ? 'Google Sheet' : 'CSV'}</Badge>
                        {timeAgo(upload.created_at)}
                      </div>
                    </td>
                    <td className="tabular-nums">{upload.row_count}</td>
                    <td>
                      <Progress done={upload.scraped} total={upload.row_count} />
                    </td>
                    <td>
                      <Progress done={upload.personalized} total={upload.row_count} />
                    </td>
                    <td className="text-right">
                      <LinkButton
                        href={`/uploads/${upload.id}`}
                        size="sm"
                        variant={next === 'export' ? 'outline' : 'secondary'}
                      >
                        {NEXT_ACTION_LABEL[next]}
                        <ArrowRight className="h-3.5 w-3.5" />
                      </LinkButton>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      )}
    </>
  )
}
