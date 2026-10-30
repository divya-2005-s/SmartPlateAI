import assert from 'node:assert/strict'
import test from 'node:test'
import {
  confidencePercent, confirmationRequired, formatConfidencePercent, hasHighRecognitionScore, isValidRecognitionScore,
  identificationSourceText, needsUserConfirmation, photoRefFor,
} from '../src/lib/recognitionConfidence.ts'

test('scores at or above 70 percent proceed directly to results', () => {
  assert.equal(hasHighRecognitionScore(0.85), true)
  assert.equal(hasHighRecognitionScore(0.71), true)
  assert.equal(hasHighRecognitionScore(0.7), true) // exactly 70% is accepted (requirement changed 2026-10-15)
})

test('scores below 70 percent require confirmation', () => {
  assert.equal(hasHighRecognitionScore(0.69), false)
  assert.equal(hasHighRecognitionScore(0.6999), false)
  assert.equal(hasHighRecognitionScore(0.4), false)
})

test('fractions and percentages are normalised once, at the same boundary', () => {
  for (const [value, pct, auto] of [[0.69, 69, false], [0.7, 70, true], [0.71, 71, true], [69, 69, false], [70, 70, true], [71, 71, true]] as const) {
    assert.equal(confidencePercent(value), pct)
    assert.equal(hasHighRecognitionScore(value), auto)
  }
  assert.equal(confidencePercent(0.29), 29) // 0.29 * 100 = 28.999999999999996 is snapped, not floored
})

test('the displayed percentage never rounds up across the threshold', () => {
  assert.equal(formatConfidencePercent(0.69999), '69.9%')
  assert.equal(formatConfidencePercent(0.7), '70.0%')
  assert.equal(formatConfidencePercent(0.29), '29.0%')
  assert.equal(formatConfidencePercent(null), null)
})

test('missing and invalid scores never qualify for automatic acceptance', () => {
  for (const score of [undefined, null, Number.NaN, Number.POSITIVE_INFINITY, -0.1, 100.5, '0.9']) {
    assert.equal(hasHighRecognitionScore(score), false)
    assert.equal(isValidRecognitionScore(score), false)
  }
})

test('a result verified by an independent vision service is shown without asking again', () => {
  assert.equal(needsUserConfirmation(0.55, ['SmartPlateAI image model', 'OpenAI Vision']), false)
  assert.equal(needsUserConfirmation(0.4, ['SmartPlateAI image model', 'Google Vision']), false)
  assert.equal(needsUserConfirmation(null, ['OpenAI Vision']), false) // food outside the model classes, named by OpenAI
})

test('a low or missing score from the image model alone still requires confirmation', () => {
  assert.equal(needsUserConfirmation(0.69, ['SmartPlateAI image model']), true)
  assert.equal(needsUserConfirmation(0.7, ['SmartPlateAI image model']), false)
  assert.equal(needsUserConfirmation(null, undefined), true)
  assert.equal(needsUserConfirmation(Number.NaN, []), true)
})

test('the component decision follows the server, and the same rule without it', () => {
  const model = { identification: { verified_by: ['SmartPlateAI image model'] } }
  for (const [confidence, expected] of [[0.69, true], [0.7, false], [0.71, false]] as const) {
    assert.equal(confirmationRequired({ prediction: { confidence }, ...model }), expected) // older server: local rule
    assert.equal(confirmationRequired({ requires_confirmation: expected, prediction: { confidence } }), expected)
  }
  // the server's decision wins (e.g. it knows a second opinion verified a 55% result)
  assert.equal(confirmationRequired({ requires_confirmation: false, prediction: { confidence: 0.55 }, ...model }), false)
})

test('the photo reference comes only from the current analysis', () => {
  assert.equal(photoRefFor({ ok: true, data: { image_ref: 'scan-2' } }), 'scan-2')
  assert.equal(photoRefFor({ ok: false, error: { pending_id: 'scan-3' } }), 'scan-3')
  assert.equal(photoRefFor({ ok: false, error: { image_ref: 'scan-4', pending_id: 'scan-4' } }), 'scan-4')
  assert.equal(photoRefFor(null), undefined) // a new photo clears the result, so no earlier photo can be referenced
  assert.equal(photoRefFor({ ok: true, data: {} }), undefined)
})

test('the identification text names the vision service that actually answered', () => {
  assert.equal(identificationSourceText({ source: 'openai', provider: 'Google Gemini' }), 'Identified by Google Gemini')
  assert.equal(identificationSourceText({ source: 'openai' }), 'Identified by OpenAI Vision') // older responses
  assert.equal(identificationSourceText({ source: 'image_model_and_openai', provider: 'Google Gemini' }),
    'Recognised by the SmartPlateAI image model and confirmed by Google Gemini')
  assert.equal(identificationSourceText({ source: 'image_model' }), 'Recognised by the SmartPlateAI image model')
})

test('Gemini counts as an independent verifier, like OpenAI and Google Vision', () => {
  assert.equal(needsUserConfirmation(0.55, ['SmartPlateAI image model', 'Google Gemini']), false)
  assert.equal(needsUserConfirmation(null, ['Google Gemini']), false)
})
