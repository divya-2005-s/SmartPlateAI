import { useEffect, useState } from 'react'
import { ChevronDown, CircleHelp, TriangleAlert } from 'lucide-react'
import { explainIngredients } from '../lib/packagedApi'
import type { IngredientComponent, IngredientItem, IngredientsExplained as Explained } from '../lib/packagedApi'
import type { ApiError } from '../lib/foodApi'

const VERIFIED: Record<IngredientComponent['verification'], string> = {
  curated_glossary: 'SmartPlateAI ingredient reference',
  curated_glossary_and_dataset: 'SmartPlateAI ingredient reference and project additive data',
  additive_dataset: 'Project additive data (function only)',
}

function Component({ c }: { c: IngredientComponent }) {
  return (
    <div className="mt-2 rounded-xl bg-cream p-3 text-sm">
      <p className="font-semibold">{c.name}{c.ins ? <span className="ml-1 font-normal text-ink-soft">· INS {c.ins}</span> : null}
        {c.category && <span className="ml-1 font-normal text-ink-soft">· {c.category}</span>}</p>
      {c.what && <p className="mt-1"><span className="font-semibold">What it is: </span>{c.what}</p>}
      {c.why && <p className="mt-1"><span className="font-semibold">Why it is used: </span>{c.why}</p>}
      {c.consider && <p className="mt-1"><span className="font-semibold">What to know: </span>{c.consider}</p>}
      <p className="mt-1 text-xs text-ink-soft">Information source: {VERIFIED[c.verification]}{c.sources.length ? ` (${c.sources.join('; ')})` : ''}</p>
    </div>
  )
}

function Item({ item }: { item: IngredientItem }) {
  const found = item.status !== 'not_found'
  return (
    <li className="py-2">
      <details className="group">
        <summary className="flex cursor-pointer list-none items-start gap-2 text-sm">
          <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 transition-transform group-open:rotate-180" aria-hidden="true" />
          <span className="min-w-0 flex-1 break-words">
            <span className="font-semibold">{item.as_written}</span>
            <span className="block text-xs text-ink-soft">
              {item.components.length ? item.components.map((c) => c.name).join(', ') : item.class ? item.class.name : 'Not in SmartPlateAI\'s reference data'}
              {item.status === 'partly_explained' && ' · partly explained'}
            </span>
          </span>
        </summary>
        <div className="pl-6">
          {item.class && <p className="mt-2 text-sm"><span className="font-semibold">{item.class.name}: </span>{item.class.explanation}</p>}
          {item.components.map((c) => <Component key={(c.key ?? '') + (c.ins ?? '') + c.name} c={c} />)}
          {item.message && (
            <p className="mt-2 flex gap-1.5 text-sm text-ink-soft"><CircleHelp className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
              {item.message}{!found && ' Nothing is guessed from the name.'}</p>
          )}
        </div>
      </details>
    </li>
  )
}

/** "Ingredients explained": each ingredient as printed, explained only from verified reference data. */
export default function IngredientsExplained({ text, source, uncertain }: { text: string | null | undefined; source: string; uncertain: boolean }) {
  // The result is stored with the request it answers, so loading is derived (no state reset inside the effect).
  const key = `${source}|${uncertain}|${text ?? ''}`
  const [res, setRes] = useState<{ key: string; data: Explained | null; error: ApiError | null } | null>(null)

  useEffect(() => {
    if (!text || !text.trim()) return
    const ac = new AbortController()
    explainIngredients(text, source, uncertain, ac.signal)
      .then((r) => setRes({ key, data: r.ok ? r.data : null, error: r.ok ? null : r.error }))
      .catch(() => undefined) // aborted
    return () => ac.abort()
  }, [key, text, source, uncertain])

  if (!text || !text.trim()) return null
  const loading = res?.key !== key
  const data = loading ? null : res!.data
  const error = loading ? null : res!.error
  return (
    <section className="mt-6 rounded-3xl border border-emerald-900/10 bg-white p-5 shadow-soft sm:p-6" aria-labelledby="ing-explained">
      <h2 id="ing-explained" className="font-display text-xl font-extrabold">Ingredients explained</h2>
      <p className="mt-1 text-sm text-ink-soft">What each ingredient is and why it is used. Tap an ingredient for details.</p>
      {uncertain && (
        <p className="mt-3 flex gap-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
          <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" />
          This list was read automatically from your photo ({source}) and may contain reading errors. Check the physical label, especially for allergens.
        </p>
      )}
      {loading && <p role="status" className="mt-3 text-sm text-ink-soft">Looking up the ingredients…</p>}
      {error && <p role="alert" className="mt-3 text-sm text-red-800">{error.message}</p>}
      {data && (
        <>
          <p className="mt-3 text-xs text-ink-soft">
            {data.counts.explained} of {data.counts.total} explained{data.counts.partly_explained ? `, ${data.counts.partly_explained} partly` : ''}
            {data.counts.not_found ? `, ${data.counts.not_found} not in the reference data` : ''}. Source of the list: {source}.
          </p>
          <ul className="mt-2 divide-y divide-emerald-900/5">{data.items.map((i, n) => <Item key={n} item={i} />)}</ul>
          <ul className="mt-3 list-disc space-y-1 pl-5 text-xs text-ink-soft">{data.notes.filter((n) => !n.startsWith('This ingredient list was read')).map((n) => <li key={n}>{n}</li>)}</ul>
        </>
      )}
    </section>
  )
}
