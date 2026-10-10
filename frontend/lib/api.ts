/**
 * Single entry point for every API call, mirroring the `lib/webhooks.ts`
 * convention in gc-website.
 *
 * Auth is a httpOnly session cookie set by the API, so every request needs
 * `credentials: 'include'` -- the API and the frontend are different origins in
 * development (:8000 vs :3000).
 */
// Unset -> the API on localhost:8000 (local dev). "/" -> same origin: calls go
// to /api/v1 on the Next server, which forwards them (see next.config.js).
const configured = process.env.NEXT_PUBLIC_API_URL
export const API_URL =
  configured === undefined || configured === '' ? 'http://localhost:8000' : configured.replace(/\/$/, '')

export class ApiError extends Error {
  status: number
  constructor(message: string, status: number) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const isForm = init.body instanceof FormData

  const response = await fetch(`${API_URL}/api/v1${path}`, {
    ...init,
    credentials: 'include',
    headers: {
      ...(isForm ? {} : { 'Content-Type': 'application/json' }),
      ...(init.headers || {}),
    },
  })

  if (response.status === 204) return undefined as T

  const text = await response.text()
  let payload: any = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    payload = text
  }

  if (!response.ok) {
    // FastAPI puts the message in `detail`; it can be a string or a list of
    // validation errors.
    const detail = payload?.detail
    const message =
      typeof detail === 'string'
        ? detail
        : Array.isArray(detail)
          ? detail.map((d: any) => d.msg || JSON.stringify(d)).join('; ')
          : `Request failed (${response.status})`
    throw new ApiError(message, response.status)
  }

  return payload as T
}

/**
 * POST and read a server-sent event stream, calling `onEvent` for each event as
 * it arrives. Errors before the stream starts throw like `api`; errors during it
 * arrive as events.
 */
export async function streamPost<E>(
  path: string,
  body: unknown,
  onEvent: (event: E) => void,
  signal?: AbortSignal,
): Promise<void> {
  const response = await fetch(`${API_URL}/api/v1${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
    signal,
  })
  if (!response.ok || !response.body) {
    let detail = ''
    try {
      detail = (await response.json())?.detail
    } catch {}
    throw new ApiError(typeof detail === 'string' && detail ? detail : `Request failed (${response.status})`, response.status)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  for (;;) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      const data = part
        .split('\n')
        .filter((line) => line.startsWith('data:'))
        .map((line) => line.slice(5).trim())
        .join('')
      if (data) onEvent(JSON.parse(data) as E)
    }
  }
}

export const api = {
  get: <T>(path: string) => request<T>(path),
  post: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'POST', body: body === undefined ? undefined : JSON.stringify(body) }),
  put: <T>(path: string, body?: unknown) =>
    request<T>(path, { method: 'PUT', body: body === undefined ? undefined : JSON.stringify(body) }),
  del: <T>(path: string) => request<T>(path, { method: 'DELETE' }),
  upload: <T>(path: string, form: FormData) =>
    request<T>(path, { method: 'POST', body: form }),
}

export function exportUrl(uploadId: string, kind: string): string {
  return `${API_URL}/api/v1/exports/${uploadId}?kind=${kind}`
}
