import { API_BASE, backendUnavailableError, readBody, responseError } from './foodApi'
import type { ApiError } from './foodApi'
import { authHeader } from './session'

export type ChatTurn = { role: 'user' | 'assistant'; content: string }
/** A compact, factual summary of the current analysis. Sent to the backend, which passes it to Gemini as data. */
export type AnalysisContext = { kind: 'fresh' | 'packaged'; title: string; status: string; [key: string]: unknown }

export async function sendChat(message: string, history: ChatTurn[], context: AnalysisContext | null, signal?: AbortSignal):
  Promise<{ ok: true; reply: string } | { ok: false; error: ApiError }> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/chat`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({ message, history: history.slice(-10), context }),
      signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    return { ok: false, error: backendUnavailableError() }
  }
  const body = await readBody(res)
  if (res.ok && body && body.success === true && typeof body.reply === 'string') return { ok: true, reply: body.reply }
  return { ok: false, error: responseError(body, res.status) }
}

/** requiresLogin: the server allows the chatbot (a paid AI service) to signed-in users only (public deployment). */
export type ChatStatus = { configured: boolean; requiresLogin: boolean; signedIn: boolean }

export async function chatStatus(): Promise<ChatStatus | null> {
  try {
    const res = await fetch(`${API_BASE}/api/chat/status`, { credentials: 'include', headers: authHeader() })
    const body = await readBody(res)
    return res.ok && body
      ? { configured: body.configured === true, requiresLogin: body.requires_login === true, signedIn: body.signed_in === true }
      : null
  } catch {
    return null
  }
}

/** Streams the answer (server-sent events) and calls onChunk with each text piece. Errors before streaming starts come back as normal API errors. */
export async function streamChat(message: string, history: ChatTurn[], context: AnalysisContext | null, onChunk: (t: string) => void,
  signal?: AbortSignal): Promise<{ ok: true; reply: string; latencyMs?: number } | { ok: false; error: ApiError }> {
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/chat/stream`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify({ message, history: history.slice(-10), context }),
      signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    return { ok: false, error: backendUnavailableError() }
  }
  if (!res.ok || !res.body || !(res.headers.get('content-type') ?? '').includes('text/event-stream')) {
    const body = await readBody(res)
    return { ok: false, error: responseError(body, res.status) }
  }
  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buf = ''
  let reply = ''
  let latencyMs: number | undefined
  for (;;) {
    const { value, done } = await reader.read()
    if (done) break
    buf += decoder.decode(value, { stream: true })
    let idx
    while ((idx = buf.indexOf('\n\n')) >= 0) {
      const block = buf.slice(0, idx)
      buf = buf.slice(idx + 2)
      const event = /^event: (.+)$/m.exec(block)?.[1]
      const dataLine = /^data: (.+)$/m.exec(block)?.[1]
      if (!dataLine) continue
      let data: Record<string, unknown>
      try { data = JSON.parse(dataLine) as Record<string, unknown> } catch { continue }
      if (event === 'chunk' && typeof data.text === 'string') { reply += data.text; onChunk(data.text) }
      else if (event === 'done' && typeof data.latency_ms === 'number') latencyMs = data.latency_ms
      else if (event === 'error') return { ok: false, error: { code: String(data.error_code ?? 'CHAT_INTERRUPTED'), message: String(data.message ?? 'The answer was interrupted.') } }
    }
  }
  return reply ? { ok: true, reply, latencyMs } : { ok: false, error: { code: 'CHAT_EMPTY_REPLY', message: 'The chatbot returned no answer. Please try again.' } }
}
