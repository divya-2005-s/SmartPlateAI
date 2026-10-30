import { authHeader } from './session'
export type TopK = { class_id: number; food: string; score: number }
export type Nutrient = { key: string; label: string; unit: string; per_100g: number | null; per_serving: number | null }
export type Nutrition = {
  basis: string
  source_fdc_id: number | null
  is_estimate: boolean
  note: string
  serving_grams: number | null
  serving_note: string
  nutrients: Nutrient[]
  not_available: string[]
  /** USDA record the values come from, and whether it is the generic record of a category food (e.g. Sandwich). */
  matched_description?: string | null
  source_url?: string | null
  generic_category_reference?: boolean
}
export type Freshness = {
  status: 'fresh' | 'possibly_spoiled' | 'uncertain' | 'not_assessed'
  confidence: number | null
  p_spoiled?: number | null
  message: string
  evidence?: string
  limitation?: string
  model_status?: string
  /** Display label, e.g. "Rotten / possibly spoiled"; "uncertain" is shown as borderline, not as a measured partial state. */
  condition_label?: string
  condition_summary?: string | null
  /** The model gives a fresh/rotten label only: these are always null and percent_supported is false. */
  freshness_percent?: null
  deterioration_percent?: null
  percent_supported?: boolean
  percent_note?: string
}
/** Headline safety message derived from freshness (danger = possibly spoiled, caution = borderline). */
export type SafetyAlert = { level: 'danger' | 'caution'; title: string; message: string; basis: string }
export type ImageQuality = {
  level: 'good' | 'fair' | 'poor'
  issues: string[]
  advice: string[]
  enhanceable: boolean
  metrics: { width: number; height: number; sharpness: number; brightness: number; contrast: number; clipped_share: number; glare_share: number }
  thresholds_note: string
}
export type Enhancement = { applied: boolean; used: 'original' | 'enhanced'; for?: string[] }
export type VisionInfo = {
  status: 'agrees' | 'conflicts' | 'generic' | 'no_food' | 'unavailable'
  message?: string
  agreeing_labels?: string[]
  conflicting_supported_foods?: string[]
  conflicting_labels?: string[]
  hints_outside_supported?: string[]
  top_labels?: { name: string; score: number }[]
}
export type OpenAIVisionInfo = {
  status: 'recognized' | 'unsupported_food' | 'no_food' | 'uncertain' | 'unavailable'
  reason?: string
  food_name?: string | null
  supported_food?: string | null
  visible_evidence?: string[]
  uncertainty?: string | null
}
export type RecognitionInfo = {
  status: 'verified_both' | 'tensorflow_fallback' | 'confirmation_required' | 'unsupported_food' | 'non_food' | 'openai_identified'
  message: string
  openai_status: OpenAIVisionInfo['status']
}
export type Precaution = { kind: string; text: string; source: string }
export type Identification = {
  food: string
  category: string
  source: 'image_model_and_openai' | 'image_model' | 'openai' | 'user_confirmed' | 'user_selected'
  supported_class: string | null
  verified_by: string[]
  /** General vision service that identified or confirmed the food: 'OpenAI Vision' or 'Google Gemini'. */
  provider?: string | null
  /** 'category' = the model recognised a kind of dish (e.g. Sandwich) but not which one; specific_type is then null. */
  specificity?: 'category' | 'specific'
  specific_type?: string | null
}
/** The generic USDA record of a category food, described exactly; never applied without the user's explicit choice. */
export type GenericReference = { food: string; fdc_id: number | null; description: string | null; data_type?: string | null; source_url?: string | null; caveat?: string | null }
/** A category food was recognised: nutrition waits until the user picks a specific type or accepts the generic record. */
export type NutritionChoice = { category: string; specific_type: null; suggested: string | null; options: string[]; generic_reference: GenericReference | null; message: string }
/** Outcome of the automatic save to scan history (only for successful analyses). */
export type HistoryStatus = { saved: true; scan_id: number; duplicate: boolean } | { saved: false; reason: string; message: string }
export type GeneralCandidate = { food: string; category: string; source: string; note: string }
export type FoodSuccess = {
  success: true
  analysis_id?: string
  /** Server-side reference to this analysis's photo; send it when correcting the food so freshness is re-assessed. */
  image_ref?: string | null
  /** Server's confirmation decision (70% rule / independent verification). */
  requires_confirmation?: boolean
  acceptance_basis?: string
  /** OpenAI saw a packaged product: its nutrition must come from the label/barcode scanner, not a generic record. */
  suggest_packaged_scan?: boolean
  identification?: Identification
  history?: HistoryStatus
  freshness?: Freshness
  image_quality?: ImageQuality
  enhancement?: Enhancement
  vision?: VisionInfo | null
  recognition?: RecognitionInfo
  openai_vision?: OpenAIVisionInfo
  precautions?: Precaution[]
  safety_alert?: SafetyAlert | null
  /** class_id/confidence are null when the food was identified by OpenAI outside the 24 model classes. */
  prediction: { food: string; class_id: number | null; confidence: number | null; confidence_percent?: number | null; margin: number | null; top_k: TopK[] }
  nutrition: Nutrition | null
  nutrition_error: string | null
  nutrition_choice?: NutritionChoice | null
  generic_alternative?: GenericReference | null
  notes: string[]
  warnings: string[]
}
export type ApiError = {
  code: string
  message: string
  candidates?: TopK[]
  confidence?: number
  margin?: number
  requires_confirmation?: boolean
  /** Why the image was not accepted: low_confidence | classifier_disagreement | far_from_supported_foods */
  reason?: string
  vision?: VisionInfo | null
  recognition?: RecognitionInfo
  openai_vision?: OpenAIVisionInfo
  /** A food outside the 24 classes suggested by OpenAI for this photo; confirm it with pending_id. */
  general_candidate?: GeneralCandidate | null
  pending_id?: string
  image_ref?: string | null
  image_quality?: ImageQuality
  enhancement?: Enhancement
  freshness?: Freshness
  safety_alert?: SafetyAlert | null
}
export type AnalyzeResult = { ok: true; data: FoodSuccess } | { ok: false; error: ApiError }
export type ConfirmFoodRequest = { food: string; serving_grams?: number; pending_id?: string; accept_generic?: boolean }
export type FoodConfirmationSuccess = {
  success: true
  analysis_id?: string
  identification?: Identification
  history?: HistoryStatus
  recognition?: RecognitionInfo
  freshness?: Freshness
  image_quality?: ImageQuality
  enhancement?: Enhancement
  precautions?: Precaution[]
  safety_alert?: SafetyAlert | null
  image_ref?: string | null
  confirmation: { food: string; source: 'user_selected' | 'user_confirmed_suggestion'; accepted_generic_reference?: boolean }
  nutrition: Nutrition | null
  nutrition_error: string | null
  nutrition_choice?: NutritionChoice | null
  generic_alternative?: GenericReference | null
  notes: string[]
}
export type ConfirmFoodResult =
  | { ok: true; data: FoodConfirmationSuccess }
  | { ok: false; error: ApiError }

export const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? ''

export async function readBody(res: Response): Promise<Record<string, unknown> | null> {
  try {
    const body: unknown = await res.json()
    return body && typeof body === 'object' ? body as Record<string, unknown> : null
  } catch {
    return null
  }
}

export function responseError(body: Record<string, unknown> | null, status: number): ApiError {
  if (body && body.success === false && typeof body.error_code === 'string' && typeof body.message === 'string') {
    return {
      code: body.error_code,
      message: body.message,
      candidates: Array.isArray(body.candidates) ? body.candidates as TopK[] : undefined,
      confidence: typeof body.confidence === 'number' ? body.confidence : undefined,
      margin: typeof body.margin === 'number' ? body.margin : undefined,
      requires_confirmation: body.requires_confirmation === true,
      reason: typeof body.reason === 'string' ? body.reason : undefined,
      vision: body.vision && typeof body.vision === 'object' ? body.vision as VisionInfo : undefined,
      recognition: body.recognition && typeof body.recognition === 'object' ? body.recognition as RecognitionInfo : undefined,
      openai_vision: body.openai_vision && typeof body.openai_vision === 'object' ? body.openai_vision as OpenAIVisionInfo : undefined,
      general_candidate: body.general_candidate && typeof body.general_candidate === 'object' ? body.general_candidate as GeneralCandidate : null,
      pending_id: typeof body.pending_id === 'string' ? body.pending_id : undefined,
      image_ref: typeof body.image_ref === 'string' ? body.image_ref : undefined,
      image_quality: body.image_quality && typeof body.image_quality === 'object' ? body.image_quality as ImageQuality : undefined,
      enhancement: body.enhancement && typeof body.enhancement === 'object' ? body.enhancement as Enhancement : undefined,
      freshness: body.freshness && typeof body.freshness === 'object' ? body.freshness as Freshness : undefined,
      safety_alert: body.safety_alert && typeof body.safety_alert === 'object' ? body.safety_alert as SafetyAlert : null,
    }
  }
  return {
    code: 'UNEXPECTED_RESPONSE',
    message: `The server returned an unexpected response (HTTP ${status}). Please try again.`,
  }
}

export function backendUnavailableError(): ApiError {
  return {
    code: 'BACKEND_UNAVAILABLE',
    message: 'Cannot reach the SmartPlateAI server. Make sure the backend is running and try again.',
  }
}

/** Never turns an error into a success: only an HTTP 2xx body with success === true is accepted. */
/** A stable key per analysis attempt: if the same request is retried, the server saves it to history only once. */
export function newRequestKey(): string {
  try {
    if (typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function') return crypto.randomUUID()
  } catch {
    /* fall through */
  }
  return `k${Date.now().toString(36)}${Math.random().toString(36).slice(2, 10)}`
}

export async function analyzeFood(file: File, servingGrams?: number, signal?: AbortSignal, requestKey?: string): Promise<AnalyzeResult> {
  const form = new FormData()
  form.append('file', file)
  if (servingGrams !== undefined) form.append('serving_grams', String(servingGrams))

  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/analyze/food`, {
      method: 'POST', body: form, signal, credentials: 'include',
      headers: { ...authHeader(), ...(requestKey ? { 'Idempotency-Key': requestKey } : {}) },
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    return { ok: false, error: backendUnavailableError() }
  }

  const body = await readBody(res)
  if (res.ok && body && body.success === true && typeof body.prediction === 'object' && body.prediction !== null) {
    return { ok: true, data: body as unknown as FoodSuccess }
  }
  return { ok: false, error: responseError(body, res.status) }
}

export async function confirmFood(food: string, servingGrams?: number, signal?: AbortSignal, pendingId?: string,
  acceptGeneric = false): Promise<ConfirmFoodResult> {
  const request: ConfirmFoodRequest = {
    food,
    ...(servingGrams !== undefined ? { serving_grams: servingGrams } : {}),
    ...(pendingId ? { pending_id: pendingId } : {}),
    ...(acceptGeneric ? { accept_generic: true } : {}),
  }
  let res: Response
  try {
    res = await fetch(`${API_BASE}/api/analyze/confirm`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'Content-Type': 'application/json', ...authHeader() },
      body: JSON.stringify(request),
      signal,
    })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    return { ok: false, error: backendUnavailableError() }
  }

  const body = await readBody(res)
  if (res.ok && body && body.success === true && typeof body.confirmation === 'object' && body.confirmation !== null) {
    return { ok: true, data: body as unknown as FoodConfirmationSuccess }
  }
  return { ok: false, error: responseError(body, res.status) }
}
/** The 24 foods the model supports, for manual correction. Returns null if the server cannot provide them. */
export async function getSupportedFoods(signal?: AbortSignal): Promise<string[] | null> {
  try {
    const res = await fetch(`${API_BASE}/api/foods/supported`, { signal })
    const body = await readBody(res)
    return res.ok && body && Array.isArray(body.foods) ? (body.foods as string[]) : null
  } catch {
    return null
  }
}
