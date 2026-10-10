'use client'

import { ArrowUp, FileText, Paperclip, Square, X } from 'lucide-react'
import { useCallback, useEffect, useRef, useState } from 'react'

import { cn, toast } from '@/components/ui'
import { streamPost } from '@/lib/api'
import type { AgentProfile, ChatAttachment, ChatEvent, ChatMessage } from '@/lib/types'

const TEXT_FILE = /\.(txt|md|markdown|csv|json|html?|xml|yaml|yml|log)$/i
const MAX_CHARS = 12000 // the backend reads this much of each attachment

type Phase = 'idle' | 'replying' | 'updating'

function readStored(key: string | null): ChatMessage[] {
  if (!key) return []
  try {
    return JSON.parse(localStorage.getItem(key) || '[]')
  } catch {
    return []
  }
}

function writeStored(key: string | null, messages: ChatMessage[]) {
  if (!key) return
  try {
    // The profile already holds what an attachment said, so keep only its name.
    const slim = messages.map((m) => ({
      ...m,
      attachments: m.attachments?.map((a) => ({ name: a.name, text: '' })),
    }))
    localStorage.setItem(key, JSON.stringify(slim.slice(-60)))
  } catch {}
}

/**
 * A running conversation with the trainer. The profile lives in the page; the
 * chat hands it every turn and gets the updated one back. Remount it (change
 * `key`) to start a different conversation.
 */
export function AgentChat({
  profile,
  onProfile,
  storageKey,
  greet,
}: {
  profile: AgentProfile
  onProfile: (profile: AgentProfile, missing: string[], done: boolean) => void
  storageKey: string | null
  /** Open with the trainer speaking first (a new, empty agent). */
  greet: boolean
}) {
  const [messages, setMessages] = useState<ChatMessage[]>(() => readStored(storageKey))
  const [draft, setDraft] = useState('')
  const [files, setFiles] = useState<ChatAttachment[]>([])
  const [phase, setPhase] = useState<Phase>('idle')
  const [dragging, setDragging] = useState(false)
  const abort = useRef<AbortController | null>(null)
  const thread = useRef<HTMLDivElement>(null)
  const input = useRef<HTMLTextAreaElement>(null)
  const pinned = useRef(true) // follow new text unless the reader scrolled up
  const started = useRef(false)

  const busy = phase !== 'idle'

  useEffect(() => {
    if (!busy) writeStored(storageKey, messages)
  }, [messages, busy, storageKey])

  useEffect(() => {
    const el = thread.current
    if (el && pinned.current) el.scrollTop = el.scrollHeight
  }, [messages, phase])

  // Grow the input with its text, up to a limit.
  useEffect(() => {
    const el = input.current
    if (!el) return
    el.style.height = 'auto'
    el.style.height = `${Math.min(el.scrollHeight, 200)}px`
  }, [draft])

  const converse = useCallback(
    async (history: ChatMessage[]) => {
      // Only the newest message carries its attachment text; the profile already
      // holds what the older ones said, and resending them each turn costs tokens.
      const lastUser = history.map((m) => m.role).lastIndexOf('user')
      const wire = history.map((m, i) => ({
        ...m,
        attachments: i === lastUser ? m.attachments : m.attachments?.map((a) => ({ name: a.name, text: '' })),
      }))

      pinned.current = true
      setMessages([...history, { role: 'assistant', text: '' }])
      setPhase('replying')
      const controller = new AbortController()
      abort.current = controller

      const append = (text: string) =>
        setMessages((all) => {
          const next = all.slice()
          const last = next[next.length - 1]
          next[next.length - 1] = { ...last, text: last.text + text }
          return next
        })

      try {
        await streamPost<ChatEvent>(
          '/agents/chat',
          { messages: wire, profile },
          (event) => {
            if (event.type === 'delta') append(event.text)
            else if (event.type === 'reply_done') setPhase('updating')
            else if (event.type === 'profile') onProfile(event.profile, event.missing, event.done)
            else if (event.type === 'error') {
              toast.error(event.message)
              setMessages((all) => (all[all.length - 1]?.text === '' ? all.slice(0, -1) : all))
            }
          },
          controller.signal,
        )
      } catch (err: any) {
        if (err?.name !== 'AbortError') {
          toast.error(err?.message || 'Could not reach the trainer.')
          setMessages((all) => (all[all.length - 1]?.text === '' ? all.slice(0, -1) : all))
        }
      } finally {
        abort.current = null
        setPhase('idle')
        input.current?.focus()
      }
    },
    [profile, onProfile],
  )

  // A new agent: the trainer speaks first.
  useEffect(() => {
    if (greet && !started.current && messages.length === 0) {
      started.current = true
      void converse([])
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  useEffect(() => () => abort.current?.abort(), [])

  function send() {
    const text = draft.trim()
    if (busy || (!text && files.length === 0)) return
    setDraft('')
    setFiles([])
    void converse([...messages, { role: 'user', text, attachments: files.length ? files : undefined }])
  }

  async function addFiles(list: FileList | File[]) {
    for (const file of Array.from(list)) {
      if (!TEXT_FILE.test(file.name) && !file.type.startsWith('text/')) {
        toast.error(`${file.name}: only text files work for now (txt, md, csv, json, html). Paste the text of a PDF or Word file instead.`)
        continue
      }
      const text = await file.text()
      if (text.length > MAX_CHARS) toast.notice('Long file', `${file.name}: only the first ${MAX_CHARS.toLocaleString()} characters are read.`)
      setFiles((all) => [...all, { name: file.name, text }])
    }
  }

  return (
    <div
      className={cn(
        'relative flex h-full min-h-0 flex-col rounded-lg border border-border bg-card',
        dragging && 'ring-2 ring-primary/50',
      )}
      onDragOver={(e) => (e.preventDefault(), setDragging(true))}
      onDragLeave={(e) => e.currentTarget.contains(e.relatedTarget as Node) || setDragging(false)}
      onDrop={(e) => {
        e.preventDefault()
        setDragging(false)
        if (e.dataTransfer.files.length) void addFiles(e.dataTransfer.files)
      }}
    >
      <div
        ref={thread}
        className="min-h-0 flex-1 space-y-4 overflow-y-auto px-4 py-5"
        onScroll={(e) => {
          const el = e.currentTarget
          pinned.current = el.scrollHeight - el.scrollTop - el.clientHeight < 80
        }}
      >
        {messages.length === 0 && !busy && (
          <p className="mx-auto max-w-md pt-10 text-center text-sm text-muted-foreground">
            Tell me about this offer: what you sell, who it is for, what you can prove, how you sound. Paste or drop
            anything you already have, and ask me to change anything at any time.
          </p>
        )}
        {messages.map((m, i) => {
          const last = i === messages.length - 1
          return (
            <div key={i} className={cn('flex', m.role === 'user' ? 'justify-end' : 'justify-start')}>
              <div className={cn('max-w-[85%] space-y-2', m.role === 'user' && 'items-end')}>
                {m.attachments?.map((a, j) => (
                  <div
                    key={j}
                    className="ml-auto flex w-fit items-center gap-1.5 rounded-md border border-border bg-muted/40 px-2 py-1 text-xs text-muted-foreground"
                  >
                    <FileText className="h-3.5 w-3.5" aria-hidden />
                    {a.name}
                  </div>
                ))}
                {(m.text || (last && m.role === 'assistant')) && (
                  <div
                    className={cn(
                      'whitespace-pre-wrap rounded-2xl px-4 py-2.5 text-sm leading-relaxed',
                      m.role === 'user' ? 'bg-primary text-primary-foreground' : 'bg-muted/60',
                    )}
                  >
                    {m.text}
                    {last && m.role === 'assistant' && phase === 'replying' && (
                      <span className="ml-0.5 inline-block h-4 w-1.5 translate-y-0.5 animate-pulse rounded-sm bg-foreground/50" />
                    )}
                  </div>
                )}
                {last && m.role === 'assistant' && phase === 'updating' && (
                  <p className="px-1 text-xs text-muted-foreground">Updating the profile…</p>
                )}
              </div>
            </div>
          )
        })}
      </div>

      <div className="border-t border-border p-3">
        {files.length > 0 && (
          <div className="mb-2 flex flex-wrap gap-2">
            {files.map((f, i) => (
              <span key={i} className="flex items-center gap-1.5 rounded-md border border-border bg-muted/40 py-1 pl-2 pr-1 text-xs">
                <FileText className="h-3.5 w-3.5 text-muted-foreground" aria-hidden />
                {f.name}
                <button
                  type="button"
                  aria-label={`Remove ${f.name}`}
                  className="rounded p-0.5 hover:bg-muted"
                  onClick={() => setFiles((all) => all.filter((_, j) => j !== i))}
                >
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
          </div>
        )}
        <div className="flex items-end gap-2 rounded-xl border border-input bg-background px-2 py-2 focus-within:ring-2 focus-within:ring-ring/40">
          <label className="cursor-pointer rounded-md p-2 text-muted-foreground hover:bg-muted hover:text-foreground">
            <Paperclip className="h-4 w-4" aria-label="Attach files" />
            <input
              type="file"
              multiple
              accept=".txt,.md,.markdown,.csv,.json,.html,.htm,.xml,.yaml,.yml,.log,text/*"
              className="sr-only"
              onChange={(e) => {
                if (e.target.files) void addFiles(e.target.files)
                e.target.value = ''
              }}
            />
          </label>
          <textarea
            ref={input}
            rows={1}
            value={draft}
            autoFocus
            aria-label="Message"
            placeholder="Message the trainer. Paste text, drop files, or ask for a change."
            className="max-h-[200px] min-h-[2.25rem] flex-1 resize-none bg-transparent py-2 text-sm outline-none placeholder:text-muted-foreground"
            onChange={(e) => setDraft(e.target.value)}
            onPaste={(e) => {
              if (e.clipboardData.files.length) {
                e.preventDefault()
                void addFiles(e.clipboardData.files)
              }
            }}
            onKeyDown={(e) => {
              if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
                e.preventDefault()
                send()
              }
            }}
          />
          {busy ? (
            <button
              type="button"
              aria-label="Stop"
              onClick={() => abort.current?.abort()}
              className="rounded-full bg-foreground p-2 text-background hover:opacity-80"
            >
              <Square className="h-4 w-4 fill-current" />
            </button>
          ) : (
            <button
              type="button"
              aria-label="Send"
              onClick={send}
              disabled={!draft.trim() && files.length === 0}
              className="rounded-full bg-primary p-2 text-primary-foreground hover:opacity-90 disabled:opacity-30"
            >
              <ArrowUp className="h-4 w-4" />
            </button>
          )}
        </div>
        <p className="mt-1.5 px-1 text-[11px] text-muted-foreground">Enter to send, Shift+Enter for a new line.</p>
      </div>
    </div>
  )
}
