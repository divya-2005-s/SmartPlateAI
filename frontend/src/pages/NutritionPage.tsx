import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { Download, Pencil, Trash } from 'lucide-react'
import { api, download } from '../lib/api'
import BarChart from '../components/BarChart'
import { Badge, Card, Empty, ErrorBox, PageHeader, Spinner, btn, fmt, input, label, todayISO } from '../components/ui'

export type Total = { key: string; label: string; unit: string; total: number | null; entries_with_value: number; entries_missing: number; complete: boolean }
export type Entry = { id: number; logged_on: string; meal: string; name: string; grams: number | null; source: 'scan' | 'manual'; provenance: string;
  scan_id: number | null; amounts: Record<string, number | null>; per_100g: Record<string, number | null> | null }
export type DayData = { date: string; entries: Entry[]; totals: Total[]; notes: string[] }
export type WeekData = { start: string; end: string; days: { date: string; entry_count: number; totals: Total[] }[] }

const MANUAL_FIELDS: [string, string, string][] = [
  ['energy_kcal', 'Energy', 'kcal'], ['protein_g', 'Protein', 'g'], ['carbohydrate_g', 'Carbohydrate', 'g'], ['total_fat_g', 'Total fat', 'g'],
  ['dietary_fibre_g', 'Fibre', 'g'], ['total_sugars_g', 'Sugars', 'g'], ['sodium_mg', 'Sodium', 'mg'],
]
const MEALS = ['breakfast', 'lunch', 'dinner', 'snack', 'other']

export default function NutritionPage() {
  const [day, setDay] = useState(todayISO())
  const [data, setData] = useState<DayData | null>(null)
  const [week, setWeek] = useState<WeekData | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [metric, setMetric] = useState('energy_kcal')
  const [editing, setEditing] = useState<number | null>(null)
  const [editGrams, setEditGrams] = useState('')
  const [msg, setMsg] = useState<string | null>(null)

  const load = useCallback(async () => {
    setErr(null)
    const [d, w] = await Promise.all([api<DayData>(`/api/nutrition/day?day=${day}`), api<WeekData>(`/api/nutrition/week?end=${day}`)])
    if (d.ok) setData(d.data); else setErr(d.error.message)
    if (w.ok) setWeek(w.data)
  }, [day])
  useEffect(() => { void load() }, [load])

  const remove = async (id: number) => {
    if (!confirm('Delete this entry?')) return
    const r = await api(`/api/nutrition/entries/${id}`, { method: 'DELETE' })
    if (r.ok) void load(); else setMsg(r.error.message)
  }
  const saveGrams = async (id: number) => {
    const g = Number(editGrams)
    if (!Number.isFinite(g) || g <= 0 || g > 5000) return setMsg('Grams must be between 1 and 5000.')
    const r = await api(`/api/nutrition/entries/${id}`, { method: 'PATCH', body: { grams: g } })
    if (r.ok) { setEditing(null); void load() } else setMsg(r.error.message)
  }
  const pdf = async (period: 'day' | 'week') => {
    const r = await download(`/api/reports/nutrition?period=${period}&day=${day}`, `nutrition_${period}.pdf`)
    if (!r.ok) setMsg(r.error.message)
  }

  const metricMeta = MANUAL_FIELDS.find((f) => f[0] === metric)!
  return (
    <>
      <PageHeader title="Daily nutrition" subtitle="Foods you logged from saved scans or entered yourself. Missing values are never counted as zero."
        actions={<>
          <label htmlFor="day" className="sr-only">Date</label>
          <input id="day" type="date" value={day} max={todayISO()} onChange={(e) => e.target.value && setDay(e.target.value)} className={`${input} w-auto`} />
          <button type="button" className={btn.secondary} onClick={() => pdf('day')}><Download className="h-4 w-4" aria-hidden="true" /> Day PDF</button>
          <button type="button" className={btn.secondary} onClick={() => pdf('week')}><Download className="h-4 w-4" aria-hidden="true" /> Week PDF</button>
        </>} />
      {err && <ErrorBox message={err} onRetry={load} />}
      {msg && <p role="status" className="mb-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">{msg}</p>}
      {!data && !err && <Spinner />}
      {data && (
        <div className="grid gap-6 lg:grid-cols-[minmax(0,1fr)_22rem]">
          <div className="grid gap-6">
            <Card title={`Totals for ${new Date(day + 'T00:00').toLocaleDateString(undefined, { weekday: 'long', day: 'numeric', month: 'short' })}`}>
              <div className="overflow-x-auto">
                <table className="w-full text-left text-sm">
                  <thead><tr className="border-b border-emerald-900/10 text-xs uppercase text-ink-soft"><th className="py-2">Nutrient</th><th className="py-2">Total</th><th className="py-2">Data</th></tr></thead>
                  <tbody>
                    {data.totals.map((t) => (
                      <tr key={t.key} className="border-b border-emerald-900/5">
                        <td className="py-2">{t.label}</td>
                        <td className="py-2 tabular-nums">{t.total === null ? <span className="text-ink-soft">No data</span> : fmt(t.total, t.unit)}</td>
                        <td className="py-2">{data.entries.length === 0 ? '–' : t.complete ? <Badge>complete</Badge> : <Badge tone="amber">{t.entries_missing} of {data.entries.length} items missing</Badge>}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </Card>
            <Card title="Logged items">
              {data.entries.length === 0 ? <Empty title="Nothing logged on this day" text="Save a scan and choose 'Add to today', or add a food manually." /> : (
                <ul className="divide-y divide-emerald-900/5">
                  {data.entries.map((e) => (
                    <li key={e.id} className="py-3">
                      <div className="flex flex-wrap items-center gap-2">
                        <span className="font-semibold">{e.name}</span>
                        <Badge tone="grey">{e.meal}</Badge>
                        <Badge tone={e.source === 'manual' ? 'blue' : 'green'}>{e.source === 'manual' ? 'user-entered' : 'from scan'}</Badge>
                        <span className="ml-auto flex gap-1">
                          {e.source === 'scan' && <button type="button" className={btn.ghost} onClick={() => { setEditing(e.id); setEditGrams(String(e.grams ?? '')) }} aria-label={`Edit grams for ${e.name}`}><Pencil className="h-4 w-4" /></button>}
                          <button type="button" className={btn.ghost} onClick={() => remove(e.id)} aria-label={`Delete ${e.name}`}><Trash className="h-4 w-4" /></button>
                        </span>
                      </div>
                      <p className="text-xs text-ink-soft">{e.grams ? `${e.grams} g · ` : ''}{fmt(e.amounts.energy_kcal, 'kcal')} · source: {e.provenance}</p>
                      {editing === e.id && (
                        <div className="mt-2 flex items-center gap-2">
                          <label htmlFor={`eg-${e.id}`} className="text-xs font-semibold">Grams</label>
                          <input id={`eg-${e.id}`} className={`${input} w-28`} inputMode="decimal" value={editGrams} onChange={(x) => setEditGrams(x.target.value)} />
                          <button type="button" className={btn.primary} onClick={() => saveGrams(e.id)}>Save</button>
                          <button type="button" className={btn.ghost} onClick={() => setEditing(null)}>Cancel</button>
                        </div>
                      )}
                    </li>
                  ))}
                </ul>
              )}
            </Card>
            <Card title="Last 7 days" action={
              <select aria-label="Nutrient to chart" value={metric} onChange={(e) => setMetric(e.target.value)} className={`${input} w-auto`}>
                {MANUAL_FIELDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}
              </select>}>
              {week ? <BarChart unit={metricMeta[2]} title={metricMeta[1]} bars={week.days.map((d) => {
                const t = d.totals.find((x) => x.key === metric)
                return { label: new Date(d.date + 'T00:00').toLocaleDateString(undefined, { weekday: 'short' }), value: d.entry_count ? t?.total ?? null : null, incomplete: !!t && t.entries_missing > 0 && d.entry_count > 0 }
              })} /> : <Spinner />}
            </Card>
          </div>
          <ManualEntry day={day} onAdded={load} />
        </div>
      )}
    </>
  )
}

function ManualEntry({ day, onAdded }: { day: string; onAdded: () => void }) {
  const [name, setName] = useState('')
  const [meal, setMeal] = useState('other')
  const [vals, setVals] = useState<Record<string, string>>({})
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    const nutrients: Record<string, number> = {}
    for (const [k, v] of Object.entries(vals)) {
      if (v.trim() === '') continue
      const n = Number(v)
      if (!Number.isFinite(n) || n < 0) return setErr('Nutrient amounts must be positive numbers.')
      nutrients[k] = n
    }
    if (!name.trim()) return setErr('Enter a food name.')
    if (Object.keys(nutrients).length === 0) return setErr('Enter at least one nutrient amount. Leave unknown ones empty.')
    setBusy(true); setErr(null)
    const r = await api('/api/nutrition/entries', { method: 'POST', body: { logged_on: day, meal, name: name.trim(), nutrients, client_ref: crypto.randomUUID?.() } })
    setBusy(false)
    if (r.ok) { setName(''); setVals({}); onAdded() } else setErr(r.error.message)
  }
  return (
    <Card title="Add a food manually" className="h-fit">
      <form onSubmit={submit} className="space-y-3" noValidate>
        <div><label htmlFor="mn" className={label}>Food</label><input id="mn" className={input} value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Homemade dal, 1 bowl" /></div>
        <div><label htmlFor="mm" className={label}>Meal</label>
          <select id="mm" className={input} value={meal} onChange={(e) => setMeal(e.target.value)}>{MEALS.map((m) => <option key={m}>{m}</option>)}</select></div>
        <p className="text-xs text-ink-soft">Amounts for the portion you ate. Leave unknown values empty; they will show as missing, not zero.</p>
        <div className="grid grid-cols-2 gap-2">
          {MANUAL_FIELDS.map(([k, l, u]) => (
            <div key={k}><label htmlFor={`mv-${k}`} className="mb-1 block text-xs font-semibold">{l} ({u})</label>
              <input id={`mv-${k}`} inputMode="decimal" className={input} value={vals[k] ?? ''} onChange={(e) => setVals((v) => ({ ...v, [k]: e.target.value }))} /></div>
          ))}
        </div>
        {err && <p role="alert" className="text-sm text-red-700">{err}</p>}
        <button type="submit" className={`${btn.primary} w-full`} disabled={busy}>{busy ? 'Adding…' : 'Add entry'}</button>
      </form>
    </Card>
  )
}
