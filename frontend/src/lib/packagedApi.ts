import { API_BASE, backendUnavailableError, readBody, responseError } from './foodApi'
import type { ApiError, HistoryStatus } from './foodApi'
import { authHeader } from './session'

export type LabelNutrient = { label: string; value: number; unit: string; raw: string; flags: string[] }
export type ParsedLabel = {
  ingredients_text: string | null
  ingredients: string[]
  ingredients_source?: string
  additive_codes: string[]
  nutrition: { basis: 'per 100 g' | 'per serving' | 'unknown'; values: Record<string, LabelNutrient>; source: string }
  serving_size_g: number | null
  allergens: { allergen: string; found_in: string[]; may_contain_only: boolean }[]
  identifiers: { fssai_licence: string | null; barcode_digits: string | null; net_quantity: string | null }
  dates?: { type: string; as_printed: string; context: string }[]
  storage?: string[]
  additive_classes?: { function: string; codes: string[]; as_printed: string }[]
  product_name_candidate?: string | null
}
export type DatasetNutrient = { key: string; label: string; unit: string; value: number | null; per_serving: number | null; flags: string[] }
export type ProductView = {
  id: string
  name: string
  brand: string | null
  category: string | null
  ingredients_text: string | null
  allergens_text: string | null
  additive_codes: string[]
  nutrition: {
    source: string
    basis: string
    basis_known: boolean
    dataset_serving_size_g: number | null
    serving_grams: number | null
    nutrients: DatasetNutrient[]
    not_available: string[]
  }
}
export type Additive = {
  code: string
  ins_label: string
  name: string | null
  function: string | null
  notes: string | null
  source: string | null
  in_reference: boolean
  found_on_label?: boolean
}
export type Precaution = { kind: 'guidance' | 'allergen' | 'additive'; source: string; text: string }
export type Candidate = { id: string; name: string; brand: string | null; score: number }
export type MatchInfo = {
  status: 'matched' | 'uncertain' | 'unmatched' | 'unavailable'
  method?: 'barcode' | 'text' | null
  confidence: number
  product_id: string | null
  candidates: Candidate[]
  reason: string | null
}
export type AllergenAlerts = {
  confirmed: { allergen: string; name: string; severity: string; evidence: string[] }[]
  possible: { allergen: string; name: string; severity: string; evidence: string[] }[]
  warnings: string[]
  preferences_checked: string[]
  has_preferences?: boolean
}
export type ExternalProduct = {
  status: 'found' | 'not_found' | 'invalid' | 'unavailable' | 'unconfirmed' | 'not_attempted'
  match?: string
  message?: string
  product?: { code: string | null; name: string | null; brand: string | null; ingredients_text: string | null; allergens: string[]; traces: string[];
    additive_codes: string[]; nutrition_per_100g: Record<string, number>; url: string | null; source: string; quantity: string | null }
  conflicts_with_label?: { nutrient: string; label_value: number; open_food_facts_value: number }[]
  /** Barcode lookups: false when the product's brand/name were not found in the text read from the pack. */
  verified_against_label?: boolean | null
}
export type LabelNutritionRow = {
  key: string; label: string; unit: string; value: number | null; ocr_value: number | null; ai_value: number | null
  status: 'agree' | 'conflict' | 'ocr_only' | 'ai_only'; source: string
}
export type PackageIdentity = {
  brand: string | null; product_name: string | null; variant: string | null; package_type: string | null; net_quantity: string | null
  claims: string[]; serving_size: string | null; manufacturer: string | null; source: string | null
}
export type Consistency = { status: 'consistent' | 'mismatch' | 'unverified' | 'single_image'; message: string | null
  front_brand?: string | null; back_brand?: string | null }
/** How the product was identified, with the evidence (dataset, Open Food Facts, or not identified). */
export type Identification = {
  status: 'identified' | 'candidates' | 'unidentified'
  source: string | null
  method: string | null
  name: string | null
  brand: string | null
  score: number | null
  evidence: string | null
  detected: { barcode: string | null; barcode_method: string | null; prominent_words: string[]; vision_reading: string | null }
}
export type BarcodeDetection = { status: string; code: string | null; format?: string | null; method?: string | null; votes?: number | null }
export type ExternalHit = { code: string; name: string | null; brand: string | null; quantity: string | null }

export type PackagedSuccess = {
  success: true
  analysis_id?: string
  category?: string
  images?: { front: boolean; back: boolean; closeup?: boolean }
  identity?: PackageIdentity
  consistency?: Consistency
  label_nutrition?: { basis: string; rows: LabelNutritionRow[]; readers: string[]; note: string | null }
  unidentified_additives?: string[]
  package_reading?: { status: string; reason?: string }
  history?: HistoryStatus
  external?: ExternalProduct | null
  allergen_alerts?: AllergenAlerts | null
  ocr: { text: string; confidence: number; word_count: number; rotation: number; quality: 'good' | 'low' | 'unreadable'
    front_text?: string; front_prominent?: string[] }
  identification?: Identification
  barcode_detection?: BarcodeDetection
  label: ParsedLabel
  match: MatchInfo
  product: ProductView | null
  additives: Additive[]
  precautions: Precaution[]
  warnings: string[]
  notes: string[]
}
export type ProductDetail = {
  success: true
  analysis_id?: string
  history?: HistoryStatus
  allergen_alerts?: AllergenAlerts | null
  product: ProductView
  additives: Additive[]
  precautions: Precaution[]
  source: 'user_selected'
  notes: string[]
}
type Result<T> = { ok: true; data: T } | { ok: false; error: ApiError }

async function request<T>(url: string, init: RequestInit, accept: (b: Record<string, unknown>) => boolean): Promise<Result<T>> {
  let res: Response
  try {
    res = await fetch(url, { ...init, credentials: 'include', headers: { ...(init.headers as Record<string, string> | undefined), ...authHeader() } })
  } catch (e) {
    if (e instanceof DOMException && e.name === 'AbortError') throw e
    return { ok: false, error: backendUnavailableError() }
  }
  const body = await readBody(res)
  if (res.ok && body && body.success === true && accept(body)) return { ok: true, data: body as unknown as T }
  return { ok: false, error: responseError(body, res.status) }
}

/** Front and/or back photo of ONE package. confirmSame is sent after the user confirms a PACKAGE_MISMATCH warning. */
export function analyzePackaged(images: { front?: File | null; back?: File | null; closeup?: File | null }, servingGrams?: number, signal?: AbortSignal,
  opts: { confirmSame?: boolean; requestKey?: string } = {}) {
  const form = new FormData()
  if (images.front) form.append('front', images.front)
  if (images.back) form.append('back', images.back)
  if (images.closeup) form.append('closeup', images.closeup)
  if (servingGrams !== undefined) form.append('serving_grams', String(servingGrams))
  if (opts.confirmSame) form.append('confirm_same_product', 'true')
  return request<PackagedSuccess>(`${API_BASE}/api/analyze/packaged`, {
    method: 'POST', body: form, signal, headers: opts.requestKey ? { 'Idempotency-Key': opts.requestKey } : undefined,
  }, (b) => typeof b.match === 'object' && b.match !== null)
}

export type BarcodeSuccess = ExternalProduct & { success: true; status: 'found'; barcode: string; format: string; analysis_id?: string
  allergen_alerts?: AllergenAlerts | null; history?: HistoryStatus }

/** Barcode lookup. Failures come back as typed errors: INVALID_BARCODE, PRODUCT_NOT_FOUND, LOOKUP_TIMEOUT,
 *  LOOKUP_RATE_LIMITED, LOOKUP_UNAVAILABLE, LOOKUP_BAD_RESPONSE. Leading zeros are kept. */
export function lookupBarcode(code: string, signal?: AbortSignal, requestKey?: string) {
  return request<BarcodeSuccess>(`${API_BASE}/api/packaged/off/${encodeURIComponent(code)}`,
    { signal, headers: requestKey ? { 'Idempotency-Key': requestKey } : undefined },
    (b) => b.status === 'found' && typeof b.product === 'object' && b.product !== null)
}

export type SearchResult = {
  success: true
  results: Candidate[]
  dataset_error?: string | null
  external?: { status: string; message?: string | null; results: ExternalHit[] }
}

/** Name search in the local dataset and (external=true) in Open Food Facts; the two lists are kept separate. */
export function searchProducts(q: string, signal?: AbortSignal, external = true) {
  return request<SearchResult>(
    `${API_BASE}/api/packaged/search?q=${encodeURIComponent(q)}${external ? '&external=true' : ''}`, { signal }, (b) => Array.isArray(b.results))
}

export function getProduct(id: string, servingGrams?: number, signal?: AbortSignal) {
  const qs = servingGrams !== undefined ? `?serving_grams=${servingGrams}` : ''
  return request<ProductDetail>(`${API_BASE}/api/packaged/products/${encodeURIComponent(id)}${qs}`, { signal },
    (b) => typeof b.product === 'object' && b.product !== null)
}

export type IngredientComponent = {
  key: string | null; name: string; ins: string | null; category: string | null; what: string | null; why: string | null
  consider: string | null; dataset_name: string | null; dataset_function: string | null
  verification: 'curated_glossary' | 'curated_glossary_and_dataset' | 'additive_dataset'; sources: string[]
}
export type IngredientItem = {
  as_written: string; class: { name: string; explanation: string } | null; components: IngredientComponent[]
  unknown_codes: string[]; status: 'explained' | 'partly_explained' | 'not_found'; message: string | null
}
export type IngredientsExplained = {
  success: true; source: string | null; uncertain: boolean; items: IngredientItem[]
  counts: { total: number; explained: number; partly_explained: number; not_found: number }; notes: string[]
}

/** Plain-language explanation of an ingredient list the app already has (label reading or product record). Reference data only. */
export function explainIngredients(text: string, source: string | null, uncertain: boolean, signal?: AbortSignal) {
  return request<IngredientsExplained>(`${API_BASE}/api/ingredients/explain`, {
    method: 'POST', body: JSON.stringify({ text: text.slice(0, 5000), source, uncertain }), signal,
    headers: { 'Content-Type': 'application/json' },
  }, (b) => Array.isArray(b.items))
}
