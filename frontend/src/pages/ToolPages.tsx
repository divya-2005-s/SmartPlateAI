import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { Download, LogOut } from 'lucide-react'
import { api, download, refreshMe, useSession } from '../lib/api'
import { setSession, setUser } from '../lib/session'
import type { SessionUser } from '../lib/session'
import { useAuth } from '../components/AuthProvider'
import { useCurrentAnalysis } from '../lib/analysisContext'
import ChatPanel from '../components/ChatPanel'
import { ChemicalTable } from '../components/AnalysisExtras'
import type { ChemicalProfile } from '../components/AnalysisExtras'
import { getSupportedFoods } from '../lib/foodApi'
import { Badge, Card, Empty, ErrorBox, PageHeader, Spinner, btn, input, label, todayISO } from '../components/ui'

/* ================================================================== BMI */
type BMIResult = { bmi: number; category: string | null; indian_category?: string; adult_categories_apply: boolean; interpretation: string;
  healthy_weight_range_kg?: [number, number]; note_asian_indian?: string; age_note?: string; disclaimer: string }

export function BMIPage() {
  const [units, setUnits] = useState<'metric' | 'imperial'>('metric')
  const [cm, setCm] = useState(''); const [kg, setKg] = useState('')
  const [ft, setFt] = useState(''); const [inch, setInch] = useState(''); const [lb, setLb] = useState('')
  const [age, setAge] = useState('')
  const [res, setRes] = useState<BMIResult | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const num = (s: string) => (s.trim() === '' ? undefined : Number(s))
  const submit = async (e: FormEvent) => {
    e.preventDefault()
    setErr(null); setRes(null)
    const body = units === 'metric' ? { height_cm: num(cm), weight_kg: num(kg) } : { height_ft: num(ft), height_in: num(inch) ?? 0, weight_lb: num(lb) }
    if (Object.values(body).some((v) => v !== undefined && !Number.isFinite(v))) return setErr('Use numbers only.')
    const r = await api<BMIResult>('/api/tools/bmi', { method: 'POST', body: { ...body, age: num(age) } })
    if (r.ok) setRes(r.data); else setErr(r.error.message)
  }
  return (
    <>
      <PageHeader title="BMI calculator" subtitle="Body mass index is a quick screening measure. It is not a diagnosis and is never estimated from food photos." />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <form onSubmit={submit} className="space-y-4" noValidate>
            <div role="radiogroup" aria-label="Units" className="flex gap-2">
              {(['metric', 'imperial'] as const).map((u) => <button key={u} type="button" role="radio" aria-checked={units === u} onClick={() => setUnits(u)}
                className={`rounded-full px-4 py-1.5 text-sm font-semibold ${units === u ? 'bg-emerald-600 text-white' : 'ring-1 ring-emerald-900/15 hover:bg-emerald-50'}`}>{u === 'metric' ? 'cm / kg' : 'ft, in / lb'}</button>)}
            </div>
            {units === 'metric' ? (
              <div className="grid grid-cols-2 gap-3">
                <div><label htmlFor="b-cm" className={label}>Height (cm)</label><input id="b-cm" inputMode="decimal" className={input} value={cm} onChange={(e) => setCm(e.target.value)} /></div>
                <div><label htmlFor="b-kg" className={label}>Weight (kg)</label><input id="b-kg" inputMode="decimal" className={input} value={kg} onChange={(e) => setKg(e.target.value)} /></div>
              </div>
            ) : (
              <div className="grid grid-cols-3 gap-3">
                <div><label htmlFor="b-ft" className={label}>Feet</label><input id="b-ft" inputMode="decimal" className={input} value={ft} onChange={(e) => setFt(e.target.value)} /></div>
                <div><label htmlFor="b-in" className={label}>Inches</label><input id="b-in" inputMode="decimal" className={input} value={inch} onChange={(e) => setInch(e.target.value)} /></div>
                <div><label htmlFor="b-lb" className={label}>Pounds</label><input id="b-lb" inputMode="decimal" className={input} value={lb} onChange={(e) => setLb(e.target.value)} /></div>
              </div>
            )}
            <div><label htmlFor="b-age" className={label}>Age in years (recommended)</label><input id="b-age" inputMode="numeric" className={input} value={age} onChange={(e) => setAge(e.target.value)} />
              <p className="mt-1 text-xs text-ink-soft">Adult categories apply from age 20. Younger people need age-specific growth charts.</p></div>
            {err && <p role="alert" className="text-sm text-red-700">{err}</p>}
            <button type="submit" className={btn.primary}>Calculate</button>
          </form>
        </Card>
        <Card title="Result">
          {!res ? <p className="text-sm text-ink-soft">Enter your height and weight.</p> : (
            <div aria-live="polite">
              <p className="font-display text-5xl font-extrabold tabular-nums">{res.bmi}</p>
              {res.category && <p className="mt-1"><Badge tone={res.category === 'Healthy weight' ? 'green' : 'amber'}>{res.category}</Badge> <span className="text-xs text-ink-soft">WHO adult category</span></p>}
              <p className="mt-3 text-sm">{res.interpretation}</p>
              {res.healthy_weight_range_kg && <p className="mt-2 text-sm text-ink-soft">A BMI of 18.5–24.9 at your height corresponds to about {res.healthy_weight_range_kg[0]}–{res.healthy_weight_range_kg[1]} kg.</p>}
              {res.note_asian_indian && <p className="mt-2 text-sm text-ink-soft">{res.note_asian_indian} By those cut-offs: <span className="font-semibold">{res.indian_category}</span>.</p>}
              {res.age_note && <p className="mt-2 text-xs text-ink-soft">{res.age_note}</p>}
              <p className="mt-4 rounded-xl bg-cream p-3 text-xs text-ink-soft">{res.disclaimer}</p>
            </div>
          )}
        </Card>
      </div>
    </>
  )
}

/* ================================================================== Chatbot */
export function ChatPage() {
  const ctx = useCurrentAnalysis()
  return (
    <>
      <PageHeader title="AI chatbot" subtitle={ctx ? 'Answers use your most recent analysis on the Analyse page, and say when data is missing.' : 'Analyse a food first to ask about it, or ask a general nutrition question.'} />
      <div className="h-[calc(100vh-14rem)] min-h-[28rem]"><ChatPanel context={ctx} /></div>
    </>
  )
}

/* ================================================================== Reports */
type ScanLite = { id: number; kind: string; title: string; created_at: string }
export function ReportsPage() {
  const [scans, setScans] = useState<ScanLite[] | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [day, setDay] = useState(todayISO())
  const [busy, setBusy] = useState<string | null>(null)
  const load = useCallback(async () => {
    const r = await api<{ items: ScanLite[] }>('/api/history?page_size=50')
    if (r.ok) setScans(r.data.items); else setErr(r.error.message)
  }, [])
  useEffect(() => { void load() }, [load])
  const get = async (key: string, path: string) => {
    setBusy(key); setErr(null)
    const r = await download(path, 'report.pdf')
    setBusy(null)
    if (!r.ok) setErr(r.error.message)
  }
  return (
    <>
      <PageHeader title="Reports" subtitle="PDF reports generated from your saved data. Reference data, package-label values and missing information are labelled." />
      {err && <div className="mb-4"><ErrorBox message={err} /></div>}
      <div className="grid gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <Card title="Nutrition summary" className="h-fit">
          <label htmlFor="r-day" className={label}>Date</label>
          <input id="r-day" type="date" className={input} value={day} max={todayISO()} onChange={(e) => e.target.value && setDay(e.target.value)} />
          <div className="mt-3 flex flex-wrap gap-2">
            <button type="button" className={btn.primary} disabled={busy !== null} onClick={() => get('day', `/api/reports/nutrition?period=day&day=${day}`)}><Download className="h-4 w-4" aria-hidden="true" /> Daily</button>
            <button type="button" className={btn.secondary} disabled={busy !== null} onClick={() => get('week', `/api/reports/nutrition?period=week&day=${day}`)}><Download className="h-4 w-4" aria-hidden="true" /> 7 days</button>
          </div>
        </Card>
        <Card title="Scan reports">
          {!scans ? <Spinner /> : scans.length === 0 ? <Empty title="No saved scans" text="Save an analysis to create its report. Unpackaged-food reports include nutrition and chemical reference data." /> : (
            <ul className="divide-y divide-emerald-900/5">{scans.map((s) => (
              <li key={s.id} className="flex items-center gap-3 py-2.5 text-sm">
                <span className="min-w-0 flex-1"><span className="block truncate font-semibold">{s.title}</span><span className="text-xs text-ink-soft">{s.kind === 'fresh' ? 'Unpackaged food, nutrition and chemical report' : 'Packaged product report'} · {new Date(s.created_at).toLocaleDateString()}</span></span>
                <button type="button" className={btn.secondary} disabled={busy !== null} onClick={() => get(`s${s.id}`, `/api/reports/scans/${s.id}`)}><Download className="h-4 w-4" aria-hidden="true" /> {busy === `s${s.id}` ? 'Preparing…' : 'PDF'}</button>
              </li>))}</ul>
          )}
        </Card>
      </div>
    </>
  )
}

/* ================================================================== Allergen preferences */
type Pref = { allergen: string; severity: 'avoid' | 'severe' }
export function AllergensPage() {
  const [options, setOptions] = useState<{ key: string; name: string }[] | null>(null)
  const [prefs, setPrefs] = useState<Record<string, Pref['severity']>>({})
  const [msg, setMsg] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  const load = useCallback(async () => {
    const [o, p] = await Promise.all([api<{ allergens: { key: string; name: string }[] }>('/api/allergens/options'), api<{ allergens: Pref[] }>('/api/allergens/preferences')])
    if (o.ok) setOptions(o.data.allergens); else setErr(o.error.message)
    if (p.ok) setPrefs(Object.fromEntries(p.data.allergens.map((a) => [a.allergen, a.severity])))
  }, [])
  useEffect(() => { void load() }, [load])
  const save = async () => {
    setBusy(true); setMsg(null); setErr(null)
    const r = await api('/api/allergens/preferences', { method: 'PUT', body: { allergens: Object.entries(prefs).map(([allergen, severity]) => ({ allergen, severity })) } })
    setBusy(false)
    if (r.ok) setMsg('Saved. Packaged-food scans, product comparisons and meal plans will check these.'); else setErr(r.error.message)
  }
  return (
    <>
      <PageHeader title="Allergen preferences" subtitle="Choose allergens to watch for. Only you can see these." />
      {err && <ErrorBox message={err} onRetry={load} />}
      {!options && !err && <Spinner />}
      {options && (
        <Card>
          <ul className="grid gap-2 sm:grid-cols-2">
            {options.map((o) => {
              const on = o.key in prefs
              return (
                <li key={o.key} className={`flex items-center gap-3 rounded-xl border px-4 py-3 ${on ? 'border-emerald-600 bg-emerald-50/60' : 'border-emerald-900/10'}`}>
                  <input id={`al-${o.key}`} type="checkbox" className="h-4 w-4 accent-emerald-700" checked={on}
                    onChange={(e) => setPrefs((p) => { const n = { ...p }; if (e.target.checked) n[o.key] = 'avoid'; else delete n[o.key]; return n })} />
                  <label htmlFor={`al-${o.key}`} className="flex-1 font-semibold">{o.name}</label>
                  {on && (
                    <select aria-label={`Severity for ${o.name}`} value={prefs[o.key]} onChange={(e) => setPrefs((p) => ({ ...p, [o.key]: e.target.value as Pref['severity'] }))}
                      className="rounded-lg border border-emerald-900/15 bg-white px-2 py-1 text-sm">
                      <option value="avoid">Avoid</option><option value="severe">Severe allergy</option>
                    </select>
                  )}
                </li>
              )
            })}
          </ul>
          <div className="mt-5 flex flex-wrap items-center gap-3">
            <button type="button" className={btn.primary} onClick={save} disabled={busy}>{busy ? 'Saving…' : 'Save preferences'}</button>
            {msg && <p role="status" className="text-sm text-emerald-800">{msg}</p>}
          </div>
          <p className="mt-4 rounded-xl bg-cream p-3 text-xs text-ink-soft">SmartPlateAI can only check what is written on a label or in a database. It cannot detect traces or cross-contamination, and missing information never means a product is allergen-free.</p>
        </Card>
      )}
    </>
  )
}

/* ================================================================== Chemical intelligence */
export function ChemicalPage() {
  const [foods, setFoods] = useState<string[] | null>(null)
  const [food, setFood] = useState('')
  const [data, setData] = useState<ChemicalProfile | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [busy, setBusy] = useState(false)
  useEffect(() => { void getSupportedFoods().then((f) => (f ? setFoods(f) : setErr('The list of supported foods could not be loaded. Is the food model installed and the backend running?'))) }, [])
  useEffect(() => {
    if (!food) return
    setBusy(true); setData(null); setErr(null)
    void api<ChemicalProfile>(`/api/chemical/${encodeURIComponent(food)}`).then((r) => { setBusy(false); if (r.ok) setData(r.data); else setErr(r.error.message) })
  }, [food])
  return (
    <>
      <PageHeader title="Chemical intelligence" subtitle="Notable compounds in supported foods, with PubChem identities and USDA amounts where available. Reference composition, not a measurement of your food." />
      <Card className="mb-6">
        <label htmlFor="ch-food" className={label}>Food</label>
        <select id="ch-food" className={`${input} max-w-sm`} value={food} onChange={(e) => setFood(e.target.value)} disabled={!foods}>
          <option value="">{foods ? 'Choose a food…' : 'Loading…'}</option>
          {foods?.map((f) => <option key={f}>{f}</option>)}
        </select>
      </Card>
      {err && <ErrorBox message={err} />}
      {busy && <Spinner label="Looking up compounds…" />}
      {data && <Card title={data.food}><ChemicalTable data={data} /></Card>}
    </>
  )
}

/* ================================================================== Profile */
export function ProfilePage() {
  const { user } = useSession()
  const { signOut: logOut } = useAuth()
  const navigate = useNavigate()
  const [name, setName] = useState(''); const [year, setYear] = useState('')
  const [prefs, setPrefs] = useState(''); const [dislikes, setDislikes] = useState('')
  const [msg, setMsg] = useState<string | null>(null); const [err, setErr] = useState<string | null>(null)
  const [cur, setCur] = useState(''); const [next, setNext] = useState(''); const [pwMsg, setPwMsg] = useState<string | null>(null)
  const [delPw, setDelPw] = useState('')
  useEffect(() => { void refreshMe() }, [])
  useEffect(() => {
    if (!user) return
    setName(user.name); setYear(user.birth_year ? String(user.birth_year) : '')
    setPrefs(user.dietary_preferences.join(', ')); setDislikes(user.disliked_foods.join(', '))
  }, [user])
  const save = async (e: FormEvent) => {
    e.preventDefault(); setMsg(null); setErr(null)
    const y = year.trim() ? Number(year) : null
    if (y !== null && (!Number.isInteger(y) || y < 1900 || y > new Date().getFullYear())) return setErr('Enter a valid birth year.')
    const r = await api<{ user: SessionUser }>('/api/profile', { method: 'PATCH', body: { name: name.trim(), birth_year: y,
      dietary_preferences: prefs.split(',').map((x) => x.trim()).filter(Boolean), disliked_foods: dislikes.split(',').map((x) => x.trim()).filter(Boolean) } })
    if (r.ok) { setUser(r.data.user); setMsg('Profile saved.') } else setErr(r.error.message)
  }
  const changePw = async (e: FormEvent) => {
    e.preventDefault(); setPwMsg(null)
    if (next.length < 8) return setPwMsg('The new password needs at least 8 characters.')
    const r = await api<{ message: string }>('/api/profile/password', { method: 'POST', body: { current_password: cur, new_password: next } })
    setPwMsg(r.ok ? r.data.message : r.error.message); if (r.ok) { setCur(''); setNext('') }
  }
  const del = async () => {
    if (!confirm('Permanently delete your account, history, food log, meal plans and preferences?')) return
    const r = await api('/api/profile/delete', { method: 'POST', body: { password: delPw } })
    if (r.ok) {
      setSession(null, null)
      await logOut()
      navigate('/')
    } else setErr(r.error.message)
  }
  if (!user) return <Spinner />
  return (
    <>
      <PageHeader title="Profile & settings" subtitle={user.email} actions={<button type="button" className={btn.secondary} onClick={() => { void logOut().then(() => navigate('/')) }}><LogOut className="h-4 w-4" aria-hidden="true" /> Sign out</button>} />
      <div className="grid gap-6 lg:grid-cols-2">
        <Card title="Profile">
          <form onSubmit={save} className="space-y-3" noValidate>
            <div><label htmlFor="p-n" className={label}>Name</label><input id="p-n" className={input} value={name} onChange={(e) => setName(e.target.value)} /></div>
            <div><label htmlFor="p-y" className={label}>Birth year (optional)</label><input id="p-y" inputMode="numeric" className={input} value={year} onChange={(e) => setYear(e.target.value)} /></div>
            <div><label htmlFor="p-p" className={label}>Dietary preferences</label><input id="p-p" className={input} value={prefs} onChange={(e) => setPrefs(e.target.value)} placeholder="vegetarian, Jain, low sodium" /></div>
            <div><label htmlFor="p-d" className={label}>Disliked foods</label><input id="p-d" className={input} value={dislikes} onChange={(e) => setDislikes(e.target.value)} /></div>
            {err && <p role="alert" className="text-sm text-red-700">{err}</p>}
            {msg && <p role="status" className="text-sm text-emerald-800">{msg}</p>}
            <button type="submit" className={btn.primary}>Save profile</button>
          </form>
        </Card>
        <div className="grid h-fit gap-6">
          <Card title="Change password">
            <form onSubmit={changePw} className="space-y-3">
              <div><label htmlFor="p-c" className={label}>Current password</label><input id="p-c" type="password" autoComplete="current-password" className={input} value={cur} onChange={(e) => setCur(e.target.value)} /></div>
              <div><label htmlFor="p-x" className={label}>New password</label><input id="p-x" type="password" autoComplete="new-password" className={input} value={next} onChange={(e) => setNext(e.target.value)} /></div>
              {pwMsg && <p role="status" className="text-sm text-ink-soft">{pwMsg}</p>}
              <button type="submit" className={btn.secondary}>Change password</button>
            </form>
          </Card>
          <Card title="Delete account">
            <p className="text-sm text-ink-soft">Removes your account and all saved data from this server.</p>
            <label htmlFor="p-del" className={`${label} mt-3`}>Confirm with your password</label>
            <input id="p-del" type="password" className={input} value={delPw} onChange={(e) => setDelPw(e.target.value)} />
            <button type="button" className={`${btn.danger} mt-3`} onClick={del} disabled={!delPw}>Delete my account</button>
          </Card>
        </div>
      </div>
    </>
  )
}
