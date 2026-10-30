import { useCallback, useEffect, useState } from 'react'
import { Apple, Download, Package, Trash, X } from 'lucide-react'
import { api, download } from '../lib/api'
import { Badge, Card, Empty, ErrorBox, PageHeader, Spinner, btn, fmt, input } from '../components/ui'

type Summary = {
  kind: 'fresh' | 'packaged'; title: string
  identity: { food: string; source: string; confidence: number | null; label: string }
  freshness: { status: string; confidence: number | null; message: string } | null
  nutrition: { per_100g: Record<string, number | null> | null; basis_known: boolean; source: string | null; provenance: string | null; not_available: string[] }
  allergens: string[]; additives: string[]; precautions: string[]
  personal_alerts?: { confirmed: { name: string }[]; possible: { name: string }[] } | null
}
type Scan = { id: number; kind: 'fresh' | 'packaged'; title: string; created_at: string; summary: Summary }
const PAGE = 10

export default function HistoryPage() {
  const [q, setQ] = useState('')
  const [kind, setKind] = useState('')
  const [from, setFrom] = useState('')
  const [to, setTo] = useState('')
  const [page, setPage] = useState(1)
  const [data, setData] = useState<{ items: Scan[]; total: number } | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [open, setOpen] = useState<Scan | null>(null)

  const load = useCallback(async () => {
    setErr(null)
    const p = new URLSearchParams({ page: String(page), page_size: String(PAGE) })
    if (q.trim()) p.set('q', q.trim())
    if (kind) p.set('kind', kind)
    if (from) p.set('date_from', from)
    if (to) p.set('date_to', to)
    const r = await api<{ items: Scan[]; total: number }>(`/api/history?${p}`)
    if (r.ok) setData(r.data); else setErr(r.error.message)
  }, [q, kind, from, to, page])
  useEffect(() => { const t = setTimeout(() => void load(), 250); return () => clearTimeout(t) }, [load])

  const remove = async (id: number) => {
    if (!confirm('Delete this scan from your history?')) return
    const r = await api(`/api/history/${id}`, { method: 'DELETE' })
    if (r.ok) { setOpen(null); void load() } else setErr(r.error.message)
  }
  const pages = data ? Math.max(1, Math.ceil(data.total / PAGE)) : 1

  return (
    <>
      <PageHeader title="Scan history" subtitle="Analyses you saved. Images are not stored; only the results and their sources." />
      <Card className="mb-6">
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <div><label htmlFor="hq" className="mb-1 block text-xs font-semibold">Search</label>
            <input id="hq" className={input} value={q} onChange={(e) => { setQ(e.target.value); setPage(1) }} placeholder="Food or product name" /></div>
          <div><label htmlFor="hk" className="mb-1 block text-xs font-semibold">Category</label>
            <select id="hk" className={input} value={kind} onChange={(e) => { setKind(e.target.value); setPage(1) }}>
              <option value="">All</option><option value="fresh">Unpackaged food</option><option value="packaged">Packaged product</option></select></div>
          <div><label htmlFor="hf" className="mb-1 block text-xs font-semibold">From</label>
            <input id="hf" type="date" className={input} value={from} onChange={(e) => { setFrom(e.target.value); setPage(1) }} /></div>
          <div><label htmlFor="ht" className="mb-1 block text-xs font-semibold">To</label>
            <input id="ht" type="date" className={input} value={to} onChange={(e) => { setTo(e.target.value); setPage(1) }} /></div>
        </div>
      </Card>
      {err && <ErrorBox message={err} onRetry={load} />}
      {!data && !err && <Spinner />}
      {data && data.items.length === 0 && <Empty title={q || kind || from || to ? 'No scans match these filters' : 'No saved scans yet'}
        text="After analysing a food or a label, choose 'Save to history'." />}
      {data && data.items.length > 0 && (
        <>
          <ul className="grid gap-3">
            {data.items.map((s) => (
              <li key={s.id}>
                <button type="button" onClick={() => setOpen(s)} className="flex w-full items-center gap-4 rounded-2xl border border-emerald-900/10 bg-white p-4 text-left shadow-soft hover:border-emerald-600/40">
                  <span className="grid h-10 w-10 shrink-0 place-items-center rounded-xl bg-emerald-50">
                    {s.kind === 'fresh' ? <Apple className="h-5 w-5 text-emerald-700" aria-hidden="true" /> : <Package className="h-5 w-5 text-emerald-700" aria-hidden="true" />}
                  </span>
                  <span className="min-w-0 flex-1">
                    <span className="block truncate font-semibold">{s.title}</span>
                    <span className="block text-xs text-ink-soft">{new Date(s.created_at).toLocaleString()} · {s.summary.identity.label}</span>
                  </span>
                  {s.summary.freshness && s.summary.freshness.status !== 'not_assessed' && <Badge tone={s.summary.freshness.status === 'fresh' ? 'green' : 'amber'}>{s.summary.freshness.status.replace('_', ' ')}</Badge>}
                  {(s.summary.personal_alerts?.confirmed.length ?? 0) > 0 && <Badge tone="red">allergen alert</Badge>}
                </button>
              </li>
            ))}
          </ul>
          <nav aria-label="Pages" className="mt-4 flex items-center justify-between text-sm">
            <span className="text-ink-soft">{data.total} scan{data.total === 1 ? '' : 's'}</span>
            <span className="flex items-center gap-2">
              <button type="button" className={btn.secondary} disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</button>
              <span>Page {page} of {pages}</span>
              <button type="button" className={btn.secondary} disabled={page >= pages} onClick={() => setPage((p) => p + 1)}>Next</button>
            </span>
          </nav>
        </>
      )}
      {open && <ScanDetail scan={open} onClose={() => setOpen(null)} onDelete={() => remove(open.id)} />}
    </>
  )
}

function ScanDetail({ scan, onClose, onDelete }: { scan: Scan; onClose: () => void; onDelete: () => void }) {
  const s = scan.summary
  const [msg, setMsg] = useState<string | null>(null)
  useEffect(() => {
    const k = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
    window.addEventListener('keydown', k)
    return () => window.removeEventListener('keydown', k)
  }, [onClose])
  const pdf = async () => {
    const r = await download(`/api/reports/scans/${scan.id}`, 'report.pdf')
    if (!r.ok) setMsg(r.error.message)
  }
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-ink/30" role="dialog" aria-modal="true" aria-labelledby="scan-title" onClick={onClose}>
      <div className="h-full w-full max-w-xl overflow-y-auto bg-cream p-6 shadow-lift" onClick={(e) => e.stopPropagation()}>
        <div className="flex items-start justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide text-emerald-700">{s.kind === 'fresh' ? 'Unpackaged food' : 'Packaged product'}</p>
            <h2 id="scan-title" className="font-display text-2xl font-extrabold">{scan.title}</h2>
            <p className="text-sm text-ink-soft">{new Date(scan.created_at).toLocaleString()}</p>
          </div>
          <button type="button" onClick={onClose} className="rounded-full p-2 hover:bg-emerald-50" aria-label="Close"><X className="h-5 w-5" /></button>
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <button type="button" className={btn.primary} onClick={pdf}><Download className="h-4 w-4" aria-hidden="true" /> PDF report</button>
          <button type="button" className={btn.danger} onClick={onDelete}><Trash className="h-4 w-4" aria-hidden="true" /> Delete</button>
        </div>
        {msg && <p role="alert" className="mt-2 text-sm text-red-700">{msg}</p>}
        <dl className="mt-5 space-y-2 text-sm">
          <div><dt className="font-semibold">Identification</dt><dd className="text-ink-soft">{s.identity.label}{s.identity.confidence !== null && ` · score ${(s.identity.confidence * 100).toFixed(1)}%`}</dd></div>
          {s.freshness && <div><dt className="font-semibold">Freshness</dt><dd className="text-ink-soft">{s.freshness.message}</dd></div>}
          <div><dt className="font-semibold">Nutrition source</dt><dd className="text-ink-soft">{s.nutrition.source ?? 'Not available'}</dd></div>
        </dl>
        {s.nutrition.per_100g && (
          <table className="mt-3 w-full text-left text-sm">
            <thead><tr className="border-b border-emerald-900/10 text-xs uppercase text-ink-soft"><th className="py-1.5">Nutrient</th><th className="py-1.5">Per 100 g</th></tr></thead>
            <tbody>{Object.entries(s.nutrition.per_100g).map(([k, v]) => <tr key={k} className="border-b border-emerald-900/5"><td className="py-1.5">{k.replace(/_(kcal|g|mg)$/, '').replace(/_/g, ' ')}</td><td className="py-1.5">{fmt(v, k.split('_').pop())}</td></tr>)}</tbody>
          </table>
        )}
        {s.allergens.length > 0 && <><h3 className="mt-5 font-semibold">Allergens read</h3><p className="text-sm text-ink-soft">{s.allergens.join(', ')}</p></>}
        {s.additives.length > 0 && <><h3 className="mt-5 font-semibold">Additives</h3><p className="text-sm text-ink-soft">{s.additives.join(', ')}</p></>}
        {s.precautions.length > 0 && <><h3 className="mt-5 font-semibold">Precautions</h3><ul className="mt-1 list-disc pl-5 text-sm text-ink-soft">{s.precautions.map((p) => <li key={p}>{p}</li>)}</ul></>}
      </div>
    </div>
  )
}
