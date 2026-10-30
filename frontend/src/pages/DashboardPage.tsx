import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Apple, Package } from 'lucide-react'
import { api, useSession } from '../lib/api'
import BarChart from '../components/BarChart'
import { Badge, Card, Empty, ErrorBox, PageHeader, Spinner, btn, fmt, todayISO } from '../components/ui'
import type { DayData, WeekData } from './NutritionPage'

type ScanItem = { id: number; kind: 'fresh' | 'packaged'; title: string; created_at: string; summary: { identity?: { label?: string } } }

export default function DashboardPage() {
  const { user } = useSession()
  const [day, setDay] = useState<DayData | null>(null)
  const [week, setWeek] = useState<WeekData | null>(null)
  const [scans, setScans] = useState<ScanItem[] | null>(null)
  const [err, setErr] = useState<string | null>(null)

  const load = useCallback(async () => {
    setErr(null)
    const [d, w, s] = await Promise.all([
      api<DayData>(`/api/nutrition/day?day=${todayISO()}`),
      api<WeekData>(`/api/nutrition/week?end=${todayISO()}`),
      api<{ items: ScanItem[] }>('/api/history?page_size=5'),
    ])
    if (!d.ok) return setErr(d.error.message)
    setDay(d.data)
    if (w.ok) setWeek(w.data)
    if (s.ok) setScans(s.data.items)
  }, [])
  useEffect(() => { void load() }, [load])

  const pick = ['energy_kcal', 'protein_g', 'carbohydrate_g', 'total_fat_g', 'dietary_fibre_g', 'total_sugars_g', 'sodium_mg']
  return (
    <>
      <PageHeader title={`Hello${user ? `, ${user.name.split(' ')[0]}` : ''}`} subtitle="Today's logged nutrition and your recent scans. Everything here comes from your own saved data."
        actions={<><Link to="/analyze" className={btn.primary}><Apple className="h-4 w-4" aria-hidden="true" /> Analyse food</Link>
          <Link to="/scan-packaged" className={btn.secondary}><Package className="h-4 w-4" aria-hidden="true" /> Scan a label</Link></>} />
      {err && <ErrorBox message={err} onRetry={load} />}
      {!day && !err && <Spinner />}
      {day && (
        <div className="grid gap-6">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            {pick.map((k) => {
              const t = day.totals.find((x) => x.key === k)
              if (!t) return null
              return (
                <div key={k} className="rounded-2xl border border-emerald-900/10 bg-white p-4 shadow-soft">
                  <p className="text-xs font-semibold uppercase tracking-wide text-ink-soft">{t.label}</p>
                  <p className="mt-1 font-display text-2xl font-extrabold tabular-nums">{t.total === null ? '–' : Math.round(t.total * 10) / 10}</p>
                  <p className="text-xs text-ink-soft">{t.unit}{t.entries_missing > 0 && day.entries.length > 0 && <Badge tone="amber">incomplete</Badge>}</p>
                </div>
              )
            })}
          </div>
          {day.entries.length === 0 && <Empty title="Nothing logged today" text="Analyse a food, save it, then use 'Add to today', or add a food manually on the Daily nutrition page."
            action={<Link to="/nutrition" className={btn.secondary}>Open daily nutrition</Link>} />}
          <div className="grid gap-6 lg:grid-cols-2">
            <Card title="Energy this week">
              {week ? <BarChart unit="kcal" title="Energy" bars={week.days.map((d) => {
                const t = d.totals.find((x) => x.key === 'energy_kcal')
                return { label: new Date(d.date + 'T00:00').toLocaleDateString(undefined, { weekday: 'short' }), value: d.entry_count ? t?.total ?? null : null, incomplete: !!t && t.entries_missing > 0 && d.entry_count > 0 }
              })} /> : <Spinner />}
            </Card>
            <Card title="Recent scans" action={<Link to="/history" className={btn.ghost}>View all</Link>}>
              {!scans ? <Spinner /> : scans.length === 0 ? <Empty title="No saved scans yet" text="Use 'Save to history' after analysing a food or label." /> : (
                <ul className="divide-y divide-emerald-900/5">
                  {scans.map((s) => (
                    <li key={s.id} className="flex items-center gap-3 py-2.5">
                      {s.kind === 'fresh' ? <Apple className="h-4 w-4 text-emerald-700" aria-hidden="true" /> : <Package className="h-4 w-4 text-emerald-700" aria-hidden="true" />}
                      <span className="min-w-0 flex-1"><span className="block truncate font-semibold">{s.title}</span>
                        <span className="text-xs text-ink-soft">{new Date(s.created_at).toLocaleString()} · {s.summary.identity?.label}</span></span>
                    </li>
                  ))}
                </ul>
              )}
            </Card>
          </div>
          <p className="text-xs text-ink-soft">Totals add only known values ({fmt(day.entries.length)} items today). 'Incomplete' means some items have no value for that nutrient.</p>
        </div>
      )}
    </>
  )
}
