import { useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { Bot, RefreshCw, Send, Trash } from 'lucide-react'
import { Link } from 'react-router-dom'
import { chatStatus, streamChat } from '../lib/chatApi'
import type { AnalysisContext, ChatTurn } from '../lib/chatApi'
import { useSession } from '../lib/api'
import Markdown from './Markdown'

const SUGGESTIONS: Record<'none' | 'fresh' | 'packaged', string[]> = {
  none: ['What does a balanced plate look like?', 'Does an apple contain wax?', 'What does E330 mean?',
    'What is the difference between total sugar and added sugar?'],
  fresh: ['Explain these nutrition values simply', 'Which nutrient values are missing?', 'What does the freshness result mean?',
    'How does this fit a low-sugar diet?'],
  packaged: ['What are the main ingredients?', 'Explain the additives on this label', 'Is this product high in sugar?',
    'Which allergens are declared?'],
}

/** A conversation item: a chat turn, or a marker shown when the analysed food changes (earlier messages are kept). */
type Item = ChatTurn | { role: 'divider'; content: string }

export default function ChatPanel({ context }: { context: AnalysisContext | null }) {
  const [items, setItems] = useState<Item[]>([])
  const [input, setInput] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [failed, setFailed] = useState<string | null>(null)
  const [configured, setConfigured] = useState<boolean | null>(null)
  const [needsSignIn, setNeedsSignIn] = useState(false)
  const session = useSession()
  const [latency, setLatency] = useState<number | null>(null)
  const listRef = useRef<HTMLDivElement | null>(null)
  const ctxKey = context ? `${context.kind}:${context.title}:${context.status}` : 'none'
  const lastKey = useRef(ctxKey)

  useEffect(() => {
    chatStatus().then((s) => {
      setConfigured(s ? s.configured : null)
      setNeedsSignIn(s !== null && s.requiresLogin && !s.signedIn)
    })
  }, [session])
  useEffect(() => {
    if (lastKey.current === ctxKey) return
    lastKey.current = ctxKey
    setErr(null)
    setFailed(null)
    setItems((prev) => (prev.length ? [...prev, { role: 'divider', content: context ? `Now discussing: ${context.title}` : 'Analysis cleared' }] : prev))
  }, [ctxKey, context])
  useEffect(() => { listRef.current?.scrollTo({ top: listRef.current.scrollHeight, behavior: 'smooth' }) }, [items, busy, err])

  /** Only the turns after the latest topic change are sent, so answers stay about the current food. */
  const currentTurns = (list: Item[]): ChatTurn[] => {
    const lastDivider = list.map((x) => x.role).lastIndexOf('divider')
    return list.slice(lastDivider + 1).filter((x): x is ChatTurn => x.role !== 'divider' && x.content !== '')
  }

  const ask = async (text: string) => {
    const q = text.trim()
    if (!q || busy) return
    const before = items
    const history = currentTurns(before)
    setItems([...before, { role: 'user', content: q }, { role: 'assistant', content: '' }])
    setInput('')
    setBusy(true)
    setErr(null)
    setFailed(null)
    setLatency(null)
    try {
      const r = await streamChat(q, history, context, (chunk) => setItems((t) => {
        const copy = t.slice()
        const last = copy[copy.length - 1]
        copy[copy.length - 1] = { ...last, content: last.content + chunk } as Item
        return copy
      }))
      if (r.ok) {
        setItems([...before, { role: 'user', content: q }, { role: 'assistant', content: r.reply }])
        if (r.latencyMs !== undefined) setLatency(r.latencyMs)
      } else {
        setItems([...before, { role: 'user', content: q }])
        setErr(r.error.message)
        setFailed(q)
      }
    } catch {
      setItems([...before, { role: 'user', content: q }])
      setErr('The chatbot connection was interrupted.')
      setFailed(q)
    } finally {
      setBusy(false)
    }
  }

  const retry = () => {
    if (!failed) return
    const q = failed
    setItems((prev) => { // remove the unanswered question; ask() adds it again
      const idx = prev.map((x) => x.role === 'user' && x.content === q).lastIndexOf(true)
      return idx >= 0 ? prev.filter((_, i) => i !== idx) : prev
    })
    setTimeout(() => void ask(q), 0)
  }

  const submit = (e: FormEvent) => { e.preventDefault(); void ask(input) }
  const visible = items.filter((t) => t.content !== '')

  return (
    <section className="flex h-full min-h-0 flex-col rounded-3xl border border-emerald-900/10 bg-white shadow-soft" aria-labelledby="chat-heading">
      <header className="flex items-start justify-between gap-3 border-b border-emerald-900/10 px-5 py-4">
        <div className="min-w-0">
          <h2 id="chat-heading" className="flex items-center gap-2 font-display text-lg font-extrabold">
            <Bot className="h-5 w-5 text-emerald-700" aria-hidden="true" /> Ask SmartPlate
          </h2>
          <p className="mt-0.5 truncate text-xs text-ink-soft">
            {context ? <>About: <span className="font-semibold text-ink">{context.title}</span></> : 'No food analysed yet; general questions only.'}
          </p>
        </div>
        {items.length > 0 && (
          <button type="button" onClick={() => { setItems([]); setErr(null); setFailed(null) }} disabled={busy}
            className="rounded-full p-2 text-ink-soft hover:bg-emerald-50 disabled:opacity-40" aria-label="Clear conversation">
            <Trash className="h-4 w-4" />
          </button>
        )}
      </header>

      <div ref={listRef} className="min-h-0 flex-1 space-y-3 overflow-y-auto px-4 py-4 sm:px-5" aria-live="polite">
        {needsSignIn && configured !== false && (
          <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
            The chatbot uses a paid AI service, so it is available to signed-in users.{' '}
            <Link to="/signin" className="font-semibold underline">Sign in</Link> to ask questions.
          </p>
        )}
        {configured === false && (
          <p className="rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
            The AI assistant is not configured on the server (GEMINI_API_KEY missing in backend/.env). Questions that name an
            additive or a topic in SmartPlateAI's reference data (for example "What does E330 mean?") can still be answered from that data.
          </p>
        )}
        {visible.length === 0 && (
          <div className="space-y-2">
            <p className="text-sm text-ink-soft">Ask about the analysis on this page or any food, nutrition or ingredient question. Answers say when
              data is missing. Not medical advice.</p>
            {SUGGESTIONS[context?.kind ?? 'none'].map((s) => (
              <button key={s} type="button" onClick={() => void ask(s)} disabled={busy || needsSignIn}
                className="block w-full rounded-xl border border-emerald-900/10 px-3 py-2 text-left text-sm hover:bg-emerald-50 disabled:opacity-50">
                {s}
              </button>
            ))}
          </div>
        )}
        {visible.map((t, i) => t.role === 'divider' ? (
          <p key={i} className="flex items-center gap-2 py-1 text-[11px] font-semibold uppercase tracking-wide text-ink-soft">
            <span className="h-px flex-1 bg-emerald-900/10" />{t.content}<span className="h-px flex-1 bg-emerald-900/10" />
          </p>
        ) : t.role === 'user' ? (
          <div key={i} className="ml-auto w-fit max-w-[88%] whitespace-pre-wrap break-words rounded-2xl rounded-br-md bg-emerald-600 px-4 py-2.5 text-sm text-white">
            {t.content}
          </div>
        ) : (
          <div key={i} className="max-w-full rounded-2xl rounded-bl-md bg-cream px-4 py-3 text-ink sm:max-w-[94%]">
            <Markdown text={t.content} />
          </div>
        ))}
        {latency !== null && !busy && <p className="text-[11px] text-ink-soft">Answered in {(latency / 1000).toFixed(1)} s</p>}
        {busy && items[items.length - 1]?.content === '' && (
          <div role="status" className="flex items-center gap-2 text-sm text-ink-soft">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-emerald-600 border-t-transparent" /> Thinking…
          </div>
        )}
        {err && (
          <div role="alert" className="flex flex-wrap items-center gap-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
            <span className="min-w-0 flex-1">{err}</span>
            {failed && (
              <button type="button" onClick={retry} disabled={busy}
                className="inline-flex items-center gap-1 rounded-full bg-white px-3 py-1 text-xs font-semibold ring-1 ring-red-200 hover:bg-red-100 disabled:opacity-50">
                <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Retry
              </button>
            )}
          </div>
        )}
      </div>

      <form onSubmit={submit} className="flex gap-2 border-t border-emerald-900/10 p-3 sm:p-4">
        <label htmlFor="chat-input" className="sr-only">Ask a question</label>
        <input id="chat-input" value={input} onChange={(e) => setInput(e.target.value)} maxLength={2000} disabled={busy || needsSignIn}
          placeholder={busy ? 'Waiting for the answer…' : context ? `Ask about ${context.title}…` : 'Ask a nutrition question…'}
          className="min-w-0 flex-1 rounded-full border border-emerald-900/15 px-4 py-2.5 text-sm outline-none focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/15 disabled:bg-slate-50" />
        <button type="submit" disabled={busy || needsSignIn || !input.trim()} aria-label="Send"
          className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-emerald-600 text-white hover:bg-emerald-700 disabled:opacity-50">
          <Send className="h-4 w-4" />
        </button>
      </form>
    </section>
  )
}
