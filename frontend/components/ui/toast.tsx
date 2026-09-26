'use client'

import { CheckCircle2, X, XCircle } from 'lucide-react'
import { useEffect, useState } from 'react'

/**
 * Minimal toast store. Confirmations ("Saved", "Job queued") used to render as
 * in-page alerts that never went away and pushed the layout down; a toast
 * says the same thing and gets out of the way.
 */
type Toast = { id: number; tone: 'success' | 'error'; message: string }

let nextId = 1
let items: Toast[] = []
const listeners = new Set<(items: Toast[]) => void>()

function emit() {
  for (const listener of listeners) listener(items)
}

function push(tone: Toast['tone'], message: string) {
  const id = nextId++
  items = [...items, { id, tone, message }]
  emit()
  setTimeout(() => dismiss(id), tone === 'error' ? 7000 : 3500)
}

function dismiss(id: number) {
  items = items.filter((t) => t.id !== id)
  emit()
}

export const toast = {
  success: (message: string) => push('success', message),
  error: (message: string) => push('error', message),
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
          ) : (
            <XCircle className="mt-0.5 h-4 w-4 shrink-0 text-danger" aria-hidden />
          )}
          <p className="flex-1 leading-relaxed">{t.message}</p>
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
