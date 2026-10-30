import { API_BASE, backendUnavailableError, readBody, responseError } from './foodApi'
import type { ApiError } from './foodApi'
import { authHeader, getSession, setSession, subscribe } from './session'
import type { SessionUser } from './session'
import { useSyncExternalStore } from 'react'

export type Result<T> = { ok: true; data: T } | { ok: false; error: ApiError }

/** JSON request to the SmartPlateAI API. Sends the auth cookie and any legacy bearer session. */
export async function api<T>(path: string, opts: { method?: string; body?: unknown; signal?: AbortSignal } = {}): Promise<Result<T>> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, {
      method: opts.method ?? 'GET',
      credentials: 'include',
      headers: { ...(opts.body !== undefined ? { 'Content-Type': 'application/json' } : {}), ...authHeader() },
      body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
      signal: opts.signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    return { ok: false, error: backendUnavailableError() }
  }
  const body = await readBody(res)
  if (res.status === 401 && getSession().token && body?.error_code === 'NOT_AUTHENTICATED') setSession(null, null)
  if (res.ok && body && body.success !== false) return { ok: true, data: body as unknown as T }
  return { ok: false, error: responseError(body, res.status) }
}

/** Downloads a file (e.g. a PDF report) with the session token and saves it in the browser. */
export async function download(path: string, fallbackName: string): Promise<{ ok: true } | { ok: false; error: ApiError }> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}${path}`, { credentials: 'include', headers: authHeader() })
  } catch {
    return { ok: false, error: backendUnavailableError() }
  }
  if (!res.ok) return { ok: false, error: responseError(await readBody(res), res.status) }
  const blob = await res.blob()
  const cd = res.headers.get('Content-Disposition') ?? ''
  const name = /filename="([^"]+)"/.exec(cd)?.[1] ?? fallbackName
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  document.body.appendChild(a)
  a.click()
  a.remove()
  setTimeout(() => URL.revokeObjectURL(url), 2000)
  return { ok: true }
}

export type AuthResponse = { success: true; token: string; expires_at: string; user: SessionUser }

export async function signIn(email: string, password: string) {
  const r = await api<AuthResponse>('/api/auth/login', { method: 'POST', body: { email, password } })
  if (r.ok) setSession(r.data.token, r.data.user)
  return r
}

export async function signUp(name: string, email: string, password: string) {
  const r = await api<AuthResponse>('/api/auth/signup', { method: 'POST', body: { name, email, password } })
  if (r.ok) setSession(r.data.token, r.data.user)
  return r
}

export async function signOut() {
  const result = await api('/api/auth/logout', { method: 'POST' })
  if (!result.ok) throw new Error(result.error.message)
  setSession(null, null)
}

export async function refreshMe() {
  if (!getSession().token) return
  const r = await api<{ success: true; user: SessionUser }>('/api/auth/me')
  if (r.ok) setSession(getSession().token, r.data.user)
}

export function useSession() {
  return useSyncExternalStore(subscribe, getSession, getSession)
}
