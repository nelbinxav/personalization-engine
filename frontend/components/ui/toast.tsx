'use client'

import { Bell, CheckCircle2, X, XCircle } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useState } from 'react'

/**
 * Minimal toast store. Confirmations ("Saved", "Job queued") used to render as
 * in-page alerts that never went away and pushed the layout down; a toast
 * says the same thing and gets out of the way.
 *
 * A notice is the exception: it reports something that happened while the
 * operator was not looking (a job finished or paused), so it stays until
 * dismissed and can carry a link to the next step.
 */
type Action = { href: string; label: string }
type Toast = {
  id: number
  tone: 'success' | 'error' | 'notice'
  message: string
  title?: string
  action?: Action
}

let nextId = 1
let items: Toast[] = []
const listeners = new Set<(items: Toast[]) => void>()

function emit() {
  for (const listener of listeners) listener(items)
}

function push(tone: Toast['tone'], message: string, extra: Pick<Toast, 'title' | 'action'> = {}) {
  const id = nextId++
  items = [...items, { id, tone, message, ...extra }]
  emit()
  if (tone !== 'notice') setTimeout(() => dismiss(id), tone === 'error' ? 7000 : 3500)
}

function dismiss(id: number) {
  items = items.filter((t) => t.id !== id)
  emit()
}

export const toast = {
  success: (message: string) => push('success', message),
  error: (message: string) => push('error', message),
  notice: (title: string, message: string, action?: Action) => push('notice', message, { title, action }),
}

export function Toaster() {
  const [list, setList] = useState<Toast[]>(items)

  useEffect(() => {
    listeners.add(setList)
    return () => {
      listeners.delete(setList)
    }
  }, [])

  return (
    <div
      aria-live="polite"
      className="pointer-events-none fixed inset-x-4 bottom-4 z-50 flex flex-col items-end gap-2 sm:inset-x-auto sm:right-6"
    >
      {list.map((t) => (
        <div
          key={t.id}
          className="pointer-events-auto flex w-full max-w-sm items-start gap-3 rounded-lg border border-border bg-elevated px-4 py-3 text-sm shadow-pop animate-in fade-in slide-in-from-bottom-2"
        >
          {t.tone === 'success' ? (
            <CheckCircle2 className="mt-0.5 h-4 w-4 shrink-0 text-success" aria-hidden />
          ) : t.tone === 'notice' ? (
            <Bell className="mt-0.5 h-4 w-4 shrink-0 text-info" aria-hidden />
          ) : (
            <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
          )}
          <div className="flex-1 leading-relaxed">
            {t.title && <p className="font-medium">{t.title}</p>}
            <p className={t.title ? 'text-muted-foreground' : undefined}>{t.message}</p>
            {t.action && (
              <Link href={t.action.href} onClick={() => dismiss(t.id)} className="link mt-1 inline-block text-sm">
                {t.action.label}
              </Link>
            )}
          </div>
          <button
            onClick={() => dismiss(t.id)}
            className="rounded text-muted-foreground hover:text-foreground"
            aria-label="Dismiss"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      ))}
    </div>
  )
}
