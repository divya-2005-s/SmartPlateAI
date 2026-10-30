import { useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Plus, Search, X } from 'lucide-react'
import { api } from '../lib/api'
import { searchProducts } from '../lib/packagedApi'
import type { Candidate } from '../lib/packagedApi'
import { Badge, Card, Empty, ErrorBox, PageHeader, Spinner, btn, fmt, input } from '../components/ui'

type Col = { id: string; name: string; brand: string | null; basis: string; comparable: boolean; values: Record<string, number | null>;
  values_as_stored: Record<string, number | null> | null; ingredients_text: string | null; additives: string[]; allergens_detected: string[]; price: number | null
  personal_alerts: { confirmed: { name: string }[]; possible: { name: string }[] } | null }
type Result = { products: Col[]; rows: { key: string; lowest: number | null; highest: number | null; missing_for: string[] }[];
  findings: { priority: string; text: string; best: string[] }[]; notes: string[]; priority_options: Record<string, string> }
const LABELS: Record<string, [string, string, 'low' | 'high' | null]> = {
  energy_kcal: ['Energy', 'kcal', 'low'], protein_g: ['Protein', 'g', 'high'], carbohydrate_g: ['Carbohydrate', 'g', null], total_sugars_g: ['Sugars', 'g', 'low'],
  total_fat_g: ['Total fat', 'g', 'low'], saturated_fat_g: ['Saturated fat', 'g', 'low'], dietary_fibre_g: ['Fibre', 'g', 'high'], sodium_mg: ['Sodium', 'mg', 'low'],
}

export default function ComparePage() {
  const [q, setQ] = useState('')
  const [results, setResults] = useState<Candidate[] | null>(null)
  const [picked, setPicked] = useState<Candidate[]>([])
  const [priorities, setPriorities] = useState<string[]>(['lower_sodium', 'lower_sugar'])
  const [options, setOptions] = useState<Record<string, string>>({})
  const [data, setData] = useState<Result | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)

  useEffect(() => { void api<{ priorities: Record<string, string> }>('/api/packaged/compare/options').then((r) => r.ok && setOptions(r.data.priorities)) }, [])
  useEffect(() => {
    if (picked.length < 2) { setData(null); return }
    setBusy(true); setErr(null)
    const ids = picked.map((p) => encodeURIComponent(p.id)).join(',')
    void api<Result>(`/api/packaged/compare?ids=${ids}&priorities=${priorities.join(',')}`).then((r) => {
      setBusy(false)
      if (r.ok) setData(r.data); else setErr(r.error.message)
    })
  }, [picked, priorities])

  const search = async (e: FormEvent) => {
    e.preventDefault()
    if (q.trim().length < 2) return
    const r = await searchProducts(q.trim())
    if (r.ok) setResults(r.data.results); else setErr(r.error.message)
  }
  const add = (c: Candidate) => setPicked((p) => (p.some((x) => x.id === c.id) || p.length >= 4 ? p : [...p, c]))

  return (
    <>
      <PageHeader title="Product comparison" subtitle="Compare 2 to 4 packaged products from the dataset per 100 g. Choose what matters to you; there is no single 'healthiest' ranking." />
      <div className="grid gap-6 lg:grid-cols-[20rem_minmax(0,1fr)]">
        <div className="grid h-fit gap-6">
          <Card title="Add products">
            <form onSubmit={search} className="flex gap-2">
              <label htmlFor="cq" className="sr-only">Search products</label>
              <input id="cq" className={input} value={q} onChange={(e) => setQ(e.target.value)} placeholder="e.g. biscuits" />
              <button type="submit" className={btn.primary} aria-label="Search"><Search className="h-4 w-4" /></button>
            </form>
            {results && results.length === 0 && <p className="mt-3 text-sm text-ink-soft">No products found.</p>}
            {results && results.length > 0 && (
              <ul className="mt-3 max-h-72 divide-y divide-emerald-900/5 overflow-y-auto">
                {results.map((r) => (
                  <li key={r.id} className="flex items-center gap-2 py-2 text-sm">
                    <span className="min-w-0 flex-1"><span className="font-semibold">{r.name}</span>{r.brand && <span className="text-ink-soft"> · {r.brand}</span>}</span>
                    <button type="button" className={btn.ghost} onClick={() => add(r)} disabled={picked.length >= 4 || picked.some((p) => p.id === r.id)} aria-label={`Add ${r.name}`}><Plus className="h-4 w-4" /></button>
                  </li>
                ))}
              </ul>
            )}
            {picked.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-2">
                {picked.map((p) => (
                  <span key={p.id} className="inline-flex items-center gap-1 rounded-full bg-emerald-50 py-1 pl-3 pr-1 text-sm">
                    {p.name}
                    <button type="button" onClick={() => setPicked((x) => x.filter((y) => y.id !== p.id))} className="rounded-full p-1 hover:bg-emerald-100" aria-label={`Remove ${p.name}`}><X className="h-3.5 w-3.5" /></button>
                  </span>
                ))}
              </div>
            )}
          </Card>
          <Card title="Your priorities">
            <fieldset className="space-y-2"><legend className="sr-only">Priorities</legend>
              {Object.entries(options).map(([k, v]) => (
                <label key={k} className="flex items-center gap-2 text-sm">
                  <input type="checkbox" className="accent-emerald-700" checked={priorities.includes(k)}
                    onChange={(e) => setPriorities((p) => (e.target.checked ? [...p, k] : p.filter((x) => x !== k)))} />
                  {v.charAt(0).toUpperCase() + v.slice(1)}
                </label>
              ))}
            </fieldset>
          </Card>
        </div>
        <div>
          {err && <ErrorBox message={err} />}
          {picked.length < 2 && <Empty title="Choose at least two products" text="Search on the left and add 2 to 4 products." />}
          {busy && <Spinner label="Comparing…" />}
          {data && !busy && (
            <div className="grid gap-6">
              {data.findings.length > 0 && (
                <Card title="What differs">
                  <ul className="space-y-2 text-sm">{data.findings.map((f) => <li key={f.priority} className="rounded-xl bg-cream p-3">{f.text}</li>)}</ul>
                </Card>
              )}
              <Card>
                <div className="overflow-x-auto">
                  <table className="w-full min-w-[36rem] text-left text-sm">
                    <thead>
                      <tr className="border-b border-emerald-900/10 align-bottom">
                        <th className="py-2 pr-3 text-xs uppercase text-ink-soft">Per 100 g</th>
                        {data.products.map((p) => <th key={p.id} className="py-2 pr-3"><span className="font-semibold">{p.name}</span>
                          <span className="block text-xs font-normal text-ink-soft">{p.brand}</span>{!p.comparable && <Badge tone="amber">basis unknown</Badge>}</th>)}
                      </tr>
                    </thead>
                    <tbody>
                      {data.rows.map((r) => {
                        const [lab, unit, better] = LABELS[r.key]
                        return (
                          <tr key={r.key} className="border-b border-emerald-900/5">
                            <td className="py-2 pr-3">{lab} <span className="text-xs text-ink-soft">({unit})</span></td>
                            {data.products.map((p) => {
                              const v = p.values[r.key]
                              const best = v !== null && better && r.lowest !== r.highest && ((better === 'low' && v === r.lowest) || (better === 'high' && v === r.highest))
                              return <td key={p.id} className={`py-2 pr-3 tabular-nums ${best ? 'font-semibold text-emerald-800' : ''}`}>{v === null ? <span className="text-xs text-ink-soft">not comparable</span> : fmt(v)}</td>
                            })}
                          </tr>
                        )
                      })}
                      <tr className="border-b border-emerald-900/5 align-top"><td className="py-2 pr-3">Additives</td>{data.products.map((p) => <td key={p.id} className="py-2 pr-3 text-xs">{p.additives.length ? p.additives.map((a) => `INS ${a}`).join(', ') : 'None recorded'}</td>)}</tr>
                      <tr className="border-b border-emerald-900/5 align-top"><td className="py-2 pr-3">Allergens (from text)</td>{data.products.map((p) => <td key={p.id} className="py-2 pr-3 text-xs">
                        {p.allergens_detected.length ? p.allergens_detected.join(', ') : 'None found in available text'}
                        {(p.personal_alerts?.confirmed.length ?? 0) > 0 && <span className="mt-1 block"><Badge tone="red">contains your allergen</Badge></span>}</td>)}</tr>
                      <tr className="align-top"><td className="py-2 pr-3">Price</td>{data.products.map((p) => <td key={p.id} className="py-2 pr-3 text-xs">{p.price !== null ? `₹${p.price}` : 'Not in dataset'}</td>)}</tr>
                    </tbody>
                  </table>
                </div>
                <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-ink-soft">{data.notes.map((n) => <li key={n}>{n}</li>)}</ul>
              </Card>
            </div>
          )}
        </div>
      </div>
    </>
  )
}
