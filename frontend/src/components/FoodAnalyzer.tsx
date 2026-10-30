import { useEffect, useRef, useState } from 'react'
import type { ChangeEvent } from 'react'
import { Link } from 'react-router-dom'
import { Camera, CircleAlert, ImagePlus, RefreshCw, Sparkles, X } from 'lucide-react'
import { analyzeFood, confirmFood, getSupportedFoods, newRequestKey } from '../lib/foodApi'
import type { AnalyzeResult, ConfirmFoodResult, GenericReference, HistoryStatus, Nutrition, NutritionChoice, OpenAIVisionInfo, RecognitionInfo, SafetyAlert } from '../lib/foodApi'
import { confirmationRequired, formatConfidencePercent, identificationSourceText, isValidRecognitionScore, photoRefFor } from '../lib/recognitionConfidence'
import type { AnalysisContext } from '../lib/chatApi'
import CameraCapture from './CameraCapture'
import DropZone from './DropZone'
import { ChemicalPanel, FreshnessCard, Precautions, QualityNote, SafetyAlertBanner, SaveActions, VisionNote } from './AnalysisExtras'
import { useAuth } from './AuthProvider'
import { api } from '../lib/api'
import { Badge } from './ui'
import NutritionExplained from './NutritionExplained'

const MAX_MB = 8
const fmt = (v: number | null) => (v === null ? 'Not available' : String(Math.round(v * 100) / 100))

function RecognitionNote({ recognition, openai }: { recognition?: RecognitionInfo; openai?: OpenAIVisionInfo }) {
  if (!recognition && !openai) return null
  // Deliberately not used (switched off, no key, or sign-in required): the recognition message already explains it.
  const providerNote = openai?.status === 'unavailable' && !['disabled', 'not_configured', 'login_required'].includes(openai.reason ?? '')
    ? ` OpenAI was unavailable (${openai.reason?.replaceAll('_', ' ') ?? 'unknown reason'}).`
    : ''
  const foodNote = openai?.food_name
    ? ` OpenAI's visual identification: ${openai.food_name}${openai.supported_food ? ' (one of the 24 model foods)' : ' (not one of the 24 model foods)'}.`
    : ''
  return (
    <details className="group mt-3 rounded-xl bg-cream px-3 py-2 text-sm text-ink-soft">
      <summary className="cursor-pointer select-none font-semibold text-ink marker:text-emerald-700">How this was identified</summary>
      <p className="mt-1.5">{recognition?.message ?? 'OpenAI recognition was not available.'}{providerNote}{foodNote}</p>
      {openai?.visible_evidence && openai.visible_evidence.length > 0 && (
        <p className="mt-1 text-xs">Visible evidence: {openai.visible_evidence.join('; ')}</p>
      )}
      {openai?.uncertainty && <p className="mt-1 text-xs">Uncertainty noted: {openai.uncertainty}</p>}
    </details>
  )
}

function NutritionCard({ nutrition, error, spoiled = false, produce = false }: { nutrition: Nutrition | null; error: string | null; spoiled?: boolean
  /** Whole fruit or vegetable (its sugars are naturally occurring). */ produce?: boolean }) {
  if (!nutrition) {
    return (
      <div className="rounded-2xl border border-emerald-900/10 p-4">
        <h3 className="font-semibold">Nutrition</h3>
        <p className="mt-1 flex gap-2 text-sm text-ink-soft"><CircleAlert className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" aria-hidden="true" />
          {error ?? 'No verified nutrition data is available for this food.'}</p>
      </div>
    )
  }
  const perServing = nutrition.serving_grams !== null
  return (
    <div className="rounded-2xl border border-emerald-900/10 p-4">
      <div className="flex flex-wrap items-baseline justify-between gap-2">
        <h3 className="font-semibold">Nutrition</h3>
        <span className="text-xs text-ink-soft">{perServing ? `per 100 g and per ${nutrition.serving_grams} g` : 'per 100 g'}</span>
      </div>
      {spoiled && (
        <p className="mt-2 rounded-xl bg-red-50 p-2.5 text-xs font-semibold text-red-900">
          Reference values for the fresh food, shown for information only. They do not apply to spoiled food, which should not be eaten.
        </p>
      )}
      <div className="mt-3">
        <NutritionExplained input={{
          nutrients: nutrition.nutrients.map((n) => ({ key: n.key, label: n.label, unit: n.unit, per100: n.per_100g, perServing: n.per_serving })),
          servingGrams: nutrition.serving_grams, basis: 'per100g', naturalSugars: produce }} />
      </div>
      <details open className="group mt-4">
        <summary className="cursor-pointer text-sm font-semibold text-emerald-800 hover:underline">All nutrient values ({nutrition.nutrients.length})</summary>
      <div className="mt-2 max-w-full overflow-x-auto">
        <table className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-emerald-900/10 text-xs uppercase tracking-wide text-ink-soft">
              <th scope="col" className="py-1.5 pr-3 font-semibold">Nutrient</th>
              <th scope="col" className="py-1.5 pr-3 text-right font-semibold">Per 100 g</th>
              {perServing && <th scope="col" className="py-1.5 text-right font-semibold">Per {nutrition.serving_grams} g</th>}
            </tr>
          </thead>
          <tbody>
            {nutrition.nutrients.map((n) => (
              <tr key={n.key} className="border-b border-emerald-900/5 last:border-0">
                <td className="py-1.5 pr-3">{n.label}</td>
                <td className={`py-1.5 pr-3 text-right tabular-nums ${n.per_100g === null ? 'text-ink-soft' : ''}`}>
                  {n.per_100g === null ? 'Not available' : `${fmt(n.per_100g)} ${n.unit}`}</td>
                {perServing && <td className={`py-1.5 text-right tabular-nums ${n.per_serving === null ? 'text-ink-soft' : ''}`}>
                  {n.per_serving === null ? 'Not available' : `${fmt(n.per_serving)} ${n.unit}`}</td>}
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      </details>
      {nutrition.generic_category_reference && (
        <p className="mt-2 rounded-xl bg-amber-50 p-2.5 text-xs font-semibold text-amber-900">Generic reference: the specific type of this food was not determined.</p>
      )}
      <p className="mt-2 break-words text-xs text-ink-soft">Source: {nutrition.basis}.{' '}
        {nutrition.source_url && <a href={nutrition.source_url} target="_blank" rel="noreferrer" className="font-semibold text-emerald-700 hover:underline">View the USDA record</a>}
        {' '}{nutrition.note} {nutrition.serving_note}</p>
    </div>
  )
}


/** A category food (e.g. Sandwich): the specific type decides the nutrition, so the user chooses it, or explicitly accepts
 *  the generic record, which is described exactly. Also shown when a specific dish has no record of its own. */
function SpecificTypeChooser({ choice, alternative, busy, onPick, onGeneric }: {
  choice: NutritionChoice | null | undefined; alternative: GenericReference | null | undefined; busy: boolean
  onPick: (name: string) => void; onGeneric: (category: string) => void
}) {
  const [other, setOther] = useState('')
  const generic = choice?.generic_reference ?? alternative ?? null
  const category = choice?.category ?? alternative?.food ?? ''
  if (!choice && !alternative) return null
  const btn = 'rounded-full border border-emerald-900/15 bg-white px-3.5 py-2 text-sm font-semibold hover:bg-emerald-50 disabled:opacity-60'
  return (
    <section className="rounded-2xl border border-amber-900/15 bg-amber-50/60 p-4" aria-labelledby="specific-type-h">
      {choice ? (
        <>
          <h3 id="specific-type-h" className="font-semibold">Which {category.toLowerCase()} is it?</h3>
          <dl className="mt-2 grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 text-sm">
            <dt className="text-ink-soft">Predicted category</dt><dd className="font-semibold">{category}</dd>
            <dt className="text-ink-soft">Specific type</dt><dd>Not determined</dd>
          </dl>
          <p className="mt-2 text-xs text-ink-soft">{choice.message}</p>
          <div className="mt-3 flex flex-wrap gap-2">
            {choice.options.map((o) => (
              <button key={o} type="button" disabled={busy} onClick={() => onPick(o)} className={btn}>
                {o}{o === choice.suggested ? ' (suggested)' : ''}
              </button>
            ))}
          </div>
          <form className="mt-3 flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); if (other.trim()) onPick(other.trim()) }}>
            <label htmlFor="other-type" className="sr-only">Other type of {category.toLowerCase()}</label>
            <input id="other-type" value={other} onChange={(e) => setOther(e.target.value)} maxLength={120}
              placeholder={`Other ${category.toLowerCase()}, e.g. "grilled cheese sandwich"`}
              className="min-w-0 flex-1 rounded-xl border border-emerald-900/15 bg-white px-3 py-2 text-sm outline-none focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/15" />
            <button type="submit" disabled={busy || !other.trim()} className={btn}>Use this name</button>
          </form>
        </>
      ) : (
        <h3 id="specific-type-h" className="font-semibold">No nutrition record for this exact food</h3>
      )}
      {generic && (
        <div className="mt-3 rounded-xl bg-white p-3 text-xs text-ink-soft">
          <p>
            <span className="font-semibold text-ink">Generic {category.toLowerCase()} reference</span>
            {generic.description ? <> (USDA FoodData Central{generic.fdc_id ? ` ${generic.fdc_id}` : ''}: {generic.description})</> : null}.
            {' '}{generic.caveat} It is not specific to your food.
          </p>
          <button type="button" disabled={busy} onClick={() => onGeneric(category)} className={`mt-2 ${btn}`}>
            Use the generic {category.toLowerCase()} reference
          </button>
        </div>
      )}
    </section>
  )
}

type Props = { embedded?: boolean; active?: boolean; onContextChange?: (ctx: AnalysisContext | null) => void }

export default function FoodAnalyzer({ embedded = false, active = true, onContextChange }: Props = {}) {
  const { user } = useAuth()
  const [cameraOpen, setCameraOpen] = useState(false)
  useEffect(() => { if (!active) setCameraOpen(false) }, [active])
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<string | null>(null)
  const [requestKey, setRequestKey] = useState<string>(() => newRequestKey())
  const [serving, setServing] = useState('')
  const [loading, setLoading] = useState(false)
  const [result, setResult] = useState<AnalyzeResult | null>(null)
  const [confirmation, setConfirmation] = useState<ConfirmFoodResult | null>(null)
  const [selectedCandidate, setSelectedCandidate] = useState<string | null>(null)
  const [confirmLoading, setConfirmLoading] = useState(false)
  const [localError, setLocalError] = useState<string | null>(null)
  const [pickerOpen, setPickerOpen] = useState(false)
  const [notListed, setNotListed] = useState(false)
  const [scoreConfirmed, setScoreConfirmed] = useState(false)
  const abortRef = useRef<AbortController | null>(null)
  const resultRef = useRef<HTMLDivElement | null>(null)

  const clearOutcome = () => {
    setResult(null)
    setConfirmation(null)
    setSelectedCandidate(null)
    setLocalError(null)
    setPickerOpen(false)
    setNotListed(false)
    setScoreConfirmed(false)
  }

  const reset = () => {
    abortRef.current?.abort()
    if (preview) URL.revokeObjectURL(preview)
    setFile(null)
    setPreview(null)
    clearOutcome()
    setServing('')
    setLoading(false)
    setConfirmLoading(false)
  }

  const retake = () => {
    reset()
    setCameraOpen(true)
  }

  const onPick = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0]
    e.target.value = ''
    if (f) acceptFile(f)
  }

  const acceptFile = (f: File) => {
    setCameraOpen(false)
    abortRef.current?.abort()
    setLoading(false)
    setConfirmLoading(false)
    clearOutcome()
    if (!f.type.startsWith('image/')) return setLocalError('Please choose an image file (JPG, PNG or WebP).')
    if (f.size > MAX_MB * 1024 * 1024) return setLocalError(`The image is larger than ${MAX_MB} MB. Please upload a smaller photo.`)
    if (preview) URL.revokeObjectURL(preview)
    setFile(f)
    setPreview(URL.createObjectURL(f))
    setRequestKey(newRequestKey()) // one key per photo: analysing the same photo again cannot create a duplicate history entry
  }

  const grams = (): number | undefined | null => {
    if (serving.trim() === '') return undefined
    const g = Number(serving)
    return Number.isFinite(g) && g >= 1 && g <= 2000 ? g : null
  }

  const analyse = async () => {
    if (!file) return
    const g = grams()
    if (g === null) return setLocalError('Serving size must be between 1 and 2000 grams.')
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setLoading(true)
    clearOutcome()
    try {
      setResult(await analyzeFood(file, g, ctrl.signal, `${requestKey}-${g ?? 'na'}`))
    } catch {
      /* request was cancelled */
    } finally {
      if (abortRef.current === ctrl) setLoading(false)
    }
  }

  const confirmName = async (name: string, pendingId?: string, acceptGeneric = false) => {
    // Choosing the specific type of a recognised category (e.g. "Paneer sandwich" for "Sandwich") is not a correction.
    if (user && result?.ok && result.data.prediction.food !== name && !result.data.nutrition_choice) {
      void api('/api/corrections', { method: 'POST', body: { predicted: result.data.prediction.food, corrected: name } })
    }
    const g = grams()
    if (g === null) return setLocalError('Serving size must be between 1 and 2000 grams.')
    abortRef.current?.abort()
    const ctrl = new AbortController()
    abortRef.current = ctrl
    setConfirmLoading(true)
    setConfirmation(null)
    setScoreConfirmed(false)
    setLocalError(null)
    try {
      // Always tie the choice to THIS analysis's photo, so the server assesses freshness on that photo for the chosen food
      // (previously only the general-food suggestion sent it, and every other choice came back "not assessed").
      const response = await confirmFood(name, g, ctrl.signal, pendingId ?? photoRefFor(result), acceptGeneric)
      setConfirmation(response)
      if (response.ok) {
        setResult(null)
        setPickerOpen(false)
      }
    } catch {
      /* request was cancelled */
    } finally {
      if (abortRef.current === ctrl) setConfirmLoading(false)
    }
  }

  const lowConfidence = result && !result.ok && result.error.code === 'LOW_CONFIDENCE' ? result.error : null
  const general = lowConfidence?.general_candidate ?? null
  const success = confirmation?.ok
    ? {
        kind: 'confirmed' as const,
        food: confirmation.data.confirmation.food,
        confidence: null as number | null,
        identification: confirmation.data.identification,
        nutrition: confirmation.data.nutrition,
        nutritionError: confirmation.data.nutrition_error,
        nutritionChoice: confirmation.data.nutrition_choice,
        genericAlternative: confirmation.data.generic_alternative,
        imageRef: confirmation.data.image_ref ?? undefined,
        notes: confirmation.data.notes,
        warnings: [] as string[],
        analysisId: confirmation.data.analysis_id,
        history: confirmation.data.history as HistoryStatus | undefined,
        freshness: confirmation.data.freshness,
        precautions: confirmation.data.precautions,
        safetyAlert: confirmation.data.safety_alert as SafetyAlert | null | undefined,
        suggestPackaged: false,
        vision: null,
        recognition: confirmation.data.recognition,
        openaiVision: undefined as OpenAIVisionInfo | undefined,
      }
    : result?.ok
      ? {
          kind: 'recognized' as const,
          food: result.data.prediction.food,
          confidence: result.data.prediction.confidence,
          identification: result.data.identification,
          nutrition: result.data.nutrition,
          nutritionError: result.data.nutrition_error,
          nutritionChoice: result.data.nutrition_choice,
          genericAlternative: result.data.generic_alternative,
          imageRef: result.data.image_ref ?? undefined,
          notes: result.data.notes,
          warnings: result.data.warnings,
          analysisId: result.data.analysis_id,
          history: result.data.history,
          freshness: result.data.freshness,
          precautions: result.data.precautions,
          safetyAlert: result.data.safety_alert,
          suggestPackaged: result.data.suggest_packaged_scan === true,
          vision: result.data.vision,
          recognition: result.data.recognition,
          openaiVision: result.data.openai_vision,
        }
      : null
  // The server decides (confidence >= 70% or independent verification -> no question); the same rule is the fallback here.
  const awaitingConfirmation = Boolean(result?.ok && !confirmation?.ok && !scoreConfirmed && confirmationRequired(result.data))
  const spoiled = success?.freshness?.status === 'possibly_spoiled'
  const scoreCandidates = result?.ok && result.data.prediction.top_k.length > 0
    ? result.data.prediction.top_k
    : result?.ok
      ? [{ class_id: result.data.prediction.class_id ?? -1, food: result.data.prediction.food, score: Number.NaN }]
      : []
  const supportedClass = success?.identification ? success.identification.supported_class : success?.food ?? null
  const category = success?.identification?.category

  useEffect(() => {
    if ((result || confirmation) && resultRef.current) resultRef.current.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }, [result, confirmation])

  useEffect(() => {
    if (!onContextChange) return
    if (!success || awaitingConfirmation) return onContextChange(null)
    if (notListed && success.kind === 'recognized') {
      return onContextChange({
        kind: 'fresh', title: 'Unidentified food',
        status: `the model guessed ${success.food}, but the user says this is wrong and their food is not one of the supported foods; no nutrition data applies`,
      })
    }
    const ident = success.identification
    onContextChange({
      kind: 'fresh',
      title: success.food,
      category: category ?? null,
      status: `${scoreConfirmed ? 'Confirmed by you. ' : ''}${ident ? identificationSourceText(ident) : success.kind === 'confirmed' ? 'User-selected food' : 'Recognised by the image model'}${isValidRecognitionScore(success.confidence) ? ` (image-model score ${formatConfidencePercent(success.confidence)}, not a probability)` : ''}${ident?.specificity === 'category' ? `. Only the category (${success.food}) was recognised; the specific type was not determined` : ''}`,
      checked_by: ident?.verified_by ?? null,
      // The freshness model's result as shown on screen, with its stated limitation (it gives a fresh/rotten label only).
      freshness: success.freshness ? {
        status: success.freshness.status, label: success.freshness.condition_label ?? null, message: success.freshness.message,
        model_score: success.freshness.confidence, limitation: success.freshness.limitation ?? null,
      } : null,
      nutrition: success.nutrition
        ? {
            source: success.nutrition.basis,
            is_estimate: success.nutrition.is_estimate,
            serving_grams: success.nutrition.serving_grams,
            values: success.nutrition.nutrients.map((n) => ({ nutrient: n.label, unit: n.unit, per_100g: n.per_100g, per_serving: n.per_serving })),
            not_available: success.nutrition.not_available,
            note: success.nutrition.note,
          }
        : { error: success.nutritionError ?? 'No nutrition data available.' },
    })
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [result, confirmation, notListed, awaitingConfirmation, scoreConfirmed])

  const Wrapper = embedded ? 'div' : 'main'
  const hasOutcome = Boolean(result || confirmation?.ok)
  return (
    <Wrapper className={embedded ? 'text-ink' : 'min-h-screen bg-cream px-4 py-10 text-ink'}>
      <div className={embedded ? '' : 'mx-auto max-w-4xl'}>
        {!embedded && (
          <>
            <h1 className="font-display text-3xl font-extrabold tracking-tight">Analyse your food</h1>
            <p className="mt-2 text-ink-soft">Upload a clear photo of one food item.</p>
          </>
        )}

        <section className={`${embedded ? '' : 'mt-8 '}rounded-3xl border border-emerald-900/10 bg-white p-4 shadow-soft sm:p-6`} aria-label="Food photo">
          {!preview && cameraOpen ? (
            <CameraCapture onCapture={acceptFile} onClose={() => setCameraOpen(false)} label="Capture food" />
          ) : !preview ? (
            <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
              <DropZone
                title="Choose a food photo"
                hint={`One food per photo works best. JPG, PNG or WebP, up to ${MAX_MB} MB`}
                inputLabel="Choose a food photo"
                onFile={acceptFile}
              />
              <button type="button" onClick={() => { setLocalError(null); setCameraOpen(true) }}
                className="inline-flex items-center justify-center gap-2 rounded-2xl border border-emerald-900/15 px-6 py-4 font-semibold hover:bg-emerald-50 sm:flex-col sm:justify-center sm:px-8">
                <Camera className="h-6 w-6 text-emerald-700" aria-hidden="true" /> Use camera
              </button>
            </div>
          ) : (
            <div className={`grid items-start gap-4 ${hasOutcome ? 'grid-cols-[6rem_minmax(0,1fr)] sm:grid-cols-[8rem_minmax(0,1fr)]' : 'sm:grid-cols-[14rem_minmax(0,1fr)]'}`}>
              <div className="relative">
                <img src={preview} alt="Your food photo" className="aspect-square w-full rounded-2xl bg-cream object-cover" />
                <button type="button" onClick={reset} aria-label="Remove photo"
                  className="absolute right-1.5 top-1.5 grid h-8 w-8 place-items-center rounded-full bg-white/90 text-ink shadow hover:bg-white">
                  <X className="h-4 w-4" />
                </button>
              </div>
              <div className="flex min-w-0 flex-col gap-3">
                <div>
                  <label htmlFor="serving" className="mb-1 block text-sm font-semibold">Serving size in grams (optional)</label>
                  <input id="serving" inputMode="decimal" value={serving} onChange={(e) => setServing(e.target.value)} placeholder="e.g. 150"
                    className="w-full max-w-xs rounded-xl border border-emerald-900/15 px-4 py-2.5 outline-none focus:border-emerald-600 focus:ring-4 focus:ring-emerald-600/15" />
                  <p className="mt-1 text-xs text-ink-soft">Enter it yourself. A photo cannot measure portion weight.</p>
                </div>
                <div className="flex flex-wrap gap-2">
                  <button type="button" onClick={analyse} disabled={loading || confirmLoading}
                    className="inline-flex items-center gap-2 rounded-full bg-emerald-600 px-6 py-2.5 font-semibold text-white shadow-sm hover:bg-emerald-700 disabled:opacity-60">
                    <Sparkles className="h-4 w-4" aria-hidden="true" /> {loading ? 'Analysing…' : hasOutcome ? 'Analyse again' : 'Analyse'}
                  </button>
                  <label className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-emerald-900/15 px-5 py-2.5 font-semibold hover:bg-emerald-50 focus-within:ring-4 focus-within:ring-emerald-600/20">
                    <ImagePlus className="h-4 w-4" aria-hidden="true" /> Replace photo
                    <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" onChange={onPick} />
                  </label>
                </div>
              </div>
            </div>
          )}
          {(loading || confirmLoading) && (
            <div role="status" className="mt-4 flex items-center gap-3 rounded-xl bg-emerald-50/60 px-4 py-3 text-sm text-ink-soft">
              <div className="h-5 w-5 animate-spin rounded-full border-2 border-emerald-600 border-t-transparent" />
              {loading ? 'Analysing your photo with the image model and the configured vision services…' : 'Loading nutrition for your selection…'}
            </div>
          )}
        </section>

        <div ref={resultRef} aria-live="polite" className="scroll-mt-24">
          {localError && <p role="alert" className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-4 font-semibold text-red-800">{localError}</p>}
          <QualityNote
            q={confirmation?.ok ? confirmation.data.image_quality : result?.ok ? result.data.image_quality : result?.error.image_quality}
            enhancement={confirmation?.ok ? confirmation.data.enhancement : result?.ok ? result.data.enhancement : result?.error.enhancement}
            onRetake={retake}
          />

          {result && !result.ok && result.error.code === 'NON_FOOD_IMAGE' && (
            <div role="alert" className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-950">
              <p className="font-display text-lg font-bold">No food found in this photo</p>
              <p className="mt-1">{result.error.message}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <label className="inline-flex cursor-pointer items-center gap-2 rounded-full bg-emerald-600 px-5 py-2.5 font-semibold text-white shadow-sm hover:bg-emerald-700 focus-within:ring-4 focus-within:ring-emerald-600/20">
                  <ImagePlus className="h-4 w-4" aria-hidden="true" /> Upload another photo
                  <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" onChange={onPick} />
                </label>
                <button type="button" onClick={retake}
                  className="inline-flex items-center gap-2 rounded-full border border-emerald-900/15 bg-white px-5 py-2.5 font-semibold text-ink hover:bg-emerald-50">
                  <Camera className="h-4 w-4 text-emerald-700" aria-hidden="true" /> Take a photo
                </button>
              </div>
            </div>
          )}

          {result && !result.ok && result.error.code === 'PACKAGED_PRODUCT' && (
            <div role="alert" className="mt-5 rounded-2xl border border-amber-200 bg-amber-50 p-5 text-amber-950">
              <p className="font-display text-lg font-bold">This looks like a packaged product</p>
              <p className="mt-1">{result.error.message}</p>
              <div className="mt-4 flex flex-wrap gap-2">
                <Link to="/scan-packaged" className="inline-flex items-center gap-2 rounded-full bg-emerald-600 px-5 py-2.5 font-semibold text-white shadow-sm hover:bg-emerald-700">
                  Scan packaged food
                </Link>
                <label className="inline-flex cursor-pointer items-center gap-2 rounded-full border border-emerald-900/15 bg-white px-5 py-2.5 font-semibold text-ink hover:bg-emerald-50 focus-within:ring-4 focus-within:ring-emerald-600/20">
                  <ImagePlus className="h-4 w-4" aria-hidden="true" /> Upload another photo
                  <input type="file" accept="image/jpeg,image/png,image/webp" className="sr-only" onChange={onPick} />
                </label>
              </div>
            </div>
          )}

          {result && !result.ok && result.error.code !== 'NON_FOOD_IMAGE' && result.error.code !== 'PACKAGED_PRODUCT' && !(result.error.code === 'LOW_CONFIDENCE' && (result.error.candidates?.length || general)) && (
            <div role="alert" className="mt-5 rounded-2xl border border-red-200 bg-red-50 p-5 text-red-800">
              <p className="font-semibold">{result.error.message}</p>
              <p className="mt-1 text-xs opacity-80">Code: {result.error.code}</p>
              {result.error.code === 'UNSUPPORTED_FOOD' && <VisionNote v={result.error.vision} />}
              <RecognitionNote recognition={result.error.recognition} openai={result.error.openai_vision} />
              {(result.error.code === 'UNSUPPORTED_FOOD' || result.error.code === 'LOW_CONFIDENCE') && (
                <ManualPicker open={pickerOpen} setOpen={setPickerOpen} busy={confirmLoading} onConfirm={(f) => void confirmName(f)}
                  prompt="If your food is one of the supported foods, choose it:" />
              )}
              {confirmation && !confirmation.ok && (
                <p role="alert" className="mt-3 rounded-xl border border-red-200 bg-white p-3 text-sm text-red-800">
                  {confirmation.error.message} <span className="text-xs">({confirmation.error.code})</span>
                </p>
              )}
            </div>
          )}

          {awaitingConfirmation && result?.ok && (
            <section className="mt-5 rounded-3xl border border-amber-900/15 bg-white p-5 shadow-soft sm:p-6" aria-labelledby="score-confirmation-heading">
              <p className="text-xs font-semibold uppercase tracking-wider text-amber-700">Please confirm</p>
              <h2 id="score-confirmation-heading" className="mt-1 font-display text-2xl font-extrabold">Which food is this?</h2>
              <p className="mt-2 text-sm text-ink-soft">
                {isValidRecognitionScore(result.data.prediction.confidence)
                  ? `The image-model score is ${formatConfidencePercent(result.data.prediction.confidence)}. Scores below 70% need your confirmation when no other service verified the food. This score is not a calibrated probability.`
                  : 'No valid image-model score is available for this result, so please confirm the food before viewing nutrition.'}
              </p>
              {result.data.prediction.class_id === null && (
                <p className="mt-3 rounded-xl bg-emerald-50 p-3 text-sm text-emerald-900">
                  Suggested by {result.data.identification?.source === 'openai' ? (result.data.identification.provider ?? 'OpenAI Vision') : 'the vision service'}: {result.data.prediction.food}. This food is outside the image model’s supported classes.
                </p>
              )}
              <fieldset className="mt-4 grid gap-2 sm:grid-cols-2" disabled={confirmLoading}>
                <legend className="sr-only">Choose the food to confirm</legend>
                {scoreCandidates.map((candidate) => (
                  <label key={candidate.class_id} className="flex cursor-pointer items-center gap-3 rounded-xl border border-emerald-900/10 px-4 py-2.5 hover:bg-emerald-50 has-[:checked]:border-emerald-600 has-[:checked]:bg-emerald-50">
                    <input type="radio" name="recognized-food-confirmation" value={candidate.food}
                      checked={selectedCandidate === candidate.food} onChange={() => setSelectedCandidate(candidate.food)}
                      className="accent-emerald-700" />
                    <span className="min-w-0 flex-1 truncate font-semibold">{candidate.food}</span>
                    <span className="text-xs tabular-nums text-ink-soft" title="Image-model score, not a probability">
                      {isValidRecognitionScore(candidate.score) ? formatConfidencePercent(candidate.score) : 'Score unavailable'}
                    </span>
                  </label>
                ))}
              </fieldset>
              <button
                type="button"
                onClick={() => {
                  const recognizedFood = result.data.prediction.food
                  if (selectedCandidate === recognizedFood && result.data.prediction.class_id !== null) {
                    setScoreConfirmed(true)
                    setSelectedCandidate(null)
                  } else if (selectedCandidate) {
                    void confirmName(selectedCandidate)
                  }
                }}
                disabled={!selectedCandidate || confirmLoading}
                className="mt-3 rounded-full bg-emerald-700 px-5 py-2 text-sm font-semibold text-white hover:bg-emerald-800 disabled:cursor-not-allowed disabled:opacity-50"
              >
                {confirmLoading ? 'Confirming…' : 'Confirm selected food'}
              </button>
              <ManualPicker open={pickerOpen} setOpen={setPickerOpen} busy={confirmLoading}
                onConfirm={(food) => void confirmName(food)} prompt="None of these? Search or enter a food name:" />
              {confirmation && !confirmation.ok && (
                <p role="alert" className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                  {confirmation.error.message} <span className="text-xs">({confirmation.error.code})</span>
                </p>
              )}
            </section>
          )}

          {lowConfidence && (lowConfidence.candidates?.length || general) && !confirmation?.ok && (
            <section className="mt-5 rounded-3xl border border-amber-900/15 bg-white p-5 shadow-soft sm:p-6" aria-labelledby="candidate-heading">
              <p className="text-xs font-semibold uppercase tracking-wider text-amber-700">Please confirm</p>
              <h2 id="candidate-heading" className="mt-1 font-display text-2xl font-extrabold">Which food is this?</h2>
              <p className="mt-2 text-sm text-ink-soft">{lowConfidence.message}</p>
              <SafetyAlertBanner alert={lowConfidence.safety_alert} />
              <RecognitionNote recognition={lowConfidence.recognition} openai={lowConfidence.openai_vision} />
              <VisionNote v={lowConfidence.vision} />
              {general && (
                <div className="mt-4 rounded-2xl border border-emerald-600/40 bg-emerald-50/60 p-4">
                  <p className="text-xs font-semibold uppercase tracking-wide text-emerald-800">Suggested by {general.source}</p>
                  <p className="mt-0.5 break-words text-lg font-bold">{general.food} <Badge tone="green">{general.category}</Badge></p>
                  <p className="text-xs text-ink-soft">{general.note} Nutrition is shown only if a verified USDA record matches.</p>
                  <button type="button" onClick={() => void confirmName(general.food, lowConfidence.pending_id)} disabled={confirmLoading}
                    className="mt-3 rounded-full bg-emerald-700 px-5 py-2 text-sm font-semibold text-white hover:bg-emerald-800 disabled:opacity-50">
                    Yes, it is {general.food}
                  </button>
                </div>
              )}
              {lowConfidence.candidates && lowConfidence.candidates.length > 0 && (
                <>
                  <p className="mt-4 text-sm font-semibold">{general ? 'Or one of the image model\'s foods:' : 'The image model\'s closest foods:'}</p>
                  <fieldset className="mt-2 grid gap-2 sm:grid-cols-2" disabled={confirmLoading}>
                    <legend className="sr-only">Candidate foods</legend>
                    {lowConfidence.candidates.map((candidate) => (
                      <label key={candidate.class_id} className="flex cursor-pointer items-center gap-3 rounded-xl border border-emerald-900/10 px-4 py-2.5 hover:bg-emerald-50 has-[:checked]:border-emerald-600 has-[:checked]:bg-emerald-50">
                        <input type="radio" name="food-candidate" value={candidate.food} checked={selectedCandidate === candidate.food}
                          onChange={() => setSelectedCandidate(candidate.food)} className="accent-emerald-700" />
                        <span className="min-w-0 flex-1 truncate font-semibold">{candidate.food}</span>
                        <span className="text-xs tabular-nums text-ink-soft" title="Image-model score, not a probability">{formatConfidencePercent(candidate.score) ?? 'Score unavailable'}</span>
                      </label>
                    ))}
                  </fieldset>
                  <button type="button" onClick={() => selectedCandidate && void confirmName(selectedCandidate)} disabled={!selectedCandidate || confirmLoading}
                    className="mt-3 rounded-full border border-emerald-700 px-5 py-2 text-sm font-semibold text-emerald-800 hover:bg-emerald-50 disabled:cursor-not-allowed disabled:opacity-50">
                    {confirmLoading ? 'Confirming…' : 'Confirm selected food'}
                  </button>
                </>
              )}
              {confirmation && !confirmation.ok && (
                <p role="alert" className="mt-3 rounded-xl border border-red-200 bg-red-50 p-3 text-sm text-red-800">
                  {confirmation.error.message} <span className="text-xs">({confirmation.error.code})</span>
                </p>
              )}
              <ManualPicker open={pickerOpen} setOpen={setPickerOpen} busy={confirmLoading} onConfirm={(f) => void confirmName(f)}
                prompt="None of these? Choose from all supported foods:" />
            </section>
          )}

          {success && !awaitingConfirmation && (
            <article className="mt-5 rounded-3xl border border-emerald-900/10 bg-white p-5 shadow-soft sm:p-6" aria-labelledby="result-heading">
              <header className="flex flex-wrap items-start justify-between gap-3">
                <div className="min-w-0">
                  <p className="flex flex-wrap items-center gap-2 text-xs font-semibold uppercase tracking-wider text-emerald-700">
                    {category ?? 'Food'}<span aria-hidden="true">›</span><span className="normal-case tracking-normal text-ink-soft">
                      {scoreConfirmed ? 'Confirmed by you · ' : ''}{success.identification ? identificationSourceText(success.identification) : success.kind === 'confirmed' ? 'Selected by you' : 'Recognised food'}</span>
                  </p>
                  <h2 id="result-heading" className="mt-1 break-words font-display text-3xl font-extrabold leading-tight">{success.food}</h2>
                  <div className="mt-2 flex flex-wrap items-center gap-1.5 text-xs">
                    {(success.identification?.verified_by ?? []).map((v) => <Badge key={v} tone={v === 'You' ? 'blue' : 'green'}>{v}</Badge>)}
                    {isValidRecognitionScore(success.confidence) ? (
                      <span className="text-ink-soft">Image-model score {formatConfidencePercent(success.confidence)} (a score, not a probability)</span>
                    ) : success.identification?.source === 'openai' && (
                      <span className="text-ink-soft">No numeric confidence: {success.identification.provider ?? 'OpenAI Vision'} does not provide a calibrated score, so none is shown. Not one of the 24 foods the image model was trained on.</span>
                    )}
                  </div>
                </div>
                <Link to="/history" className="shrink-0 rounded-full px-3 py-1.5 text-sm font-semibold text-emerald-700 hover:bg-emerald-50">View history</Link>
              </header>
              {!notListed && <SafetyAlertBanner alert={success.safetyAlert} />}
              {success.suggestPackaged && (
                <div className="mt-4 flex flex-wrap items-center gap-3 rounded-2xl border border-sky-900/15 bg-sky-50/60 p-4 text-sm">
                  <span className="min-w-0 flex-1">This looks like a packaged product. Its nutrition is on its label, so scan the label or barcode for the exact product.</span>
                  <Link to="/scan-packaged" className="rounded-full bg-emerald-700 px-4 py-2 font-semibold text-white hover:bg-emerald-800">Scan packaged food</Link>
                </div>
              )}
              {success.warnings.length > 0 && (
                <p className="mt-3 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">Warning: non-food rejection is not calibrated on this server.</p>
              )}
              <RecognitionNote recognition={success.recognition} openai={success.openaiVision} />
              <VisionNote v={success.vision} />
              {success.kind === 'recognized' && supportedClass && (
                <>
                  <ManualPicker open={pickerOpen} setOpen={setPickerOpen} busy={confirmLoading} onConfirm={(f) => void confirmName(f)}
                    prompt="Choose the correct food:" toggleLabel="Not correct? Choose the food"
                    onNotListed={() => {
                      setNotListed(true); setPickerOpen(false)
                      if (user && result?.ok) void api('/api/corrections', { method: 'POST', body: { predicted: result.data.prediction.food, not_recognized: true } })
                    }} />
                  {confirmation && !confirmation.ok && <p role="alert" className="mt-2 text-sm text-red-800">{confirmation.error.message}</p>}
                </>
              )}
              {notListed ? (
                <p role="alert" className="mt-4 rounded-xl bg-amber-50 p-3 text-sm text-amber-900">
                  Your food is not one of the foods SmartPlateAI supports, so this result is wrong and the nutrition does not apply. Try another photo.
                </p>
              ) : (
                <div className="mt-5 grid items-start gap-5 lg:grid-cols-[minmax(0,1.25fr)_minmax(0,1fr)]">
                  <div className="min-w-0 space-y-4">
                    <SpecificTypeChooser choice={success.nutritionChoice} alternative={success.nutrition ? null : success.genericAlternative}
                      busy={confirmLoading} onPick={(name) => void confirmName(name, success.imageRef)}
                      onGeneric={(category) => void confirmName(category, success.imageRef, true)} />
                    <NutritionCard nutrition={success.nutrition} spoiled={spoiled} produce={category === 'Fruits' || category === 'Vegetables'}
                      error={success.nutritionChoice ? 'Nutrition is shown after you choose the specific type, or accept the generic reference, above.'
                        : success.nutritionError} />
                    {supportedClass && <ChemicalPanel food={supportedClass} />}
                  </div>
                  <div className="min-w-0 space-y-4">
                    <FreshnessCard f={success.freshness} />
                    {/* Spoiled food is not offered for the "eaten today" log. */}
                    <SaveActions analysisId={success.analysisId} kind="fresh" history={success.history} canLog={Boolean(success.nutrition) && !spoiled} />
                    <Precautions items={success.precautions} />
                  </div>
                </div>
              )}
              <ul className="mt-5 list-disc space-y-0.5 pl-5 text-xs text-ink-soft">
                {success.notes.map((n) => <li key={n}>{n}</li>)}
              </ul>
              <div className="mt-5 flex flex-wrap gap-2 border-t border-emerald-900/10 pt-4">
                <button type="button" onClick={reset} className="inline-flex items-center gap-2 rounded-full border border-emerald-900/15 px-5 py-2 text-sm font-semibold hover:bg-emerald-50">
                  <RefreshCw className="h-4 w-4" aria-hidden="true" /> Analyse another photo
                </button>
                {/* Offered only for an identified food that is not flagged as possibly spoiled. */}
                {!notListed && !spoiled && success.nutrition && (
                  <Link to={`/meal-planner?have=${encodeURIComponent(success.food)}`}
                    className="inline-flex items-center gap-2 rounded-full px-5 py-2 text-sm font-semibold text-emerald-700 hover:bg-emerald-50">
                    <Sparkles className="h-4 w-4" aria-hidden="true" /> Plan meals with {success.food.toLowerCase()}
                  </Link>
                )}
              </div>
            </article>
          )}
        </div>
      </div>
    </Wrapper>
  )
}

function ManualPicker({ open, setOpen, busy, onConfirm, prompt, toggleLabel = 'Choose the food manually', onNotListed }: {
  open: boolean
  setOpen: (v: boolean) => void
  busy: boolean
  onConfirm: (food: string) => void
  prompt: string
  toggleLabel?: string
  onNotListed?: () => void
}) {
  const [foods, setFoods] = useState<string[] | null>(null)
  const [failed, setFailed] = useState(false)
  const [choice, setChoice] = useState('')
  useEffect(() => {
    if (!open || foods) return
    const ctrl = new AbortController()
    let active = true
    getSupportedFoods(ctrl.signal).then((f) => {
      if (!active) return
      if (f) setFoods(f)
      else setFailed(true)
    })
    return () => {
      active = false
      ctrl.abort()
    }
  }, [open, foods])
  const matchingFoods = foods?.filter((food) => choice.trim()
    && food.toLocaleLowerCase().includes(choice.trim().toLocaleLowerCase())).slice(0, 8) ?? []
  if (!open) {
    return (
      <button type="button" onClick={() => setOpen(true)} className="mt-3 text-sm font-semibold text-emerald-700 underline-offset-2 hover:underline">
        {toggleLabel}
      </button>
    )
  }
  return (
    <div className="mt-4 rounded-2xl border border-emerald-900/10 bg-cream p-4 text-ink" aria-busy={busy}>
      <form onSubmit={(event) => { event.preventDefault(); if (choice.trim() && !busy) onConfirm(choice.trim()) }}>
        <label htmlFor="manual-food" className="text-sm font-semibold">{prompt}</label>
        {failed && <p className="mt-1 text-xs text-amber-800">Supported-food suggestions are unavailable. You can still enter a food name.</p>}
        {!foods && !failed && <p className="mt-1 text-xs text-ink-soft" role="status">Loading food suggestions…</p>}
        <div className="mt-2 flex flex-wrap gap-2">
          <input
            id="manual-food"
            type="text"
            list="supported-food-suggestions"
            value={choice}
            onChange={(event) => setChoice(event.target.value)}
            maxLength={120}
            required
            autoComplete="off"
            placeholder="Type or choose a food"
            disabled={busy}
            className="min-w-0 flex-1 rounded-xl border border-emerald-900/15 bg-white px-3 py-2.5 text-sm"
          />
          <datalist id="supported-food-suggestions">
            {foods?.map((food) => <option key={food} value={food} />)}
          </datalist>
          <button type="submit" disabled={!choice.trim() || busy}
            className="rounded-full bg-emerald-700 px-5 py-2.5 text-sm font-semibold text-white hover:bg-emerald-800 disabled:opacity-50">
            {busy ? 'Looking up…' : 'Use this food'}
          </button>
        </div>
        <p className="mt-1 text-xs text-ink-soft">A food name is required. Empty submissions are disabled.</p>
        {matchingFoods.length > 0 && (
          <div className="mt-2 flex flex-wrap gap-2" aria-label="Matching supported foods">
            {matchingFoods.map((food) => (
              <button key={food} type="button" onClick={() => setChoice(food)} disabled={busy}
                className="rounded-full border border-emerald-900/10 bg-white px-3 py-1 text-xs font-semibold text-emerald-800 hover:bg-emerald-50 disabled:opacity-50">
                {food}
              </button>
            ))}
          </div>
        )}
      </form>
      <div className="mt-2 flex flex-wrap gap-4 text-xs">
        {onNotListed && (
          <button type="button" onClick={onNotListed} className="font-semibold text-amber-800 hover:underline">My food is not in this list</button>
        )}
        <button type="button" onClick={() => setOpen(false)} className="text-ink-soft hover:underline">Cancel</button>
      </div>
      <p className="mt-2 text-xs text-ink-soft">A food you enter is labelled as user-selected, not model-verified. Nutrition is shown only when a reference record is available.</p>
    </div>
  )
}
