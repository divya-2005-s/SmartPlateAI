import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent, FormEvent } from 'react'
import { TriangleAlert, Camera, ChevronDown, ImagePlus, Info, RefreshCw, ScanBarcode, ScanText, Search, X } from 'lucide-react'
import { analyzePackaged, getProduct, lookupBarcode, searchProducts } from '../lib/packagedApi'
import type { Additive, BarcodeSuccess, Candidate, PackagedSuccess, Precaution, ProductDetail, ProductView, SearchResult } from '../lib/packagedApi'
import { newRequestKey } from '../lib/foodApi'
import type { ApiError } from '../lib/foodApi'
import type { AnalysisContext } from '../lib/chatApi'
import CameraCapture from './CameraCapture'
import DropZone from './DropZone'
import { AllergenAlertsCard, ExternalCard, LabelDates, SaveActions } from './AnalysisExtras'
import { Badge } from './ui'
import IngredientsExplained from './IngredientsExplained'
import NutritionExplained from './NutritionExplained'

/** Drinks are compared per 100 ml with different criteria, so the per-100 g food comparison is skipped for them. */
const isDrink = (category: string | null | undefined) => /beverage|drink|juice|soda|\bmilk\b|\bwater\b/i.test(category ?? '')

const MAX_MB = 8
const fmt = (v: number) => String(Math.round(v * 100) / 100)

type Side = 'front' | 'back' | 'closeup'
const SIDE_NAME: Record<Side, string> = { front: 'front', back: 'back', closeup: 'close-up' }
type Photo = { file: File; url: string }
type Props = { active?: boolean; onContextChange?: (ctx: AnalysisContext | null) => void }

function PhotoSlot({ side, photo, onFile, onRemove, onCamera, disabled }: {
  side: Side; photo: Photo | null; onFile: (f: File) => void; onRemove: () => void; onCamera: () => void; disabled: boolean
}) {
  const title = side === 'front' ? 'Front of package' : side === 'back' ? 'Back of package' : 'Close-up (optional)'
  const hint = side === 'front' ? 'Brand, product name and variant' : side === 'back' ? 'Ingredients and nutrition table' : 'Barcode or nutrition table, filling the frame'
  const pick = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (f) onFile(f)
  }
  return (
    <div className="flex min-w-0 flex-col rounded-2xl border border-emerald-900/10 p-3">
      <div className="mb-2">
        <h3 className="text-sm font-semibold">{title}</h3>
        <p className="text-xs text-ink-soft">{hint}</p>
      </div>
      {photo ? (
        <div className="relative">
          <img src={photo.url} alt={title} className="aspect-[4/3] w-full rounded-xl bg-cream object-contain" />
          <div className="mt-2 flex flex-wrap gap-2">
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-emerald-900/15 px-3 py-1.5 text-xs font-semibold hover:bg-emerald-50 focus-within:ring-4 focus-within:ring-emerald-600/20">
              <ImagePlus className="h-3.5 w-3.5" aria-hidden="true" /> Replace
              <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" onChange={pick} disabled={disabled} aria-label={`Replace ${title.toLowerCase()} photo`} />
            </label>
            <button type="button" onClick={onRemove} disabled={disabled}
              className="inline-flex items-center gap-1.5 rounded-full border border-emerald-900/15 px-3 py-1.5 text-xs font-semibold hover:bg-emerald-50">
              <X className="h-3.5 w-3.5" aria-hidden="true" /> Remove
            </button>
          </div>
        </div>
      ) : (
        <div className="grid flex-1 gap-2">
          <DropZone compact title={`Upload ${side} photo`} hint={`JPG, PNG or WebP, up to ${MAX_MB} MB.`} onFile={onFile} disabled={disabled}
            inputLabel={`Upload ${title.toLowerCase()} photo`} />
          <button type="button" onClick={onCamera} disabled={disabled}
            className="inline-flex items-center justify-center gap-2 rounded-full border border-emerald-900/15 px-4 py-2 text-sm font-semibold hover:bg-emerald-50">
            <Camera className="h-4 w-4 text-emerald-700" aria-hidden="true" /> Use camera
          </button>
        </div>
      )}
    </div>
  )
}

function LabelNutritionCard({ scan }: { scan: PackagedSuccess }) {
  const ln = scan.label_nutrition
  if (!ln || ln.rows.length === 0) return null
  const tone = { agree: 'green', ocr_only: 'grey', ai_only: 'blue', conflict: 'amber' } as const
  const word = { agree: 'both readers agree', ocr_only: 'OCR only', ai_only: 'AI reading only', conflict: 'readings differ' }
  return (
    <section className="mt-5 rounded-3xl border border-emerald-900/10 bg-white p-5 shadow-soft sm:p-6">
      <p className="text-xs font-semibold uppercase tracking-wider text-emerald-700">Read from your package</p>
      <h2 className="font-display text-xl font-extrabold">Nutrition on the label</h2>
      <p className="text-xs text-ink-soft">Basis: {ln.basis === 'unknown' ? 'not detected on the label' : ln.basis}
        {scan.identity?.serving_size ? ` · serving size as printed: ${scan.identity.serving_size}` : ''}
        {ln.readers.length ? ` · read by ${ln.readers.map((r) => (r === 'openai' ? 'OpenAI Vision' : r === 'gemini' ? 'Google Gemini' : 'Tesseract OCR')).join(' and ')}` : ''}</p>
      <div className="mt-3 max-w-full overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead><tr className="border-b border-emerald-900/10 text-xs uppercase tracking-wide text-ink-soft">
            <th scope="col" className="py-1.5 pr-3">Nutrient</th><th scope="col" className="py-1.5 pr-3 text-right">Value</th><th scope="col" className="py-1.5">Check</th>
          </tr></thead>
          <tbody>
            {ln.rows.map((r) => (
              <tr key={r.key} className="border-b border-emerald-900/5 align-top last:border-0">
                <td className="py-1.5 pr-3">{r.label}</td>
                <td className="py-1.5 pr-3 text-right tabular-nums">
                  {r.value !== null ? `${fmt(r.value)} ${r.unit}` : <span className="text-amber-800">Not shown: OCR {r.ocr_value ?? '–'} vs AI {r.ai_value ?? '–'} {r.unit}</span>}
                </td>
                <td className="py-1.5"><Badge tone={tone[r.status]}>{word[r.status]}</Badge></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {ln.note && <p className="mt-2 text-xs text-amber-800">{ln.note}</p>}
      <p className="mt-2 text-xs text-ink-soft">Values are copied from the label in your photo. Where the two readers disagree, no value is shown; check the pack.</p>
      <div className="mt-4 border-t border-emerald-900/10 pt-4">
        <NutritionExplained title="Label nutrition at a glance" input={{
          nutrients: ln.rows.map((r) => ({ key: r.key, label: r.label, unit: r.unit,
            per100: ln.basis === 'per serving' ? null : r.value, perServing: ln.basis === 'per serving' ? r.value : null })),
          servingGrams: ln.basis === 'per serving' ? scan.label.serving_size_g : null,
          basis: ln.basis === 'per 100 g' ? 'per100g' : ln.basis === 'per serving' ? 'perServing' : 'unknown',
          liquid: isDrink(scan.product?.category) }} />
      </div>
    </section>
  )
}

export default function PackagedAnalyzer({ active = true, onContextChange }: Props) {
  const [photos, setPhotos] = useState<Record<Side, Photo | null>>({ front: null, back: null, closeup: null })
  const [cameraFor, setCameraFor] = useState<Side | null>(null)
  const [requestKey, setRequestKey] = useState<string>(() => newRequestKey())
  const [serving, setServing] = useState('')
  const [loading, setLoading] = useState(false)
  const [scan, setScan] = useState<PackagedSuccess | null>(null)
  const [selected, setSelected] = useState<ProductDetail | null>(null)
  const [barcodeHit, setBarcodeHit] = useState<BarcodeSuccess | null>(null)
  const [error, setError] = useState<ApiError | null>(null)
  const [localError, setLocalError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [results, setResults] = useState<Candidate[] | null>(null)
  const [extResults, setExtResults] = useState<SearchResult['external'] | null>(null)
  const [extPicking, setExtPicking] = useState<string | null>(null)
  const searchRef = useRef<HTMLInputElement | null>(null)
  const [searching, setSearching] = useState(false)
  const [picking, setPicking] = useState<string | null>(null)
  const abortRef = useRef<AbortController | null>(null)
  const resultRef = useRef<HTMLDivElement | null>(null)
  useEffect(() => { if (!active) setCameraFor(null) }, [active])

  const grams = (): number | undefined | null => {
    if (serving.trim() === '') return undefined
    const g = Number(serving)
    return Number.isFinite(g) && g >= 1 && g <= 2000 ? g : null
  }

  const clearResults = () => {
    abortRef.current?.abort()
    setScan(null)
    setSelected(null)
    setBarcodeHit(null)
    setError(null)
    setLocalError(null)
    setResults(null)
    setExtResults(null)
    setLoading(false)
  }

  const reset = () => {
    clearResults()
    Object.values(photos).forEach((p) => p && URL.revokeObjectURL(p.url))
    setPhotos({ front: null, back: null, closeup: null })
    setServing('')
    setQuery('')
  }

  const setPhoto = (side: Side, f: File | null) => {
    setCameraFor(null)
    clearResults()
    if (f) {
      if (!f.type.startsWith('image/')) return setLocalError('Please choose an image file (JPG, PNG or WebP).')
      if (f.size > MAX_MB * 1024 * 1024) return setLocalError(`The image is larger than ${MAX_MB} MB. Please upload a smaller photo.`)
    }
    setPhotos((prev) => {
      if (prev[side]) URL.revokeObjectURL(prev[side]!.url)
      return { ...prev, [side]: f ? { file: f, url: URL.createObjectURL(f) } : null }
    })
    setRequestKey(newRequestKey())
  }

  const analyse = async (confirmSame = false) => {
    if (!photos.front && !photos.back && !photos.closeup) return
    const g = grams()
    if (g === null) return setLocalError('Serving size must be between 1 and 2000 grams.')
    clearResults()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    try {
      const r = await analyzePackaged({ front: photos.front?.file, back: photos.back?.file, closeup: photos.closeup?.file }, g, ctrl.signal,
        { confirmSame, requestKey: `${requestKey}-${confirmSame ? 'c' : 'n'}-${g ?? 'na'}` })
      if (r.ok) setScan(r.data)
      else setError(r.error)
    } catch {
      /* cancelled */
    } finally {
      if (abortRef.current === ctrl) setLoading(false)
    }
  }

  useEffect(() => {
    if ((scan || selected || error) && resultRef.current) resultRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [scan, selected, error])

  const pick = async (id: string) => {
    const g = grams()
    if (g === null) return setLocalError('Serving size must be between 1 and 2000 grams.')
    setPicking(id)
    setLocalError(null)
    try {
      const r = await getProduct(id, g)
      if (r.ok) setSelected(r.data)
      else setLocalError(r.error.message)
    } finally {
      setPicking(null)
    }
  }

  const search = async (e: FormEvent) => {
    e.preventDefault()
    if (query.trim().length < 2) return
    setSearching(true)
    setLocalError(null)
    try {
      const r = await searchProducts(query.trim())
      if (r.ok) {
        setResults(r.data.results)
        setExtResults(r.data.external ?? null)
      } else setLocalError(r.error.message)
    } finally {
      setSearching(false)
    }
  }

  const correct = (q: string) => {
    setQuery(q)
    searchRef.current?.scrollIntoView({ behavior: 'smooth', block: 'center' })
    window.setTimeout(() => searchRef.current?.focus(), 300)
  }

  const pickExternal = async (code: string) => {
    setExtPicking(code)
    setLocalError(null)
    try {
      const r = await lookupBarcode(code, undefined, newRequestKey())
      if (r.ok) { clearResults(); setBarcodeHit(r.data) }
      else setLocalError(r.error.message)
    } finally {
      setExtPicking(null)
    }
  }

  // What the chatbot sees: only the data on screen, with its source and identification status.
  useEffect(() => {
    if (!onContextChange) return
    if (barcodeHit?.product && !scan && !selected) {
      const p = barcodeHit.product
      return onContextChange({
        kind: 'packaged', title: [p.brand, p.name].filter(Boolean).join(' ') || `Barcode ${barcodeHit.barcode}`,
        status: `identified by barcode ${barcodeHit.barcode} in Open Food Facts (crowd-sourced database)`, category: 'Packaged Food',
        product: { name: p.name, brand: p.brand, ingredients: p.ingredients_text, allergens_declared: p.allergens, may_contain: p.traces,
          nutrition: { source: p.source, basis: 'per 100 g', values: p.nutrition_per_100g } },
        additives: p.additive_codes.map((c) => `INS ${c}`),
      })
    }
    if (!scan && !selected) return onContextChange(null)
    const product = selected?.product ?? scan?.product ?? null
    const ident = scan?.identity
    const status = selected
      ? 'product selected by the user from the dataset (not identified from the photo)'
      : scan?.match.status === 'matched'
        ? `matched to a dataset product from the package text (match score ${scan.match.confidence})`
        : scan?.identification?.status === 'identified'
          ? `not in the local dataset; identified in ${scan.identification.source} via ${scan.identification.method}`
          : `NOT identified (${scan?.match.status}); only what was read from the package is known`
    const offP = scan && !selected && scan.external?.status === 'found' ? scan.external.product : undefined
    const labelTitle = (ident && [ident.brand, ident.product_name, ident.variant].filter(Boolean).join(' '))
      || (offP && [offP.brand, offP.name].filter(Boolean).join(' '))
      || (scan?.ocr.front_prominent?.length ? `${scan.ocr.front_prominent.slice(0, 4).join(' ')} (as printed)` : '')
    onContextChange({
      kind: 'packaged',
      title: product ? `${product.brand ? product.brand + ' ' : ''}${product.name}` : labelTitle || 'Unidentified packaged product',
      status,
      category: 'Packaged Food',
      package_as_printed: scan && !selected && ident ? { ...ident } : undefined,
      open_food_facts_record: offP && scan?.match.status !== 'matched' ? {
        name: offP.name, brand: offP.brand, ingredients: offP.ingredients_text, allergens_declared: offP.allergens, may_contain: offP.traces,
        nutrition: { source: offP.source, basis: 'per 100 g', values: offP.nutrition_per_100g } } : undefined,
      product: product && {
        name: product.name, brand: product.brand, category: product.category, ingredients: product.ingredients_text,
        allergens: product.allergens_text,
        nutrition: {
          source: product.nutrition.source, basis: product.nutrition.basis,
          values: product.nutrition.nutrients.map((n) => ({ nutrient: n.label, value: n.value, unit: n.unit, per_serving: n.per_serving, flags: n.flags })),
          not_available: product.nutrition.not_available,
        },
      },
      label_read_from_photo: scan && !selected ? {
        ingredients: scan.label.ingredients_text,
        ingredients_source: scan.label.ingredients_source,
        nutrition_basis: scan.label_nutrition?.basis ?? scan.label.nutrition.basis,
        nutrition: (scan.label_nutrition?.rows ?? []).map((r) => ({ nutrient: r.label, value: r.value, unit: r.unit, check: r.status })),
        allergens: scan.label.allergens,
        serving_size: ident?.serving_size ?? scan.label.serving_size_g,
      } : undefined,
      additives: (selected?.additives ?? scan?.additives ?? []).map((a) => ({ code: a.ins_label, name: a.name, function: a.function, dataset_notes: a.notes })),
      additives_named_without_code: scan?.unidentified_additives,
      precautions: (selected?.precautions ?? scan?.precautions ?? []).map((p) => `${p.text} [${p.source}]`),
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [scan, selected, barcodeHit])

  const product: ProductView | null = selected?.product ?? scan?.product ?? null
  const additives = selected?.additives ?? scan?.additives ?? []
  const precautions = selected?.precautions ?? scan?.precautions ?? []
  const candidates = scan && scan.match.status !== 'matched' ? scan.match.candidates : []
  const busy = loading || picking !== null
  const ident = scan?.identity
  const identTitle = ident ? [ident.brand, ident.product_name].filter(Boolean).join(' ') : ''

  return (
    <div className="text-ink">
      <section className="rounded-3xl border border-emerald-900/10 bg-white p-4 shadow-soft sm:p-6" aria-labelledby="pk-upload-h">
        <h2 id="pk-upload-h" className="font-display text-lg font-extrabold">Photograph the package</h2>
        <p className="mt-1 text-sm text-ink-soft">Add the front to identify the product and the back to read ingredients and nutrition. Both should show the same pack.</p>
        {cameraFor ? (
          <div className="mt-4">
            <p className="mb-2 text-sm font-semibold">Capturing the {SIDE_NAME[cameraFor]} of the package</p>
            <CameraCapture onCapture={(f) => setPhoto(cameraFor, f)} onClose={() => setCameraFor(null)} label={`Capture ${SIDE_NAME[cameraFor]}`}
              guide={cameraFor === 'closeup' ? 'closeup' : 'package'} />
          </div>
        ) : (
          <>
            <div className="mt-4 grid gap-3 sm:grid-cols-2">
              {(['front', 'back'] as const).map((side) => (
                <PhotoSlot key={side} side={side} photo={photos[side]} disabled={loading}
                  onFile={(f) => setPhoto(side, f)} onRemove={() => setPhoto(side, null)} onCamera={() => { setLocalError(null); setCameraFor(side) }} />
              ))}
            </div>
            {(photos.front || photos.back || photos.closeup) && (
              <div className="mt-3 sm:max-w-[calc(50%-0.375rem)]">
                <PhotoSlot side="closeup" photo={photos.closeup} disabled={loading}
                  onFile={(f) => setPhoto('closeup', f)} onRemove={() => setPhoto('closeup', null)}
                  onCamera={() => { setLocalError(null); setCameraFor('closeup') }} />
              </div>
            )}
          </>
        )}
        {(photos.front || photos.back || photos.closeup) && !cameraFor && (
          <div className="mt-4 flex flex-wrap items-end gap-3">
            <div>
              <label htmlFor="pk-serving" className="mb-1 block text-sm font-semibold">Serving size in grams (optional)</label>
              <input id="pk-serving" inputMode="decimal" value={serving} onChange={(e) => setServing(e.target.value)} placeholder="e.g. 30"
                className="w-40 rounded-xl border border-emerald-900/15 px-4 py-2.5 outline-none focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/15" />
            </div>
            <button type="button" onClick={() => void analyse(false)} disabled={loading}
              className="inline-flex items-center gap-2 rounded-full bg-emerald-600 px-6 py-2.5 font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:opacity-60">
              <ScanText className="h-5 w-5" aria-hidden="true" /> {loading ? 'Reading package…' : [photos.front, photos.back, photos.closeup].filter(Boolean).length > 1 ? 'Analyse photos' : 'Analyse photo'}
            </button>
            <button type="button" onClick={reset} disabled={loading}
              className="inline-flex items-center gap-2 rounded-full border border-emerald-900/15 px-5 py-2.5 font-semibold hover:bg-emerald-50">
              <RefreshCw className="h-4 w-4" aria-hidden="true" /> Start again
            </button>
          </div>
        )}
        {photos.front && !photos.back && !cameraFor && (
          <p className="mt-3 flex gap-2 text-xs text-ink-soft"><Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden="true" />
            Without the back label, ingredients and nutrition may be incomplete; they can only come from a matched product record.</p>
        )}
        {loading && (
          <div role="status" className="mt-4 flex items-center gap-3 rounded-xl bg-emerald-50/60 px-4 py-3 text-sm text-ink-soft">
            <div className="h-5 w-5 animate-spin rounded-full border-2 border-emerald-600 border-t-transparent" />
            Reading the package (this can take 10–30 seconds)…
          </div>
        )}
      </section>

      <div ref={resultRef} aria-live="polite" className="scroll-mt-24">
        {localError && <p role="alert" className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800">{localError}</p>}
        {error && (
          <div role="alert" className={`mt-5 rounded-2xl border p-5 ${error.code === 'PACKAGE_MISMATCH' ? 'border-amber-300 bg-amber-50 text-amber-950' : 'border-red-200 bg-red-50 text-red-800'}`}>
            <p className="font-semibold">{error.message}</p>
            <p className="mt-1 text-xs opacity-80">Code: {error.code}</p>
            {error.code === 'PACKAGE_MISMATCH' && (
              <div className="mt-3 flex flex-wrap gap-2">
                <button type="button" onClick={() => void analyse(true)} disabled={loading}
                  className="rounded-full bg-amber-700 px-4 py-2 text-sm font-semibold text-white hover:bg-amber-800 disabled:opacity-50">
                  They are the same product, continue
                </button>
                <span className="self-center text-xs">or replace one of the photos above.</span>
              </div>
            )}
          </div>
        )}

        {scan && !selected && (ident?.brand || ident?.product_name) && (
          <section className="mt-5 rounded-3xl border border-emerald-900/10 bg-white p-5 shadow-soft sm:p-6">
            <p className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wider text-emerald-700">
              Packaged Food <span aria-hidden="true">›</span> <span className="normal-case tracking-normal text-ink-soft">Read from the package (as printed)</span>
            </p>
            <h2 className="mt-1 break-words font-display text-2xl font-extrabold">{identTitle || 'Product name not readable'}</h2>
            <p className="mt-1 text-sm text-ink-soft">{[ident?.variant, ident?.package_type, ident?.net_quantity].filter(Boolean).join(' · ')}</p>
            {ident?.claims && ident.claims.length > 0 && (
              <p className="mt-2 flex flex-wrap gap-1.5">{ident.claims.map((c) => <Badge key={c} tone="grey">{c}</Badge>)}</p>
            )}
            {ident?.manufacturer && <p className="mt-2 text-xs text-ink-soft">Manufacturer (as printed): {ident.manufacturer}</p>}
            {scan.consistency?.status === 'consistent' && <p className="mt-2 text-xs text-emerald-800">Front and back appear to be the same product.</p>}
            <p className="mt-2 text-xs text-ink-soft">Label claims are the manufacturer's statements, not verified by SmartPlateAI.</p>
          </section>
        )}

        {scan && !selected && (
          <MatchCard scan={scan} candidates={candidates} picking={picking} onPick={pick} onCorrect={correct} />
        )}

        {product && (
          <section className="mt-5 rounded-3xl border border-emerald-900/10 bg-white p-5 shadow-soft sm:p-6">
            <p className="text-xs font-semibold uppercase tracking-wider text-emerald-700">
              {selected ? 'Selected by you' : 'Matched product record'}
            </p>
            <h2 className="break-words font-display text-2xl font-extrabold">{product.name}</h2>
            <p className="mt-1 text-sm text-ink-soft">
              {[product.brand, product.category].filter(Boolean).join(' · ') || 'Brand not recorded'}
              {scan && !selected && ` · text-match score ${(scan.match.confidence * 100).toFixed(0)}%`}
            </p>
            {selected && <p className="mt-2 text-sm text-ink-soft">Chosen from the dataset; not identified from the photo.</p>}
            <DatasetNutrition product={product} />
            {product.ingredients_text && (
              <div className="mt-5">
                <h3 className="font-semibold">Ingredients (dataset record)</h3>
                <p className="mt-1 text-sm text-ink-soft">{product.ingredients_text}</p>
              </div>
            )}
          </section>
        )}

        {scan && !selected && <LabelNutritionCard scan={scan} />}
        {(scan || selected) && <AllergenAlertsCard alerts={selected ? selected.allergen_alerts : scan?.allergen_alerts} />}
        {scan && !selected && <LabelCard scan={scan} />}
        {scan && !selected && <ExternalCard ext={scan.external} />}
        {scan && !selected && scan.label.ingredients_text ? (
          <IngredientsExplained text={scan.label.ingredients_text} source={scan.label.ingredients_source ?? 'reading of the label photo'} uncertain />
        ) : product?.ingredients_text ? (
          <IngredientsExplained text={product.ingredients_text} source="product record in the SmartPlateAI dataset" uncertain={false} />
        ) : null}
        {(scan || selected) && <AdditivesCard additives={additives} unidentified={selected ? [] : scan?.unidentified_additives ?? []} />}
        {(scan || selected) && <PrecautionsCard items={precautions} />}
        {(scan || selected) && (
          <div className="mt-5">
            <SaveActions analysisId={selected?.analysis_id ?? scan?.analysis_id} kind="packaged" history={selected?.history ?? scan?.history}
              canLog={Boolean((selected?.product ?? scan?.product)?.nutrition.basis_known || scan?.label_nutrition?.basis === 'per 100 g')} />
          </div>
        )}

        {(scan || selected) && (
          <ul className="mt-4 list-disc space-y-1 pl-5 text-xs text-ink-soft">
            {[...(scan && !selected ? scan.warnings : []), ...(selected?.notes ?? scan?.notes ?? [])].map((n) => <li key={n}>{n}</li>)}
          </ul>
        )}

        <section className="mt-6 rounded-3xl border border-emerald-900/10 bg-white p-5 shadow-soft sm:p-6">
          <BarcodeLookup active={active} disabled={busy} hit={barcodeHit} onFound={(b) => { clearResults(); setBarcodeHit(b) }} />
          <h2 className="mt-6 font-display text-xl font-extrabold">Search by product name</h2>
          <p className="mt-1 text-sm text-ink-soft">Use this if the package could not be identified or the match is wrong. Searches the local dataset and Open Food Facts.</p>
          <form onSubmit={search} className="mt-3 flex gap-2">
            <label htmlFor="pk-search" className="sr-only">Product name or brand</label>
            <input id="pk-search" ref={searchRef} value={query} onChange={(e) => setQuery(e.target.value)} placeholder="e.g. Maggi masala noodles"
              className="min-w-0 flex-1 rounded-xl border border-emerald-900/15 px-4 py-2.5 outline-none focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/15" />
            <button type="submit" disabled={searching || query.trim().length < 2}
              className="inline-flex items-center gap-2 rounded-full bg-emerald-700 px-5 py-2.5 font-semibold text-white hover:bg-emerald-800 disabled:opacity-50">
              <Search className="h-4 w-4" aria-hidden="true" /> {searching ? 'Searching…' : 'Search'}
            </button>
          </form>
          {results && results.length === 0 && <p className="mt-3 text-sm text-ink-soft">No products in the local dataset match that search.</p>}
          {results && results.length > 0 && <h3 className="mt-4 text-xs font-semibold uppercase tracking-wider text-ink-soft">Local dataset</h3>}
          {results && results.length > 0 && (
            <ul className="mt-3 divide-y divide-emerald-900/5">
              {results.map((r) => (
                <li key={r.id} className="flex items-center gap-3 py-2">
                  <span className="min-w-0 flex-1 break-words"><span className="font-semibold">{r.name}</span>{r.brand && <span className="text-ink-soft"> · {r.brand}</span>}</span>
                  <button type="button" onClick={() => pick(r.id)} disabled={picking !== null}
                    className="rounded-full border border-emerald-900/15 px-4 py-1.5 text-sm font-semibold hover:bg-emerald-50 disabled:opacity-50">
                    {picking === r.id ? 'Loading…' : 'Select'}
                  </button>
                </li>
              ))}
            </ul>
          )}
          {extResults && (
            <div className="mt-4">
              <h3 className="text-xs font-semibold uppercase tracking-wider text-ink-soft">Open Food Facts (crowd-sourced)</h3>
              {extResults.results.length === 0 ? (
                <p className="mt-1 text-sm text-ink-soft">{extResults.message ?? 'No Open Food Facts products for that search.'}</p>
              ) : (
                <ul className="mt-1 divide-y divide-emerald-900/5">
                  {extResults.results.map((r) => (
                    <li key={r.code} className="flex items-center gap-3 py-2">
                      <span className="min-w-0 flex-1 break-words"><span className="font-semibold">{r.name ?? 'Unnamed product'}</span>
                        {r.brand && <span className="text-ink-soft"> · {r.brand}</span>}{r.quantity && <span className="text-ink-soft"> · {r.quantity}</span>}
                        <span className="block text-xs tabular-nums text-ink-soft">Barcode {r.code}</span></span>
                      <button type="button" onClick={() => void pickExternal(r.code)} disabled={extPicking !== null}
                        className="rounded-full border border-emerald-900/15 px-4 py-1.5 text-sm font-semibold hover:bg-emerald-50 disabled:opacity-50">
                        {extPicking === r.code ? 'Loading…' : 'Select'}
                      </button>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </section>
      </div>
    </div>
  )
}


function MatchCard({ scan, candidates, picking, onPick, onCorrect }: {
  scan: PackagedSuccess; candidates: Candidate[]; picking: string | null; onPick: (id: string) => void; onCorrect: (q: string) => void
}) {
  const id = scan.identification
  const det = id?.detected
  const guess = (det?.vision_reading || (det?.prominent_words ?? []).slice(0, 4).join(' ')).trim()
  const packName = [scan.identity?.brand, scan.identity?.product_name, scan.identity?.variant].filter(Boolean).join(' · ')
  const evidence = (
    <dl className="mt-3 grid gap-x-6 gap-y-1 text-sm sm:grid-cols-2">
      <div><dt className="inline text-ink-soft">Barcode: </dt><dd className="inline font-medium tabular-nums">{det?.barcode
        ? <>{det.barcode} <span className="text-xs font-normal text-ink-soft">({det.barcode_method})</span></> : 'not found in the photos'}</dd></div>
      <div className="min-w-0"><dt className="inline text-ink-soft">Largest text on the front: </dt>
        <dd className="inline break-words font-medium">{det?.prominent_words?.length ? det.prominent_words.join(', ') : 'none read'}</dd></div>
    </dl>
  )
  if (scan.match.status === 'matched') {
    return (
      <section className="mt-6 rounded-3xl border border-emerald-900/10 bg-emerald-50/40 p-5">
        <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-emerald-800">
          <Badge tone="green">Identified · local dataset</Badge>
          {scan.match.method === 'barcode' ? 'Exact barcode match' : `Label-text match, score ${(scan.match.confidence * 100).toFixed(0)}%`}
        </p>
        <p className="mt-2 text-sm text-ink-soft">{scan.match.reason}</p>
        {evidence}
      </section>
    )
  }
  if (id?.status === 'identified') {
    return (
      <section className="mt-6 rounded-3xl border border-sky-900/15 bg-sky-50/50 p-6">
        <p className="flex flex-wrap items-center gap-2 text-sm font-semibold text-sky-800">
          <Badge tone="blue">Identified · {id.source}</Badge> via {id.method}
        </p>
        <h2 className="mt-2 font-display text-2xl font-extrabold">{[id.brand, id.name].filter(Boolean).join(' · ')}</h2>
        <p className="mt-2 text-sm text-ink-soft">{id.evidence} This product is not in the local dataset, so its details below come from
          Open Food Facts (crowd-sourced) and from your label photo.</p>
        {scan.external?.verified_against_label === false && (
          <p role="alert" className="mt-2 rounded-xl bg-amber-50 p-3 text-sm font-semibold text-amber-900">
            {scan.external.message ?? 'The product name for this barcode was not found on the pack.'} Its Open Food Facts values may
            belong to a different product; rely on the nutrition label in your photo.
          </p>
        )}
        {evidence}
      </section>
    )
  }
  return (
    <section className={`mt-6 rounded-3xl border bg-white p-6 shadow-soft ${scan.match.status === 'uncertain' ? 'border-amber-900/15' : 'border-emerald-900/10'}`}>
      <p className="text-sm font-semibold uppercase tracking-wider text-amber-700">
        {scan.match.status === 'uncertain' ? 'Product not confirmed' : scan.match.status === 'unavailable' ? 'Dataset unavailable' : 'Product not identified'}
      </p>
      <h2 className="mt-1 font-display text-2xl font-extrabold">
        {candidates.length ? 'Is it one of these?' : 'The label was read, but the exact product could not be confirmed'}
      </h2>
      {packName && (
        <p className="mt-2 text-sm">
          <span className="font-semibold">Read from the pack:</span> {packName}
          <span className="block text-xs text-ink-soft">As printed on the package. It was not matched to a product database, so no
            database nutrition is shown; the nutrition below comes only from the label in your photo.</span>
        </p>
      )}
      <p className="mt-2 text-sm text-ink-soft">{scan.match.reason} Everything read from your photos is still shown below.</p>
      {scan.external && scan.external.status !== 'found' && scan.external.message && (
        <p className="mt-2 text-sm text-ink-soft">Open Food Facts: {scan.external.message}</p>
      )}
      {evidence}
      {candidates.length > 0 && (
        <ul className="mt-4 space-y-2">
          {candidates.map((c) => (
            <li key={c.id} className="flex items-center gap-3 rounded-xl border border-emerald-900/10 px-4 py-3">
              <span className="min-w-0 flex-1"><span className="font-semibold">{c.name}</span>{c.brand && <span className="text-ink-soft"> · {c.brand}</span>}</span>
              <span className="text-sm tabular-nums text-ink-soft" title="Share of the record's weighted words found on the pack">{(c.score * 100).toFixed(0)}%</span>
              <button type="button" onClick={() => onPick(c.id)} disabled={picking !== null}
                className="rounded-full bg-emerald-700 px-4 py-1.5 text-sm font-semibold text-white hover:bg-emerald-800 disabled:opacity-50">
                {picking === c.id ? 'Loading…' : 'This one'}
              </button>
            </li>
          ))}
        </ul>
      )}
      <button type="button" onClick={() => onCorrect(guess)}
        className="mt-4 inline-flex items-center gap-2 rounded-full border border-emerald-900/15 px-4 py-2 text-sm font-semibold hover:bg-emerald-50">
        <Search className="h-4 w-4" aria-hidden="true" /> Correct the name and search again
      </button>
    </section>
  )
}

function DatasetNutrition({ product }: { product: ProductView }) {
  const n = product.nutrition
  if (!n.nutrients.length) return <p className="mt-5 text-sm text-ink-soft">The dataset has no nutrition values for this product.</p>
  return (
    <div className="mt-5 overflow-x-auto">
      <h3 className="font-semibold">Nutrition (dataset record)</h3>
      <p className="text-xs text-ink-soft">{n.basis}</p>
      <table className="mt-2 w-full text-left text-sm">
        <thead>
          <tr className="border-b border-emerald-900/10">
            <th className="py-2 pr-4">Nutrient</th>
            <th className="py-2 pr-4">{n.basis_known ? 'Per 100 g' : 'Value (as stored)'}</th>
            {n.serving_grams !== null && <th className="py-2">Per {n.serving_grams} g</th>}
          </tr>
        </thead>
        <tbody>
          {n.nutrients.map((x) => (
            <tr key={x.key} className="border-b border-emerald-900/5 align-top">
              <td className="py-2 pr-4">{x.label}</td>
              <td className="py-2 pr-4">
                {x.value === null ? <span className="text-ink-soft">Not available</span> : `${fmt(x.value)} ${x.unit}`}
                {x.flags.map((f) => <span key={f} className="block text-xs text-amber-700">{f}</span>)}
              </td>
              {n.serving_grams !== null && <td className="py-2">{x.per_serving === null ? 'Not available' : `${fmt(x.per_serving)} ${x.unit}`}</td>}
            </tr>
          ))}
        </tbody>
      </table>
      <div className="mt-4">
        <NutritionExplained title="Nutrition at a glance (dataset record)" input={{
          nutrients: n.nutrients.map((x) => ({ key: x.key, label: x.label, unit: x.unit, per100: x.value, perServing: x.per_serving })),
          servingGrams: n.serving_grams, basis: n.basis_known ? 'per100g' : 'unknown', liquid: isDrink(product.category) }} />
      </div>
    </div>
  )
}

function LabelCard({ scan }: { scan: PackagedSuccess }) {
  const [showText, setShowText] = useState(false)
  const l = scan.label
  const values = Object.entries(l.nutrition.values)
  return (
    <section className="mt-6 rounded-3xl border border-emerald-900/10 bg-white p-6 shadow-soft">
      <p className="text-sm font-semibold uppercase tracking-wider text-emerald-600">Read from your photo</p>
      <h2 className="font-display text-2xl font-extrabold">Label details</h2>
      <p className="mt-1 text-xs text-ink-soft">
        OCR quality: {scan.ocr.quality} · {scan.ocr.word_count} words · average confidence {scan.ocr.confidence.toFixed(0)}%
        {scan.ocr.rotation ? ` · image rotated ${scan.ocr.rotation}°` : ''}
      </p>
      <div className="mt-4 grid gap-5 md:grid-cols-2">
        <div>
          <h3 className="font-semibold">Nutrition on the label</h3>
          {values.length === 0 ? <p className="mt-1 text-sm text-ink-soft">No nutrition values could be read.</p> : (
            <>
              <p className="text-xs text-ink-soft">Basis: {l.nutrition.basis === 'unknown' ? 'not detected on the label' : l.nutrition.basis}
                {l.serving_size_g ? ` · serving size ${l.serving_size_g} g` : ''}</p>
              <ul className="mt-2 space-y-1 text-sm">
                {values.map(([k, v]) => (
                  <li key={k} className="flex justify-between gap-4 border-b border-emerald-900/5 py-1">
                    <span>{v.label}</span>
                    <span className="text-right tabular-nums">{fmt(v.value)} {v.unit}
                      {v.flags.map((f) => <span key={f} className="block text-xs text-amber-700">{f}</span>)}</span>
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div>
          <h3 className="font-semibold">Ingredients on the label</h3>
          <p className="mt-1 text-sm text-ink-soft">{l.ingredients_text ?? 'No ingredient list could be read.'}</p>
          {l.ingredients_text && l.ingredients_source && <p className="mt-1 text-xs text-ink-soft">Source: {l.ingredients_source}</p>}
          {(l.identifiers.net_quantity || l.identifiers.fssai_licence) && (
            <p className="mt-3 text-xs text-ink-soft">
              {l.identifiers.net_quantity && <>Net quantity: {l.identifiers.net_quantity}. </>}
              {l.identifiers.fssai_licence && <>FSSAI licence: {l.identifiers.fssai_licence}.</>}
            </p>
          )}
        </div>
      </div>
      <LabelDates dates={l.dates} storage={l.storage} />
      <button type="button" onClick={() => setShowText((v) => !v)} aria-expanded={showText}
        className="mt-5 inline-flex items-center gap-1 text-sm font-semibold text-emerald-700 hover:underline">
        <ChevronDown className={`h-4 w-4 transition-transform ${showText ? 'rotate-180' : ''}`} aria-hidden="true" /> {showText ? 'Hide' : 'Show'} raw label text
      </button>
      {showText && <pre className="mt-2 max-h-64 overflow-auto whitespace-pre-wrap rounded-xl bg-cream p-3 text-xs">{scan.ocr.text}</pre>}
    </section>
  )
}

function AdditivesCard({ additives, unidentified = [] }: { additives: Additive[]; unidentified?: string[] }) {
  return (
    <section className="mt-6 rounded-3xl border border-emerald-900/10 bg-white p-6 shadow-soft">
      <h2 className="font-display text-xl font-extrabold">Additives (INS codes)</h2>
      {unidentified.length > 0 && (
        <p className="mt-2 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
          Also printed on the label but not matched to a known INS / E code: {unidentified.join(', ')}. Check the physical label.
        </p>
      )}
      {additives.length === 0 ? (
        <p className="mt-2 text-sm text-ink-soft">No INS / E codes were found on the label or in the dataset record. This does not prove the product has none.</p>
      ) : (
        <ul className="mt-3 divide-y divide-emerald-900/5">
          {additives.map((a) => (
            <li key={a.code} className="py-3">
              <p className="font-semibold">{a.ins_label}{a.name ? ` · ${a.name}` : ''}</p>
              <p className="text-sm text-ink-soft">
                {a.function ? `Function: ${a.function}` : 'Function not recorded in the dataset.'}
                {!a.in_reference && ' Not found in the project additive data.'}
              </p>
              <p className="text-xs text-ink-soft">
                {a.found_on_label ? 'Read from the label' : 'From the dataset record'}{a.source ? ` · info: ${a.source}` : ''}
              </p>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-ink-soft">Approved additives are permitted within legal limits; listing one here is not a safety warning.</p>
    </section>
  )
}

function PrecautionsCard({ items }: { items: Precaution[] }) {
  return (
    <section className="mt-6 rounded-3xl border border-emerald-900/10 bg-white p-6 shadow-soft">
      <h2 className="font-display text-xl font-extrabold">Precautions & guidance</h2>
      {items.length === 0 ? (
        <p className="mt-2 text-sm text-ink-soft">Nothing specific was found in the available data. Always check the physical label if you have allergies or dietary restrictions.</p>
      ) : (
        <ul className="mt-3 space-y-3">
          {items.map((p, i) => (
            <li key={i} className={`flex gap-3 rounded-xl p-3 text-sm ${p.kind === 'allergen' ? 'bg-amber-50 text-amber-950' : 'bg-cream'}`}>
              {p.kind === 'allergen' ? <TriangleAlert className="mt-0.5 h-4 w-4 shrink-0" aria-hidden="true" /> : <Info className="mt-0.5 h-4 w-4 shrink-0 text-emerald-700" aria-hidden="true" />}
              <span>{p.text}<span className="mt-0.5 block text-xs opacity-70">Source: {p.source}</span></span>
            </li>
          ))}
        </ul>
      )}
      <p className="mt-3 text-xs text-ink-soft">General information, not medical advice.</p>
    </section>
  )
}


/** Minimal typing for the browser BarcodeDetector API (Chrome/Edge/Android); not in the TypeScript DOM library. */
type DetectedCode = { rawValue: string; format: string }
type BarcodeDetectorLike = { detect: (src: CanvasImageSource | Blob | ImageBitmap) => Promise<DetectedCode[]> }
type BarcodeDetectorCtor = new (opts?: { formats?: string[] }) => BarcodeDetectorLike
const RETAIL_FORMATS = ['ean_13', 'ean_8', 'upc_a', 'upc_e', 'itf']

function getDetector(): BarcodeDetectorLike | null {
  const Ctor = (window as unknown as { BarcodeDetector?: BarcodeDetectorCtor }).BarcodeDetector
  if (!Ctor) return null
  try { return new Ctor({ formats: RETAIL_FORMATS }) } catch { return null }
}

const BARCODE_HINTS: Record<string, string> = {
  INVALID_BARCODE: 'Check the digits printed under the bars (8, 12, 13 or 14 digits, including any leading zeros).',
  PRODUCT_NOT_FOUND: 'Try photographing the front and back of the package above, or search by product name below.',
  LOOKUP_TIMEOUT: 'The database was slow to answer. Try again in a moment.',
  LOOKUP_RATE_LIMITED: 'Too many lookups in a short time. Wait a minute and try again.',
  LOOKUP_UNAVAILABLE: 'The database could not be reached. Check the internet connection of the server, or use the photo analysis above.',
  LOOKUP_BAD_RESPONSE: 'The database sent an unreadable answer. Try again, or use the photo analysis above.',
  LOOKUP_DISABLED: 'Barcode lookups are turned off on this server. Use the photo analysis or the name search instead.',
}

function BarcodeLookup({ active, disabled, hit, onFound }: {
  active: boolean; disabled: boolean; hit: BarcodeSuccess | null; onFound: (b: BarcodeSuccess) => void
}) {
  const [code, setCode] = useState('')
  const [busy, setBusy] = useState(false)
  const [err, setErr] = useState<ApiError | null>(null)
  const [scanning, setScanning] = useState(false)
  const [scanMsg, setScanMsg] = useState<string | null>(null)
  const [supported] = useState(() => typeof window !== 'undefined' && getDetector() !== null)
  const videoRef = useRef<HTMLVideoElement | null>(null)
  const streamRef = useRef<MediaStream | null>(null)
  const ctrl = useRef<AbortController | null>(null)

  const stopCamera = () => {
    streamRef.current?.getTracks().forEach((t) => t.stop())
    streamRef.current = null
    setScanning(false)
  }
  useEffect(() => () => { stopCamera(); ctrl.current?.abort() }, [])
  useEffect(() => { if (!active) stopCamera() }, [active])

  const lookup = async (raw: string) => {
    const c = raw.replace(/[\s-]/g, '') // keep leading zeros: the code is sent as a string
    if (!/^\d+$/.test(c) || ![8, 12, 13, 14].includes(c.length)) {
      setErr({ code: 'INVALID_BARCODE', message: 'A retail barcode has 8, 12, 13 or 14 digits.' })
      return
    }
    ctrl.current?.abort()
    const ac = new AbortController()
    ctrl.current = ac
    setBusy(true); setErr(null)
    const r = await lookupBarcode(c, ac.signal, newRequestKey())
    if (ac.signal.aborted) return
    setBusy(false)
    if (r.ok) onFound(r.data)
    else setErr(r.error)
  }

  const submit = (e: FormEvent) => { e.preventDefault(); void lookup(code) }

  const startCamera = async () => {
    const detector = getDetector()
    if (!detector) return
    setScanMsg(null); setErr(null)
    try {
      const stream = await navigator.mediaDevices.getUserMedia({ video: { facingMode: 'environment' }, audio: false })
      streamRef.current = stream
      setScanning(true)
      requestAnimationFrame(async () => {
        const v = videoRef.current
        if (!v) return stopCamera()
        v.srcObject = stream
        await v.play().catch(() => undefined)
        const started = Date.now()
        const tick = async () => {
          if (!streamRef.current) return
          try {
            const found = v.readyState >= 2 ? await detector.detect(v) : []
            const digits = found.map((f) => f.rawValue.replace(/\D/g, '')).find((d) => [8, 12, 13, 14].includes(d.length))
            if (digits) { stopCamera(); setCode(digits); void lookup(digits); return }
          } catch { /* keep trying until the timeout */ }
          if (Date.now() - started > 30000) { stopCamera(); setScanMsg('No barcode was detected. Type the digits instead.'); return }
          setTimeout(() => void tick(), 250)
        }
        void tick()
      })
    } catch {
      stopCamera()
      setScanMsg('The camera could not be opened (permission denied or no camera). Type the digits instead.')
    }
  }

  const fromPhoto = async (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    const detector = getDetector()
    if (!f || !detector) return
    setScanMsg(null); setErr(null)
    try {
      const bmp = await createImageBitmap(f)
      const found = await detector.detect(bmp)
      const digits = found.map((x) => x.rawValue.replace(/\D/g, '')).find((d) => [8, 12, 13, 14].includes(d.length))
      if (digits) { setCode(digits); void lookup(digits) }
      else setScanMsg('No barcode was found in that photo. Try a closer, sharper photo or type the digits.')
    } catch {
      setScanMsg('That photo could not be read. Type the digits instead.')
    }
  }

  const p = hit?.product
  return (
    <div>
      <h2 className="flex items-center gap-2 font-display text-xl font-extrabold">
        <ScanBarcode className="h-5 w-5 text-emerald-700" aria-hidden="true" /> Look up a barcode
      </h2>
      <p className="mt-1 text-sm text-ink-soft">Searches Open Food Facts, a crowd-sourced database. Results are labelled as external data.</p>
      <form onSubmit={submit} className="mt-3 flex flex-wrap gap-2">
        <label htmlFor="pk-barcode" className="sr-only">Barcode digits</label>
        <input id="pk-barcode" inputMode="numeric" autoComplete="off" value={code} onChange={(e) => setCode(e.target.value)} placeholder="e.g. 8901234567890"
          className="min-w-0 flex-1 rounded-xl border border-emerald-900/15 px-4 py-3 tabular-nums outline-none focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/15" />
        <button type="submit" disabled={busy || disabled || !code.trim()} className="rounded-full bg-emerald-700 px-5 py-3 font-semibold text-white hover:bg-emerald-800 disabled:opacity-50">
          {busy ? 'Looking up…' : 'Look up'}
        </button>
      </form>
      <div className="mt-2 flex flex-wrap items-center gap-2 text-sm">
        {supported ? (
          <>
            <button type="button" onClick={scanning ? stopCamera : () => void startCamera()} disabled={busy || disabled}
              className="inline-flex items-center gap-1.5 rounded-full border border-emerald-900/15 px-3 py-1.5 font-semibold hover:bg-emerald-50 disabled:opacity-50">
              <Camera className="h-4 w-4" aria-hidden="true" /> {scanning ? 'Stop camera' : 'Scan with camera'}
            </button>
            <label className="inline-flex cursor-pointer items-center gap-1.5 rounded-full border border-emerald-900/15 px-3 py-1.5 font-semibold hover:bg-emerald-50">
              <ImagePlus className="h-4 w-4" aria-hidden="true" /> Read from a photo
              <input type="file" accept="image/*" className="sr-only" onChange={(e) => void fromPhoto(e)} disabled={busy || disabled} />
            </label>
          </>
        ) : (
          <span className="text-xs text-ink-soft">Camera scanning is not supported in this browser; type the digits printed under the bars.</span>
        )}
      </div>
      {scanning && (
        <div className="relative mt-3 overflow-hidden rounded-2xl bg-black">
          <video ref={videoRef} muted playsInline className="aspect-video w-full object-cover" />
          <div className="pointer-events-none absolute inset-x-8 top-1/2 h-0.5 -translate-y-1/2 bg-red-500/80" aria-hidden="true" />
          <p className="absolute inset-x-0 bottom-0 bg-black/50 px-3 py-1.5 text-center text-xs text-white" role="status">Point the camera at the barcode…</p>
        </div>
      )}
      {scanMsg && <p className="mt-2 text-sm text-amber-800" role="status">{scanMsg}</p>}
      {err && (
        <div role="alert" className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
          <p className="font-semibold">{err.message}</p>
          {BARCODE_HINTS[err.code] && <p className="mt-1 text-red-700/90">{BARCODE_HINTS[err.code]}</p>}
          {['LOOKUP_TIMEOUT', 'LOOKUP_UNAVAILABLE', 'LOOKUP_BAD_RESPONSE', 'LOOKUP_RATE_LIMITED', 'BACKEND_UNAVAILABLE'].includes(err.code) && (
            <button type="button" onClick={() => void lookup(code)} disabled={busy}
              className="mt-2 inline-flex items-center gap-1 rounded-full bg-white px-3 py-1 text-xs font-semibold ring-1 ring-red-200 hover:bg-red-100 disabled:opacity-50">
              <RefreshCw className="h-3.5 w-3.5" aria-hidden="true" /> Try again
            </button>
          )}
        </div>
      )}
      {hit && p && (
        <div className="mt-4">
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <Badge tone="blue">Barcode {hit.barcode}{hit.format ? ` · ${hit.format}` : ''}</Badge>
            <span className="text-ink-soft">{[p.brand, p.name].filter(Boolean).join(' · ')}</span>
          </div>
          <ExternalCard ext={hit} />
          <AllergenAlertsCard alerts={hit.allergen_alerts} />
          <div className="mt-5">
            <SaveActions analysisId={hit.analysis_id} kind="packaged" canLog={false} history={hit.history} />
          </div>
        </div>
      )}
    </div>
  )
}
