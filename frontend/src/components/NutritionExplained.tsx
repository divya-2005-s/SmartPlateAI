import { ChevronDown, Info } from 'lucide-react'
import { explainNutrition, fmt } from '../lib/nutritionExplain'
import type { ExplainInput, GlanceItem, Observation } from '../lib/nutritionExplain'

const TONE: Record<Observation['level'], string> = {
  high: 'bg-amber-50 text-amber-950', medium: 'bg-cream text-ink', low: 'bg-emerald-50 text-emerald-950',
  source: 'bg-emerald-50 text-emerald-950', info: 'bg-sky-50 text-sky-950',
}

function GlanceCard({ g, portionLabel }: { g: GlanceItem; portionLabel: string | null }) {
  const main = g.per100 ?? g.asPrinted
  return (
    <li className="min-w-0 rounded-xl border border-emerald-900/10 bg-white p-3">
      <p className="text-xs font-semibold text-ink-soft">{g.label}</p>
      {!g.available ? (
        <p className="mt-0.5 text-sm text-ink-soft">Information unavailable</p>
      ) : (
        <>
          {main !== null && (
            <p className="mt-0.5 break-words font-display text-lg font-extrabold tabular-nums">{fmt(main)} {g.unit}
              <span className="block font-sans text-xs font-normal text-ink-soft">{g.per100 !== null ? 'per 100 g' : 'as printed'}</span></p>
          )}
          {g.perServing !== null && portionLabel && (
            <p className="text-sm tabular-nums">{fmt(g.perServing)} {g.unit} <span className="text-xs text-ink-soft">{portionLabel}</span>
              {g.dvPercent !== null && <span className="ml-1 text-xs font-semibold text-emerald-800">{g.dvPercent}% DV</span>}</p>
          )}
          {g.derived && <p className="mt-0.5 text-xs text-ink-soft">{g.derived}</p>}
        </>
      )}
    </li>
  )
}

/** "Nutrition at a glance", "What this means" and "What these nutrients mean" for one set of source values. */
export default function NutritionExplained({ input, title = 'Nutrition at a glance' }: { input: ExplainInput; title?: string }) {
  const e = explainNutrition(input)
  if (!e.glance.some((g) => g.available) && e.meanings.length === 0) return null
  const portionLabel = input.servingGrams !== null ? `per ${fmt(input.servingGrams)} g` : input.basis === 'perServing' ? 'per serving' : null
  return (
    <div className="space-y-4">
      <section aria-label={title}>
        <h4 className="text-sm font-semibold">{title}</h4>
        <ul className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-3">
          {e.glance.map((g) => <GlanceCard key={g.canon} g={g} portionLabel={portionLabel} />)}
        </ul>
      </section>

      <section aria-label="What this means">
        <h4 className="text-sm font-semibold">What this means</h4>
        {e.portion.length > 0 && (
          <ul className="mt-2 space-y-1 text-sm">{e.portion.map((p) => <li key={p}>{p}</li>)}</ul>
        )}
        {e.observations.length > 0 ? (
          <ul className="mt-2 space-y-1.5">
            {e.observations.map((o) => (
              <li key={o.canon + o.level} className={`rounded-xl px-3 py-2 text-sm ${TONE[o.level]}`}>
                {o.text}<span className="block text-xs opacity-75">Compared with: {o.standard}</span>
              </li>
            ))}
          </ul>
        ) : e.portion.length === 0 && (
          <p className="mt-1 text-sm text-ink-soft">No comparison is possible with the values available.</p>
        )}
        <p className="mt-2 text-xs text-ink-soft">One nutrient does not make a food good or bad: what matters is the portion and your whole day's eating.</p>
      </section>

      {e.meanings.length > 0 && (
        <details className="group rounded-xl border border-emerald-900/10 bg-white">
          <summary className="flex cursor-pointer list-none items-center justify-between gap-2 p-3 text-sm font-semibold">
            What these nutrients mean
            <ChevronDown className="h-4 w-4 shrink-0 transition-transform group-open:rotate-180" aria-hidden="true" />
          </summary>
          <dl className="space-y-2 px-3 pb-3 text-sm">
            {e.meanings.map((m) => (
              <div key={m.canon}>
                <dt className="font-semibold">{m.label}{!m.available && <span className="ml-1 text-xs font-normal text-ink-soft">(information unavailable for this food)</span>}</dt>
                <dd className="text-ink-soft">{m.text}</dd>
              </div>
            ))}
            {e.units.length > 0 && <p className="pt-1 text-xs text-ink-soft">Units: {e.units.join(' · ')}.</p>}
          </dl>
        </details>
      )}

      {e.notes.length > 0 && (
        <ul className="space-y-1 text-xs text-ink-soft">
          {e.notes.map((n) => <li key={n} className="flex gap-1.5"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />{n}</li>)}
        </ul>
      )}
    </div>
  )
}
