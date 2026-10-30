import { useCallback, useEffect, useState } from 'react'
import type { FormEvent } from 'react'
import { ChevronDown, Info, Pencil, RefreshCw, ShieldAlert, ShoppingCart, Sparkles, Trash, TriangleAlert } from 'lucide-react'
import { Link, useSearchParams } from 'react-router-dom'
import { api, useSession } from '../lib/api'
import { Badge, Card, Empty, ErrorBox, PageHeader, Spinner, btn, input, label } from '../components/ui'

type NutrientKey = 'energy_kcal' | 'protein_g' | 'carbohydrate_g' | 'total_sugars_g' | 'total_fat_g' | 'saturated_fat_g' | 'dietary_fibre_g' | 'sodium_mg'
type VerifiedRow = { item: string; grams: number | null; status: 'matched' | 'no_match' | 'unavailable' | 'no_amount'; message: string | null
  source: { name: string; fdc_id: number | null; description: string | null; url: string | null } | null; values: Partial<Record<NutrientKey, number | null>> | null }
type Verified = { status: 'complete' | 'partial' | 'unavailable'; ingredients: VerifiedRow[]; matched: number; total: number
  totals: Partial<Record<NutrientKey, number | null>>; basis: string }
type Meal = { meal: string; name: string; ingredients: { item: string; grams: number | null }[]; estimated_nutrition: Record<string, number | null>;
  nutrition_label: string; substitutions: string[]; prep_note: string; why?: string; allergen_conflicts?: { name: string; ingredients: string[] }[];
  disliked_found?: string[]; needs_attention?: boolean; edited_by_user?: boolean; withheld?: boolean; verified_nutrition?: Verified | null }
type DayVerified = { complete: boolean; meals_counted: number; meals: number; totals: Partial<Record<NutrientKey, number | null>> }
type Plan = { days: { day: number; meals: Meal[]; totals_estimate: Record<string, { total: number | null; complete: boolean }>; totals_verified?: DayVerified }[];
  shopping_list: { item: string; grams: number | null; unknown_amount: boolean; used_in_meals: number }[]; warnings: string[]; target_kcal_per_day?: number }
type PlanRow = { id: number; title: string; created_at: string; plan?: Plan }
const split = (s: string) => s.split(',').map((x) => x.trim()).filter(Boolean)
const TARGET_MIN = 1000
const TARGET_MAX = 4500
const MEAL_TYPES = ['breakfast', 'lunch', 'dinner', 'snack']
const SHOWN: [NutrientKey, string, string][] = [
  ['energy_kcal', 'Energy', 'kcal'], ['protein_g', 'Protein', 'g'], ['carbohydrate_g', 'Carbs', 'g'], ['total_fat_g', 'Fat', 'g'],
  ['dietary_fibre_g', 'Fibre', 'g'], ['total_sugars_g', 'Sugars', 'g'], ['sodium_mg', 'Sodium', 'mg'],
]
const num = (v: number | null | undefined) => (v === null || v === undefined ? null : Math.round(v * 10) / 10)

export default function MealPlannerPage() {
  const { user } = useSession()
  const [params] = useSearchParams()
  const [days, setDays] = useState<1 | 7>(1)
  const [prefs, setPrefs] = useState('')
  const [dislikes, setDislikes] = useState('')
  const [available, setAvailable] = useState(() => params.get('have') ?? '')
  const [budget, setBudget] = useState('')
  const [meals, setMeals] = useState(MEAL_TYPES)
  const [goals, setGoals] = useState('')
  const [target, setTarget] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<string | null>(null)
  const [list, setList] = useState<PlanRow[] | null>(null)
  const [listErr, setListErr] = useState<string | null>(null)
  const [current, setCurrent] = useState<PlanRow | null>(null)
  const [day, setDay] = useState(1)

  useEffect(() => { if (user) { setPrefs(user.dietary_preferences.join(', ')); setDislikes(user.disliked_foods.join(', ')) } }, [user])
  const loadList = useCallback(async () => {
    const r = await api<{ items: PlanRow[] }>('/api/meal-plans')
    if (r.ok) { setList(r.data.items); setListErr(null) } else { setList([]); setListErr(r.error.message) }
  }, [])
  useEffect(() => { void loadList() }, [loadList])

  const generate = async (e: FormEvent) => {
    e.preventDefault()
    if (!meals.length) return setErr('Choose at least one meal.')
    const t = target.trim() ? Number(target) : null
    if (t !== null && (!Number.isInteger(t) || t < TARGET_MIN || t > TARGET_MAX)) {
      return setErr(`Enter a daily energy target between ${TARGET_MIN} and ${TARGET_MAX} kcal as a whole number, or leave it empty. For a target outside this range, plan with a doctor or registered dietitian.`)
    }
    setBusy(true); setErr(null)
    const r = await api<{ plan: PlanRow }>('/api/meal-plans', { method: 'POST', body: {
      days, dietary_preferences: split(prefs), disliked_foods: split(dislikes), available_ingredients: split(available),
      budget: budget || null, meals, goals: goals.trim() || null, target_kcal_per_day: t } })
    setBusy(false)
    if (r.ok) { setCurrent(r.data.plan); setDay(1); void loadList() } else setErr(r.error.message)
  }
  const open = async (id: number) => {
    setErr(null)
    const r = await api<{ plan: PlanRow }>(`/api/meal-plans/${id}`)
    if (r.ok) { setCurrent(r.data.plan); setDay(1) } else setErr(r.error.message)
  }
  const remove = async (id: number) => {
    if (!confirm('Delete this meal plan?')) return
    const r = await api(`/api/meal-plans/${id}`, { method: 'DELETE' })
    if (r.ok) { if (current?.id === id) setCurrent(null); void loadList() } else setErr(r.error.message)
  }

  return (
    <>
      <PageHeader title="Plan your meals" subtitle="AI-suggested meals, checked on the server against your saved allergens and dislikes. Nutrition is shown as an AI estimate and, where the ingredients match, as verified USDA values." />
      <div className="grid gap-6 lg:grid-cols-[22rem_minmax(0,1fr)]">
        <div className="grid h-fit gap-6">
          <Card title="Plan settings">
            <form onSubmit={generate} className="space-y-3" noValidate>
              <fieldset><legend className={label}>Length</legend>
                <div className="flex gap-4">{([1, 7] as const).map((d) => (
                  <label key={d} className="flex items-center gap-1.5 text-sm"><input type="radio" name="days" className="accent-emerald-700" checked={days === d} onChange={() => setDays(d)} />{d === 1 ? 'One day' : 'One week'}</label>
                ))}</div>
              </fieldset>
              <fieldset><legend className={label}>Meals</legend>
                <div className="flex flex-wrap gap-3">{MEAL_TYPES.map((m) => (
                  <label key={m} className="flex items-center gap-1.5 text-sm capitalize"><input type="checkbox" className="accent-emerald-700" checked={meals.includes(m)} onChange={(e) => setMeals((x) => (e.target.checked ? [...x, m] : x.filter((y) => y !== m)))} />{m}</label>
                ))}</div>
              </fieldset>
              <div><label htmlFor="mp-p" className={label}>Dietary preferences</label><input id="mp-p" className={input} value={prefs} onChange={(e) => setPrefs(e.target.value)} placeholder="vegetarian, high protein" aria-describedby="mp-p-help" />
                <p id="mp-p-help" className="mt-1 text-xs text-ink-soft">Preferences, not medical diets. For a diet prescribed for a health condition, follow your doctor's or dietitian's advice.</p></div>
              <div><label htmlFor="mp-d" className={label}>Disliked foods</label><input id="mp-d" className={input} value={dislikes} onChange={(e) => setDislikes(e.target.value)} placeholder="okra, bitter gourd" /></div>
              <div><label htmlFor="mp-a" className={label}>Ingredients you have</label><input id="mp-a" className={input} value={available} onChange={(e) => setAvailable(e.target.value)} placeholder="rice, dal, tomatoes" /></div>
              <div><label htmlFor="mp-b" className={label}>Budget</label>
                <select id="mp-b" className={input} value={budget} onChange={(e) => setBudget(e.target.value)}><option value="">No preference</option><option value="low">Low</option><option value="medium">Medium</option><option value="high">High</option></select></div>
              <div><label htmlFor="mp-t" className={label}>Daily energy target (optional)</label>
                <div className="flex items-center gap-2"><input id="mp-t" className={input} inputMode="numeric" value={target} onChange={(e) => setTarget(e.target.value.replace(/[^\d]/g, ''))} placeholder={`e.g. 2000`} aria-describedby="mp-t-help" /><span className="text-sm text-ink-soft">kcal</span></div>
                <p id="mp-t-help" className="mt-1 text-xs text-ink-soft">Only if you have one ({TARGET_MIN}–{TARGET_MAX} kcal). Leave empty for no target.</p></div>
              <div><label htmlFor="mp-g" className={label}>Other wishes (optional)</label><input id="mp-g" className={input} maxLength={200} value={goals} onChange={(e) => setGoals(e.target.value)} placeholder="quick to cook, South Indian" /></div>
              <p className="text-xs text-ink-soft">Your saved allergens (<Link to="/allergens" className="font-semibold text-emerald-700 hover:underline">edit</Link>) are always applied. A suggestion that names one is removed.</p>
              {err && <p role="alert" className="rounded-xl bg-red-50 p-3 text-sm text-red-800">{err}</p>}
              <button type="submit" className={`${btn.primary} w-full`} disabled={busy}><Sparkles className="h-4 w-4" aria-hidden="true" /> {busy ? 'Generating (up to 30 s)…' : 'Generate plan'}</button>
            </form>
          </Card>
          <Card title="Saved plans">
            {!list ? <Spinner /> : listErr ? <p role="alert" className="text-sm text-red-800">{listErr}</p> : list.length === 0 ? <p className="text-sm text-ink-soft">No saved plans yet. Generated plans are saved automatically.</p> : (
              <ul className="divide-y divide-emerald-900/5">{list.map((p) => (
                <li key={p.id} className="flex items-center gap-2 py-2 text-sm">
                  <button type="button" className="min-w-0 flex-1 truncate text-left font-semibold hover:text-emerald-700" onClick={() => open(p.id)} aria-label={`Open ${p.title}`}>{p.title}<span className="block text-xs font-normal text-ink-soft">{new Date(p.created_at).toLocaleString()}</span></button>
                  <button type="button" className={btn.ghost} onClick={() => remove(p.id)} aria-label={`Delete ${p.title}`}><Trash className="h-4 w-4" /></button>
                </li>))}</ul>
            )}
          </Card>
        </div>
        <div className="min-w-0">
          {busy && <Spinner label="Asking the planner, checking allergens and looking up verified nutrition…" />}
          {!current && !busy && <Empty title="No plan open" text="Choose your settings and generate a plan, or open a saved one." />}
          {current?.plan && !busy && <PlanView row={current} day={day} setDay={setDay} onChange={setCurrent} />}
        </div>
      </div>
    </>
  )
}

function NutrientLine({ values, prefix }: { values: Partial<Record<NutrientKey, number | null>> | Record<string, number | null>; prefix: string }) {
  const parts = SHOWN.filter(([k]) => k in values).map(([k, l, u]) => `${l} ${num(values[k]) ?? '–'}${values[k] === null || values[k] === undefined ? '' : ` ${u}`}`)
  return <p className="text-xs text-ink-soft"><span className="font-semibold text-ink">{prefix}</span> {parts.join(' · ')}</p>
}

function VerifiedBlock({ v }: { v: Verified }) {
  const missing = v.ingredients.filter((r) => r.status !== 'matched')
  return (
    <details className="group mt-2 rounded-xl bg-emerald-50/60 p-2.5">
      <summary className="flex cursor-pointer list-none items-start gap-1.5 text-xs">
        <ChevronDown className="mt-0.5 h-3.5 w-3.5 shrink-0 transition-transform group-open:rotate-180" aria-hidden="true" />
        <span className="min-w-0 flex-1">
          {v.status === 'complete' ? <NutrientLine values={v.totals} prefix="Verified (USDA):" />
            : v.status === 'partial' ? <span className="text-ink-soft"><span className="font-semibold text-ink">Verified total unavailable:</span> {v.matched} of {v.total} ingredients matched a USDA record ({missing.map((r) => r.item).join(', ')} did not).</span>
              : <span className="text-ink-soft"><span className="font-semibold text-ink">Verified values unavailable:</span> no ingredient matched a USDA record.</span>}
        </span>
      </summary>
      <ul className="mt-2 space-y-1 pl-5 text-xs">
        {v.ingredients.map((r, i) => (
          <li key={i} className="break-words">
            <span className="font-semibold">{r.item}{r.grams !== null ? ` (${num(r.grams)} g)` : ''}:</span>{' '}
            {r.status === 'matched' && r.values ? (
              <>{num(r.values.energy_kcal) ?? '–'} kcal, protein {num(r.values.protein_g) ?? '–'} g · {r.source?.url
                ? <a href={r.source.url} target="_blank" rel="noreferrer" className="text-emerald-700 hover:underline">{r.source.description ?? r.source.name}</a>
                : r.source?.description ?? r.source?.name}</>
            ) : <span className="text-ink-soft">{r.message ?? 'No verified match.'}</span>}
          </li>
        ))}
        <li className="text-ink-soft">{v.basis} Real values depend on the actual products and cooking.</li>
      </ul>
    </details>
  )
}

function PlanView({ row, day, setDay, onChange }: { row: PlanRow; day: number; setDay: (d: number) => void; onChange: (p: PlanRow) => void }) {
  const plan = row.plan!
  const d = plan.days.find((x) => x.day === day) ?? plan.days[0]
  const [busy, setBusy] = useState<string | null>(null)
  const [err, setErr] = useState<string | null>(null)
  const [edit, setEdit] = useState<Meal | null>(null)
  const regen = async (meal: string) => {
    setBusy(meal); setErr(null)
    const r = await api<{ plan: PlanRow }>(`/api/meal-plans/${row.id}/regenerate`, { method: 'POST', body: { day: d.day, meal } })
    setBusy(null)
    if (r.ok) onChange(r.data.plan); else setErr(r.error.message)
  }
  const est = d.totals_estimate.energy_kcal
  const ver = d.totals_verified
  return (
    <div className="grid gap-6">
      <div>
        <h2 className="font-display text-xl font-extrabold">{row.title}</h2>
        <p className="text-xs text-ink-soft">Saved {new Date(row.created_at).toLocaleString()}</p>
      </div>
      {plan.days.length > 1 && (
        <div role="tablist" aria-label="Day" className="flex flex-wrap gap-2">
          {plan.days.map((x) => <button key={x.day} type="button" role="tab" aria-selected={x.day === d.day} onClick={() => setDay(x.day)}
            className={`rounded-full px-4 py-1.5 text-sm font-semibold ${x.day === d.day ? 'bg-emerald-600 text-white' : 'bg-white ring-1 ring-emerald-900/10 hover:bg-emerald-50'}`}>Day {x.day}</button>)}
        </div>
      )}
      {err && <ErrorBox message={err} />}
      <Card title={`Day ${d.day}`}>
        <div className="mb-4 grid gap-2 rounded-2xl bg-cream p-3 text-sm sm:grid-cols-3">
          <p><span className="block text-xs text-ink-soft">AI estimate</span><span className="font-semibold">{est?.total ?? '–'} kcal</span>{est && !est.complete && <span className="text-xs text-ink-soft"> (some meals not estimated)</span>}</p>
          <p><span className="block text-xs text-ink-soft">Verified (USDA)</span>
            {ver?.complete ? <span className="font-semibold">{num(ver.totals.energy_kcal) ?? '–'} kcal</span>
              : <span className="text-xs text-ink-soft">Unavailable: {ver ? `${ver.meals_counted} of ${ver.meals} meals fully matched` : 'not calculated for this older plan'}</span>}</p>
          <p><span className="block text-xs text-ink-soft">Your target</span><span className="font-semibold">{plan.target_kcal_per_day ? `${plan.target_kcal_per_day} kcal` : 'None set'}</span></p>
        </div>
        <ul className="grid gap-4">
          {d.meals.map((m) => (
            <li key={m.meal} className={`min-w-0 rounded-2xl border p-4 ${m.withheld ? 'border-red-200 bg-red-50/40' : m.needs_attention ? 'border-amber-300 bg-amber-50/50' : 'border-emerald-900/10'}`}>
              <div className="flex flex-wrap items-center gap-2">
                <Badge tone="grey">{m.meal}</Badge>
                {!m.withheld && <span className="min-w-0 break-words font-semibold">{m.name}</span>}
                {m.edited_by_user && <Badge tone="blue">edited by you</Badge>}
                <span className="ml-auto flex flex-wrap gap-1">
                  {!m.withheld && <button type="button" className={btn.ghost} onClick={() => setEdit(m)} aria-label={`Edit ${m.meal}`}><Pencil className="h-4 w-4" aria-hidden="true" /> Edit</button>}
                  <button type="button" className={btn.ghost} onClick={() => regen(m.meal)} disabled={busy !== null} aria-label={`Replace ${m.meal} with a new suggestion`}>
                    <RefreshCw className={`h-4 w-4 ${busy === m.meal ? 'animate-spin' : ''}`} aria-hidden="true" /> {busy === m.meal ? 'Replacing…' : 'Replace'}</button>
                </span>
              </div>
              {m.withheld ? (
                <p role="alert" className="mt-2 flex gap-1.5 text-sm font-semibold text-red-800"><ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                  This suggestion was removed because it named your allergen {m.allergen_conflicts?.map((c) => c.name).join(', ')}. Use Replace for a new suggestion.</p>
              ) : (
                <>
                  {m.allergen_conflicts?.map((c) => <p key={c.name} role="alert" className="mt-2 flex items-center gap-1.5 text-sm font-semibold text-red-800"><TriangleAlert className="h-4 w-4" aria-hidden="true" /> Contains your allergen {c.name}: {c.ingredients.join(', ')}.</p>)}
                  {m.disliked_found && m.disliked_found.length > 0 && <p className="mt-1 text-sm text-amber-900">Includes a disliked food: {m.disliked_found.join(', ')}</p>}
                  {m.why && <p className="mt-2 text-sm"><span className="font-semibold">Why this meal: </span>{m.why}</p>}
                  <ul className="mt-2 flex flex-wrap gap-1.5 text-sm">
                    {m.ingredients.map((i, n) => <li key={n} className="rounded-full bg-white px-2.5 py-0.5 ring-1 ring-emerald-900/10">{i.item}{i.grams ? <span className="text-ink-soft"> · {num(i.grams)} g</span> : ''}</li>)}
                  </ul>
                  <div className="mt-2 space-y-0.5">
                    <NutrientLine values={m.estimated_nutrition} prefix="AI estimate:" />
                    <p className="text-[11px] text-ink-soft">{m.nutrition_label}</p>
                  </div>
                  {m.verified_nutrition && <VerifiedBlock v={m.verified_nutrition} />}
                  {m.substitutions.length > 0 && <p className="mt-2 text-xs text-ink-soft">Swaps: {m.substitutions.join('; ')}</p>}
                  {m.prep_note && <p className="mt-1 text-xs text-ink-soft">{m.prep_note}</p>}
                </>
              )}
            </li>
          ))}
        </ul>
      </Card>
      {edit && <EditMeal plan={row} day={d.day} meal={edit} onClose={() => setEdit(null)} onSaved={(p) => { onChange(p); setEdit(null) }} />}
      <Card title="Shopping list" action={<ShoppingCart className="h-5 w-5 text-emerald-700" aria-hidden="true" />}>
        {plan.shopping_list.length === 0 ? <p className="text-sm text-ink-soft">Nothing to buy for this plan.</p> : (
          <ul className="grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">{plan.shopping_list.map((s) => <li key={s.item} className="flex justify-between gap-2 border-b border-emerald-900/5 py-1"><span className="min-w-0 break-words capitalize">{s.item}</span><span className="shrink-0 text-ink-soft">{s.grams ? `${s.grams} g` : ''}{s.unknown_amount ? ' + some' : ''}</span></li>)}</ul>
        )}
      </Card>
      <ul className="space-y-1 text-xs text-ink-soft">{plan.warnings.map((w) => <li key={w} className="flex gap-1.5"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{w}</li>)}</ul>
    </div>
  )
}

function EditMeal({ plan, day, meal, onClose, onSaved }: { plan: PlanRow; day: number; meal: Meal; onClose: () => void; onSaved: (p: PlanRow) => void }) {
  const [name, setName] = useState(meal.name)
  const [ings, setIngs] = useState(meal.ingredients.map((i) => `${i.item}${i.grams ? `: ${i.grams}` : ''}`).join('\n'))
  const [err, setErr] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const save = async (e: FormEvent) => {
    e.preventDefault()
    const ingredients = ings.split('\n').map((l) => l.trim()).filter(Boolean).map((l) => {
      const [item, g] = l.split(':')
      const grams = g !== undefined && g.trim() !== '' ? Number(g) : null
      return { item: item.trim(), grams: grams !== null && Number.isFinite(grams) ? grams : null }
    })
    if (!name.trim()) return setErr('Enter a meal name.')
    if (ingredients.length === 0) return setErr('Enter at least one ingredient.')
    setSaving(true)
    const r = await api<{ plan: PlanRow }>(`/api/meal-plans/${plan.id}/meal`, { method: 'PUT', body: { day, meal: meal.meal, name, ingredients } })
    setSaving(false)
    if (r.ok) onSaved(r.data.plan); else setErr(r.error.message)
  }
  return (
    <Card title={`Edit ${meal.meal}`}>
      <form onSubmit={save} className="space-y-3" noValidate>
        <div><label htmlFor="em-n" className={label}>Meal name</label><input id="em-n" className={input} value={name} onChange={(e) => setName(e.target.value)} /></div>
        <div><label htmlFor="em-i" className={label}>Ingredients (one per line, grams after a colon, e.g. "cooked rice: 150")</label>
          <textarea id="em-i" rows={5} className={input} value={ings} onChange={(e) => setIngs(e.target.value)} /></div>
        {err && <p role="alert" className="text-sm text-red-700">{err}</p>}
        <div className="flex gap-2"><button type="submit" className={btn.primary} disabled={saving}>{saving ? 'Saving…' : 'Save meal'}</button><button type="button" className={btn.secondary} onClick={onClose}>Cancel</button></div>
        <p className="text-xs text-ink-soft">Edited meals are re-checked against your allergens. No AI estimate is made for them; verified values are calculated for ingredients that match a USDA record and have grams.</p>
      </form>
    </Card>
  )
}
