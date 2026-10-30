import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { TriangleAlert, BookmarkPlus, Camera, Check, Download, ExternalLink, FlaskConical, Info, Leaf, CirclePlus, ShieldAlert } from 'lucide-react'
import { api, download } from '../lib/api'
import { useAuth } from './AuthProvider'
import type { Enhancement, Freshness, HistoryStatus, ImageQuality, Precaution, SafetyAlert, VisionInfo } from '../lib/foodApi'
import type { AllergenAlerts, ExternalProduct } from '../lib/packagedApi'
import { Badge, btn, input, todayISO } from './ui'

/* ------------------------------------------------------------------ save / report / log */
/** Successful analyses are saved automatically for signed-in users (cookie or token session). This panel shows the
 *  outcome, offers a manual save if the automatic one failed, and links the PDF report and food log. */
export function SaveActions({ analysisId, kind, canLog = true, history }: {
  analysisId?: string; kind: 'fresh' | 'packaged'; canLog?: boolean; history?: HistoryStatus
}) {
  const { user, loading } = useAuth()
  const autoId = history && history.saved ? history.scan_id : null
  const [scanId, setScanId] = useState<number | null>(autoId)
  const [state, setState] = useState<'idle' | 'saving' | 'error'>('idle')
  const [msg, setMsg] = useState<string | null>(null)
  const [grams, setGrams] = useState('')
  const [meal, setMeal] = useState('other')
  const [logged, setLogged] = useState(false)
  const [busy, setBusy] = useState(false)
  useEffect(() => {
    setScanId(autoId); setState('idle'); setLogged(false)
    setMsg(history && !history.saved && history.reason === 'storage_error' ? history.message : null)
  }, [analysisId, autoId, history])

  if (!analysisId || loading) return null
  if (!user) {
    return (
      <p className="mt-5 rounded-xl bg-cream p-3 text-sm text-ink-soft">
        <Link to="/signin" className="font-semibold text-emerald-700 hover:underline">Sign in</Link> to save {kind === 'fresh' ? 'foods' : 'products'} to
        your history automatically, add them to your daily nutrition, and download PDF reports.
      </p>
    )
  }
  const save = async () => {
    setState('saving'); setMsg(null)
    const r = await api<{ scan: { id: number }; duplicate: boolean }>('/api/history', { method: 'POST', body: { analysis_id: analysisId } })
    if (r.ok) { setScanId(r.data.scan.id); setState('idle'); setMsg(r.data.duplicate ? 'Already in your history.' : 'Saved to your history.') }
    else { setState('error'); setMsg(r.error.message) }
  }
  const report = async () => {
    if (!scanId) return
    setBusy(true)
    const r = await download(`/api/reports/scans/${scanId}`, 'SmartPlateAI_report.pdf')
    setBusy(false)
    if (!r.ok) setMsg(r.error.message)
  }
  const log = async () => {
    const g = Number(grams)
    if (!scanId || !Number.isFinite(g) || g <= 0 || g > 5000) return setMsg('Enter the grams you ate (1 to 5000).')
    setBusy(true)
    const r = await api('/api/nutrition/entries', { method: 'POST', body: { logged_on: todayISO(), meal, scan_id: scanId, grams: g, client_ref: `${scanId}-${todayISO()}-${meal}-${g}` } })
    setBusy(false)
    if (r.ok) { setLogged(true); setMsg('Added to today\'s nutrition.') } else setMsg(r.error.message)
  }
  return (
    <div className="rounded-2xl border border-emerald-900/10 bg-cream/60 p-4">
      <div className="flex flex-wrap items-center gap-2">
        {scanId ? (
          <>
            <Badge><Check className="h-3 w-3" aria-hidden="true" /> {history && history.saved && history.scan_id === scanId
              ? (history.duplicate ? 'Already in your history' : 'Saved to your history') : 'Saved'}</Badge>
            <Link to="/history" className={btn.ghost}>View history</Link>
            <button type="button" className={btn.secondary} onClick={report} disabled={busy}>
              <Download className="h-4 w-4" aria-hidden="true" /> PDF report
            </button>
          </>
        ) : (
          <button type="button" className={btn.primary} onClick={save} disabled={state === 'saving'}>
            <BookmarkPlus className="h-4 w-4" aria-hidden="true" /> {state === 'saving' ? 'Saving…' : 'Save to history'}
          </button>
        )}
      </div>
      {scanId && canLog && !logged && (
        <div className="mt-3 flex flex-wrap items-end gap-2">
          <div className="w-28">
            <label htmlFor={`g-${analysisId}`} className="mb-1 block text-xs font-semibold">Grams eaten</label>
            <input id={`g-${analysisId}`} inputMode="decimal" className={input} value={grams} onChange={(e) => setGrams(e.target.value)} placeholder="150" />
          </div>
          <div className="w-32">
            <label htmlFor={`m-${analysisId}`} className="mb-1 block text-xs font-semibold">Meal</label>
            <select id={`m-${analysisId}`} className={input} value={meal} onChange={(e) => setMeal(e.target.value)}>
              {['breakfast', 'lunch', 'dinner', 'snack', 'other'].map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          </div>
          <button type="button" className={btn.secondary} onClick={log} disabled={busy}>
            <CirclePlus className="h-4 w-4" aria-hidden="true" /> Add to today
          </button>
        </div>
      )}
      {msg && <p role={state === 'error' ? 'alert' : 'status'} className={`mt-2 text-sm ${state === 'error' ? 'text-red-700' : 'text-ink-soft'}`}>{msg}</p>}
    </div>
  )
}

/* ------------------------------------------------------------------ freshness */
const CONDITION_FALLBACK: Record<Freshness['status'], string> = {
  fresh: 'Fresh', possibly_spoiled: 'Rotten / possibly spoiled', uncertain: 'Borderline / unclear', not_assessed: 'Not assessed',
}

export function FreshnessCard({ f }: { f?: Freshness }) {
  if (!f) return null
  const tone = f.status === 'fresh' ? 'green' : f.status === 'possibly_spoiled' ? 'red' : f.status === 'uncertain' ? 'amber' : 'grey'
  const assessed = f.status !== 'not_assessed'
  return (
    <div className="rounded-2xl border border-emerald-900/10 p-4">
      <div className="flex flex-wrap items-center gap-2">
        <Leaf className="h-4 w-4 text-emerald-700" aria-hidden="true" />
        <span className="font-semibold">Condition</span>
        <Badge tone={tone}>{f.condition_label ?? CONDITION_FALLBACK[f.status]}</Badge>
      </div>
      {f.condition_summary && <p className="mt-1.5 text-sm">{f.condition_summary}</p>}
      <p className="mt-1 text-sm text-ink-soft">{f.message}</p>
      {assessed && f.confidence !== null && (
        <p className="mt-1 text-xs text-ink-soft">
          Model confidence in this label: {(f.confidence * 100).toFixed(0)}%. This is how sure the model is of the label, not how fresh the food is.
        </p>
      )}
      {assessed && (
        <p className="mt-1 text-xs text-ink-soft">
          {f.percent_note ?? 'No freshness or deterioration percentage is shown: the model only distinguishes fresh from rotten.'}
        </p>
      )}
      {f.evidence && (
        <details className="mt-1 text-xs text-ink-soft">
          <summary className="cursor-pointer select-none">Model details</summary>
          <p className="mt-1">{f.evidence}</p>
        </details>
      )}
      {assessed && <p className="mt-1 text-xs text-ink-soft">A photo cannot show microbes, toxins or residues.</p>}
    </div>
  )
}

/** Prominent banner for food that may be spoiled (danger) or could not be judged (caution). */
export function SafetyAlertBanner({ alert }: { alert?: SafetyAlert | null }) {
  if (!alert) return null
  const danger = alert.level === 'danger'
  return (
    <div role="alert" className={`mt-4 flex gap-3 rounded-2xl border p-4 ${danger ? 'border-red-300 bg-red-50 text-red-900' : 'border-amber-300 bg-amber-50 text-amber-950'}`}>
      {danger ? <ShieldAlert className="mt-0.5 h-6 w-6 shrink-0" aria-hidden="true" /> : <TriangleAlert className="mt-0.5 h-5 w-5 shrink-0" aria-hidden="true" />}
      <div className="min-w-0">
        <p className={`font-bold ${danger ? 'text-lg' : ''}`}>{alert.title}</p>
        <p className="mt-0.5 text-sm">{alert.message}</p>
        <p className="mt-1 text-xs opacity-75">{alert.basis}</p>
      </div>
    </div>
  )
}

export function QualityNote({ q, enhancement, onRetake }: { q?: ImageQuality; enhancement?: Enhancement; onRetake?: () => void }) {
  if (!q || (q.level === 'good' && !enhancement?.applied)) return null
  const poor = q.level === 'poor'
  return (
    <div role={poor ? 'alert' : 'status'} className={`mt-5 rounded-2xl border p-4 text-sm ${poor ? 'border-amber-300 bg-amber-50 text-amber-950' : 'border-emerald-900/10 bg-cream text-ink'}`}>
      <p className="flex flex-wrap items-center gap-2 font-semibold">
        <Camera className="h-4 w-4" aria-hidden="true" /> Photo quality: {poor ? 'too low for a reliable result' : q.level === 'fair' ? 'fair' : 'good'}
      </p>
      {q.advice.length > 0 && <ul className="mt-1 list-disc space-y-0.5 pl-5">{q.advice.map((a) => <li key={a}>{a}</li>)}</ul>}
      {enhancement?.applied && (
        <p className="mt-1 text-xs opacity-80">
          {enhancement.used === 'enhanced'
            ? 'A brightness/contrast-corrected copy confirmed the same food, so that result is shown.'
            : 'A brightness/contrast-corrected copy was tried but did not give a more reliable result, so the original was used.'}
        </p>
      )}
      <p className="mt-1 text-xs opacity-80">Photo quality is measured separately from food identity and freshness confidence.</p>
      {poor && onRetake && <button type="button" onClick={onRetake} className="mt-2 rounded-full border border-current px-4 py-1.5 font-semibold">Retake photo</button>}
    </div>
  )
}

/* ------------------------------------------------------------------ Google Vision */
export function VisionNote({ v }: { v?: VisionInfo | null }) {
  if (!v) return null
  if (v.status === 'unavailable') return <p className="mt-3 text-xs text-ink-soft">{v.message ?? 'Google Vision was unavailable.'}</p>
  const text = {
    agrees: `Google Vision agrees (${(v.agreeing_labels ?? []).join(', ')}).`,
    generic: 'Google Vision saw food but did not name a specific one.',
    conflicts: `Google Vision suggests ${[...(v.conflicting_supported_foods ?? []), ...(v.conflicting_labels ?? [])].slice(0, 3).join(', ') || 'a different food'}.`,
    no_food: 'Google Vision did not detect food in this photo.',
  }[v.status]
  return (
    <p className="mt-3 flex items-start gap-2 text-sm text-ink-soft">
      <Info className="mt-0.5 h-4 w-4 shrink-0 text-sky-700" aria-hidden="true" />
      <span>{text} {v.hints_outside_supported && v.hints_outside_supported.length > 0 &&
        <>Google Vision labels alone are never used to name a food; they only support or question the identification.</>}</span>
    </p>
  )
}

/* ------------------------------------------------------------------ precautions */
export function Precautions({ items }: { items?: Precaution[] }) {
  if (!items || items.length === 0) return null
  return (
    <div>
      <h3 className="font-semibold">Precautions</h3>
      <ul className="mt-2 space-y-2">
        {items.map((p, i) => (
          <li key={i} className={`flex gap-2 rounded-xl p-3 text-sm ${p.kind === 'danger' ? 'bg-red-50 font-semibold text-red-900' : p.kind === 'warning' ? 'bg-amber-50 text-amber-950' : 'bg-cream'}`}>
            {p.kind === 'danger' ? <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              : p.kind === 'warning' ? <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
                : <Info className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" aria-hidden="true" />}
            <span>{p.text}<span className="block text-xs opacity-70">{p.source}</span></span>
          </li>
        ))}
      </ul>
    </div>
  )
}

/* ------------------------------------------------------------------ chemical intelligence */
export type Compound = {
  common_name: string; category: string; role: string; where: string | null; chemical_name: string | null; formula: string | null
  molecular_weight: number | null; pubchem_url: string | null; pubchem_status: string
  amount: { value: number; unit: string; basis: string; source: string; url: string | null } | null
  record_sources?: { association: string; identity: string | null; amount: string | null }
}
export type PubChemSummary = { status: string; message: string | null; total: number; found: number; not_found: number; failed: number }
export type ChemicalProfile = { food: string; status: string; compounds: Compound[]; message: string | null; sources: { name: string; url: string }[];
  limitations: string[]; pubchem_reachable: boolean | null; pubchem?: PubChemSummary }

const PUBCHEM_ROW_STATUS: Record<string, string> = {
  not_found: 'No PubChem match', timeout: 'Not retrieved: PubChem timed out', rate_limited: 'Not retrieved: PubChem busy',
  unavailable: 'Not retrieved: PubChem unreachable', invalid_response: 'Not retrieved: unreadable PubChem reply',
  invalid_query: 'Not retrieved: name rejected by PubChem', disabled: 'PubChem lookups off',
}
const PUBCHEM_OK = new Set(['ok', 'no_match', 'not_applicable'])

/** One line about PubChem, only when there is something to say. Older responses without `pubchem` fall back to the old flag. */
function PubChemNotice({ data }: { data: ChemicalProfile }) {
  const s = data.pubchem
  const message = s ? s.message : data.pubchem_reachable === false ? 'PubChem could not be reached, so chemical names and formulas are missing.' : null
  if (!message) return null
  const problem = s ? !PUBCHEM_OK.has(s.status) : true
  return (
    <p role="status" className={`mt-3 rounded-xl p-2.5 text-xs ${problem ? 'bg-amber-50 font-semibold text-amber-900' : 'bg-cream text-ink-soft'}`}>
      {message}
    </p>
  )
}

function CompoundAmount({ c }: { c: Compound }) {
  return c.amount
    ? <><span className="font-semibold text-ink">{Math.round(c.amount.value * 100) / 100} {c.amount.unit}</span> {c.amount.basis}</>
    : <span className="text-ink-soft">No amount in the source data</span>
}

function CompoundSources({ c }: { c: Compound }) {
  const s = c.record_sources
  return (
    <span className="block break-words text-xs text-ink-soft">
      Sources: {s ? s.association : 'SmartPlateAI curated list'}
      {c.pubchem_url ? <>; identity <a href={c.pubchem_url} target="_blank" rel="noreferrer" className="inline-flex items-center gap-0.5 font-semibold text-emerald-700 hover:underline">{s?.identity ?? 'PubChem'} <ExternalLink className="h-3 w-3" aria-hidden="true" /></a></> : null}
      {c.amount ? `; amount ${c.amount.source}` : null}
    </span>
  )
}

function formulaText(c: Compound): string {
  return c.formula ?? PUBCHEM_ROW_STATUS[c.pubchem_status] ?? 'Not available'
}

export function ChemicalPanel({ food, initiallyOpen = false }: { food: string; initiallyOpen?: boolean }) {
  const [open, setOpen] = useState(initiallyOpen)
  const [data, setData] = useState<ChemicalProfile | null>(null)
  const [err, setErr] = useState<string | null>(null)
  useEffect(() => { setData(null); setErr(null) }, [food])
  useEffect(() => {
    if (!open || data) return
    const ctrl = new AbortController()
    api<ChemicalProfile>(`/api/chemical/${encodeURIComponent(food)}`, { signal: ctrl.signal })
      .then((r) => (r.ok ? setData(r.data) : setErr(r.error.message))).catch(() => {})
    return () => ctrl.abort()
  }, [open, data, food])
  return (
    <div className="rounded-2xl border border-emerald-900/10">
      <button type="button" onClick={() => setOpen((v) => !v)} aria-expanded={open}
        className="flex w-full items-center gap-2 px-4 py-3 text-left font-semibold hover:bg-emerald-50/60">
        <FlaskConical className="h-4 w-4 text-emerald-700" aria-hidden="true" /> Chemical intelligence
        <span className="ml-auto text-xs font-normal text-ink-soft">reference composition</span>
      </button>
      {open && (
        <div className="border-t border-emerald-900/10 p-4">
          {!data && !err && <p role="status" className="text-sm text-ink-soft">Loading compound data…</p>}
          {err && <p role="alert" className="text-sm text-red-700">{err}</p>}
          {data && <ChemicalTable data={data} />}
        </div>
      )}
    </div>
  )
}

export function ChemicalTable({ data }: { data: ChemicalProfile }) {
  return (
    <>
      {data.compounds.length === 0 ? <p className="text-sm text-ink-soft">{data.message}</p> : (
        <>
          {/* Phones: one card per compound, everything wraps (no clipped columns). */}
          <ul className="space-y-3 md:hidden">
            {data.compounds.map((c) => (
              <li key={c.common_name} className="rounded-xl border border-emerald-900/10 p-3 text-sm">
                <p className="font-semibold">{c.common_name}</p>
                <p className="text-xs text-ink-soft">{c.category}</p>
                <dl className="mt-2 grid grid-cols-[5.5rem_minmax(0,1fr)] gap-x-2 gap-y-1 text-xs">
                  <dt className="text-ink-soft">Formula</dt><dd className={`break-words ${c.formula ? 'font-mono' : 'text-ink-soft'}`}>{formulaText(c)}</dd>
                  {c.chemical_name && <><dt className="text-ink-soft">IUPAC name</dt><dd className="break-words">{c.chemical_name}</dd></>}
                  <dt className="text-ink-soft">Role</dt><dd>{c.role}{c.where && <span className="block text-ink-soft">{c.where}</span>}</dd>
                  <dt className="text-ink-soft">Amount</dt><dd><CompoundAmount c={c} /></dd>
                </dl>
                <div className="mt-2"><CompoundSources c={c} /></div>
              </li>
            ))}
          </ul>
          <div className="hidden md:block">
            <table className="w-full table-fixed text-left text-sm">
              <thead><tr className="border-b border-emerald-900/10 text-xs uppercase tracking-wide text-ink-soft">
                <th scope="col" className="w-[30%] py-2 pr-3">Compound</th><th scope="col" className="w-[17%] py-2 pr-3">Formula</th>
                <th scope="col" className="w-[30%] py-2 pr-3">Role in the food</th><th scope="col" className="py-2">Amount</th>
              </tr></thead>
              <tbody>
                {data.compounds.map((c) => (
                  <tr key={c.common_name} className="border-b border-emerald-900/5 align-top">
                    <td className="break-words py-2 pr-3">
                      <span className="font-semibold">{c.common_name}</span>
                      <span className="block text-xs text-ink-soft">{c.category}</span>
                      {c.chemical_name && <span className="block break-words text-xs text-ink-soft">IUPAC: {c.chemical_name}</span>}
                      <CompoundSources c={c} />
                    </td>
                    <td className={`break-words py-2 pr-3 text-xs ${c.formula ? 'font-mono' : 'text-ink-soft'}`}>{formulaText(c)}</td>
                    <td className="break-words py-2 pr-3">{c.role}{c.where && <span className="block text-xs text-ink-soft">{c.where}</span>}</td>
                    <td className="break-words py-2 text-xs"><CompoundAmount c={c} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </>
      )}
      <PubChemNotice data={data} />
      <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-ink-soft">{data.limitations.map((l) => <li key={l}>{l}</li>)}</ul>
      <p className="mt-2 text-xs text-ink-soft">Sources: {data.sources.map((s, i) => <span key={s.url}>{i > 0 && ', '}<a href={s.url} target="_blank" rel="noreferrer" className="font-semibold text-emerald-700 hover:underline">{s.name}</a></span>)}</p>
    </>
  )
}

/* ------------------------------------------------------------------ packaged: allergen alerts + Open Food Facts */
export function AllergenAlertsCard({ alerts }: { alerts?: AllergenAlerts | null }) {
  const { user } = useAuth()
  if (!user) return <p className="mt-6 rounded-2xl bg-white p-4 text-sm text-ink-soft shadow-soft"><Link to="/signin" className="font-semibold text-emerald-700 hover:underline">Sign in</Link> and set your allergen preferences to get personal allergen alerts.</p>
  if (!alerts) return null
  if (!alerts.preferences_checked.length) return <p className="mt-6 rounded-2xl bg-white p-4 text-sm text-ink-soft shadow-soft">You have no saved allergens. <Link to="/allergens" className="font-semibold text-emerald-700 hover:underline">Add your allergens</Link> to get personal alerts.</p>
  return (
    <section className="mt-6 rounded-3xl border border-amber-900/15 bg-white p-6 shadow-soft" aria-labelledby="alerts-h">
      <h2 id="alerts-h" className="flex items-center gap-2 font-display text-xl font-extrabold"><ShieldAlert className="h-5 w-5 text-amber-700" aria-hidden="true" /> Your allergen alerts</h2>
      {alerts.confirmed.map((a) => (
        <p key={a.allergen} role="alert" className="mt-3 rounded-xl bg-red-50 p-3 text-sm font-semibold text-red-800">
          Contains {a.name}{a.severity === 'severe' ? ' (marked severe)' : ''}. Found in: {a.evidence.join(', ')}.
        </p>
      ))}
      {alerts.possible.map((a) => (
        <p key={a.allergen} className="mt-3 rounded-xl bg-amber-50 p-3 text-sm font-semibold text-amber-900">May contain {a.name} (precautionary statement).</p>
      ))}
      {alerts.warnings.map((w) => <p key={w} className="mt-3 text-sm text-ink-soft">{w}</p>)}
      <p className="mt-2 text-xs text-ink-soft">Checked: {alerts.preferences_checked.join(', ')}. Always read the physical label.</p>
    </section>
  )
}

export function ExternalCard({ ext }: { ext?: ExternalProduct | null }) {
  if (!ext || ext.status === 'not_attempted') return null
  return (
    <section className="mt-6 rounded-3xl border border-emerald-900/10 bg-white p-6 shadow-soft">
      <p className="text-sm font-semibold uppercase tracking-wider text-sky-700">External database</p>
      <h2 className="font-display text-xl font-extrabold">Open Food Facts</h2>
      {ext.status === 'found' && ext.product ? (
        <>
          <p className="mt-1 text-sm">{[ext.product.brand, ext.product.name].filter(Boolean).join(' ')} {ext.product.quantity && <span className="text-ink-soft">· {ext.product.quantity}</span>}</p>
          <p className="text-xs text-ink-soft">Matched by {ext.match === 'barcode' ? 'barcode' : 'brand and product name'} · {ext.product.source}</p>
          {Object.keys(ext.product.nutrition_per_100g).length > 0 && (
            <ul className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
              {Object.entries(ext.product.nutrition_per_100g).map(([k, v]) => <li key={k} className="flex justify-between border-b border-emerald-900/5 py-1"><span>{k.replace(/_/g, ' ')}</span><span className="tabular-nums">{v} per 100 g</span></li>)}
            </ul>
          )}
          {ext.conflicts_with_label && ext.conflicts_with_label.length > 0 && (
            <div className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
              <p className="font-semibold">Differences from the label in your photo (the label takes priority):</p>
              <ul className="mt-1 list-disc pl-5">{ext.conflicts_with_label.map((c) => <li key={c.nutrient}>{c.nutrient.replace(/_/g, ' ')}: label {c.label_value}, Open Food Facts {c.open_food_facts_value}</li>)}</ul>
            </div>
          )}
          {ext.product.url && <a className="mt-3 inline-flex items-center gap-1 text-sm font-semibold text-emerald-700 hover:underline" href={ext.product.url} target="_blank" rel="noreferrer">View on Open Food Facts <ExternalLink className="h-3.5 w-3.5" aria-hidden="true" /></a>}
        </>
      ) : <p className="mt-1 text-sm text-ink-soft">{ext.message ?? 'No matching product.'}</p>}
    </section>
  )
}

export function LabelDates({ dates, storage }: { dates?: { type: string; as_printed: string }[]; storage?: string[] }) {
  if (!dates?.length && !storage?.length) return null
  return (
    <div className="mt-4 grid gap-4 md:grid-cols-2">
      {dates && dates.length > 0 && (
        <div>
          <h3 className="font-semibold">Dates (as printed)</h3>
          <ul className="mt-1 text-sm text-ink-soft">{dates.map((d) => <li key={d.type + d.as_printed}>{d.type.replace('_', ' ')}: <span className="font-semibold text-ink">{d.as_printed}</span></li>)}</ul>
          <p className="text-xs text-ink-soft">Read by OCR; check the pack before relying on it.</p>
        </div>
      )}
      {storage && storage.length > 0 && (
        <div>
          <h3 className="font-semibold">Storage instructions</h3>
          <ul className="mt-1 list-disc pl-5 text-sm text-ink-soft">{storage.map((s) => <li key={s}>{s}</li>)}</ul>
        </div>
      )}
    </div>
  )
}
