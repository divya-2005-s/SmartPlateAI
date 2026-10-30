/** Food-identification confidence policy, mirrored from the backend (app/api/routes/analyze.py):
 *  confidence >= 70% is accepted automatically (exactly 70% included); below 70% the user confirms. */
export const AUTO_ACCEPT_SCORE_THRESHOLD = 0.7
export const AUTO_ACCEPT_PERCENT = 70

/** A valid 0..1 fraction, as the API sends `prediction.confidence`. */
export function isValidRecognitionScore(score: unknown): score is number {
  return typeof score === 'number'
    && Number.isFinite(score)
    && score >= 0
    && score <= 1
}

/**
 * Confidence as a percentage, or null when missing/invalid. 0..1 is a fraction (0.7 -> 70); 1 < value <= 100 is already
 * a percentage (70 -> 70, never scaled twice). Snapped to 6 decimals so float noise (0.29 * 100 = 28.999999999999996)
 * cannot move a value across the threshold.
 */
export function confidencePercent(value: unknown): number | null {
  if (typeof value !== 'number' || !Number.isFinite(value) || value < 0 || value > 100) return null
  const pct = value <= 1 ? value * 100 : value
  return Math.round(pct * 1e6) / 1e6
}

export function hasHighRecognitionScore(score: unknown): boolean {
  const pct = confidencePercent(score)
  return pct !== null && pct >= AUTO_ACCEPT_PERCENT
}

/** One decimal, rounded DOWN, so "70.0%" is never shown for a value that did not pass the 70% rule. */
export function formatConfidencePercent(value: unknown): string | null {
  const pct = confidencePercent(value)
  return pct === null ? null : `${(Math.floor(Math.round(pct * 10 * 1e6) / 1e6) / 10).toFixed(1)}%`
}

/** Identification sources that are independent of the SmartPlateAI image model (names as sent in `verified_by`). */
export const INDEPENDENT_VERIFIERS: readonly string[] = ['OpenAI Vision', 'Google Gemini', 'Google Vision']

/** Fallback rule when the server did not send `requires_confirmation`: ask when the score is below 70% and no
 *  independent vision service verified the identification. */
export function needsUserConfirmation(score: unknown, verifiedBy: readonly string[] | null | undefined): boolean {
  if (hasHighRecognitionScore(score)) return false
  return !(verifiedBy ?? []).some((v) => INDEPENDENT_VERIFIERS.includes(v))
}

type AcceptedResult = {
  requires_confirmation?: boolean
  prediction: { confidence: number | null }
  identification?: { verified_by: string[] }
}

/** The confirmation decision for an accepted analysis. The server's decision is authoritative when present. */
export function confirmationRequired(data: AcceptedResult): boolean {
  if (typeof data.requires_confirmation === 'boolean') return data.requires_confirmation
  return needsUserConfirmation(data.prediction.confidence, data.identification?.verified_by)
}

type AnalysisOutcome =
  | { ok: true; data: { image_ref?: string | null } }
  | { ok: false; error: { image_ref?: string | null; pending_id?: string } }

/** The server-side reference to the photo of THIS analysis, sent with every confirmation or correction so that
 *  freshness is assessed on that photo for the chosen food. Only ever taken from the current result. */
export function photoRefFor(result: AnalysisOutcome | null | undefined): string | undefined {
  if (!result) return undefined
  const ref = result.ok ? result.data.image_ref : result.error.image_ref ?? result.error.pending_id
  return ref ?? undefined
}

type SourceInfo = { source: 'image_model_and_openai' | 'image_model' | 'openai' | 'user_confirmed' | 'user_selected'; provider?: string | null }

/** How the food was identified, naming the general vision service that actually answered (OpenAI or Gemini). */
export function identificationSourceText(ident: SourceInfo): string {
  const provider = ident.provider ?? 'OpenAI Vision'
  return {
    image_model_and_openai: `Recognised by the SmartPlateAI image model and confirmed by ${provider}`,
    image_model: 'Recognised by the SmartPlateAI image model',
    openai: `Identified by ${provider}`,
    user_confirmed: `Confirmed by you from the ${provider} suggestion`,
    user_selected: 'Selected by you',
  }[ident.source]
}
