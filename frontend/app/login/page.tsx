'use client'

import { Sparkles } from 'lucide-react'
import { useRouter } from 'next/navigation'
import { useState } from 'react'

import { Alert, Button, Card, Field, Input } from '@/components/ui'
import { api } from '@/lib/api'

export default function LoginPage() {
  const router = useRouter()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  async function submit(event: React.FormEvent) {
    event.preventDefault()
    setBusy(true)
    setError(null)
    try {
      await api.post('/auth/login', { email, password })
      router.push('/overview')
      router.refresh()
    } catch (err: any) {
      setError(err.message)
      setBusy(false)
    }
  }

  return (
    <main className="relative flex min-h-screen items-center justify-center overflow-hidden p-6">
      <div
        className="pointer-events-none absolute left-1/2 top-0 h-[480px] w-[720px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-primary/15 blur-3xl"
        aria-hidden
      />

      <div className="relative w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center text-center">
          <span className="flex h-11 w-11 items-center justify-center rounded-xl bg-primary text-primary-foreground shadow-lg shadow-primary/30">
            <Sparkles className="h-5 w-5" strokeWidth={2.5} />
          </span>
          <h1 className="mt-4 text-xl font-semibold tracking-tight">Personalization Engine</h1>
          <p className="mt-1 text-sm text-muted-foreground">Sign in to continue.</p>
        </div>

        <Card className="p-6 shadow-pop">
          <form onSubmit={submit} className="space-y-4">
            <Field id="email" label="Email">
              <Input
                id="email"
                type="email"
                autoComplete="username"
                autoFocus
                required
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>

            <Field id="password" label="Password">
              <Input
                id="password"
                type="password"
                autoComplete="current-password"
                required
                value={password}
                onChange={(e) => setPassword(e.target.value)}
              />
            </Field>

            {error && <Alert>{error}</Alert>}

            <Button type="submit" className="w-full" size="lg" loading={busy}>
              {busy ? 'Signing in' : 'Sign in'}
            </Button>
          </form>
        </Card>

        <p className="mt-6 text-center text-xs leading-relaxed text-muted-foreground">
          Accounts are created by an operator:
          <code className="mt-1.5 block rounded-md border border-border bg-muted px-2 py-1.5 font-mono text-[11px] text-foreground/80">
            docker compose exec api python scripts/create_operator.py you@bighammer.ai
          </code>
        </p>
      </div>
    </main>
  )
}
