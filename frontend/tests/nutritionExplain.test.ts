import assert from 'node:assert/strict'
import test from 'node:test'
import { canonical, explainNutrition, fmt, MEANING } from '../src/lib/nutritionExplain.ts'
import type { NutrientInput } from '../src/lib/nutritionExplain.ts'

// Apple-like USDA record per 100 g (keys as in the project nutrition CSV), with saturated fat not reported.
const apple: NutrientInput[] = [
  { key: 'energy_kcal', label: 'Energy', unit: 'kcal', per100: 52, perServing: null },
  { key: 'protein_g', label: 'Protein', unit: 'g', per100: 0.26, perServing: null },
  { key: 'fat_g', label: 'Fat', unit: 'g', per100: 0.17, perServing: null },
  { key: 'carbohydrate_g', label: 'Carbohydrate', unit: 'g', per100: 13.8, perServing: null },
  { key: 'fiber_g', label: 'Fiber', unit: 'g', per100: 2.4, perServing: null },
  { key: 'sugars_g', label: 'Sugars', unit: 'g', per100: 10.4, perServing: null },
  { key: 'sodium_mg', label: 'Sodium', unit: 'mg', per100: 1, perServing: null },
  { key: 'vitamin_d_ug', label: 'Vitamin d', unit: 'µg', per100: null, perServing: null },
]
const scaled = (rows: NutrientInput[], g: number) => rows.map((r) => ({ ...r, perServing: r.per100 === null ? null : (r.per100 * g) / 100 }))

test('source keys and labels map to canonical nutrients', () => {
  assert.equal(canonical('fat_g'), 'total_fat')
  assert.equal(canonical('Fatty acids, total saturated'), 'saturated_fat')
  assert.equal(canonical('fiber_g'), 'fibre')
  assert.equal(canonical('Added sugars'), 'added_sugars')
  assert.equal(canonical('sugars_g'), 'total_sugars')
  assert.equal(canonical('vitamin_a_rae_ug'), 'vitamin_a')
  assert.equal(canonical('salt_g'), 'salt')
})

test('a trace amount is not displayed as zero', () => {
  assert.equal(fmt(0.0025), 'less than 0.01')
  assert.equal(fmt(0), '0')
  assert.equal(fmt(13.84), '13.8')
  assert.equal(fmt(0.26), '0.26')
})

test('missing nutrients are unavailable, never zero', () => {
  const e = explainNutrition({ nutrients: apple, servingGrams: null, basis: 'per100g' })
  const sat = e.glance.find((g) => g.canon === 'saturated_fat')!
  assert.equal(sat.available, false)
  assert.equal(sat.per100, null)
  const added = e.glance.find((g) => g.canon === 'added_sugars')!
  assert.equal(added.available, false)
  const vitD = e.meanings.find((m) => m.canon === 'vitamin_d')!
  assert.equal(vitD.available, false) // listed by the source, value missing
  assert.equal(e.glance.find((g) => g.canon === 'energy')!.per100, 52)
})

test('known values get everyday explanations with their units', () => {
  const e = explainNutrition({ nutrients: apple, servingGrams: null, basis: 'per100g' })
  assert.equal(e.meanings.find((m) => m.canon === 'protein')!.text, MEANING.protein)
  assert.match(MEANING.sodium, /high blood pressure/)
  assert.ok(e.units.includes('kcal = kilocalories, the "calories" on food labels'))
  assert.ok(e.units.some((u) => u.startsWith('mg =')))
})

test('serving-size scaling and portion sentences use the per-100 g data', () => {
  const e = explainNutrition({ nutrients: scaled(apple, 150), servingGrams: 150, basis: 'per100g' })
  const fib = e.glance.find((g) => g.canon === 'fibre')!
  assert.equal(fib.perServing, 3.6)
  assert.equal(fib.dvPercent, 13) // 3.6 g of the 28 g FDA Daily Value
  assert.ok(e.portion.some((p) => p === '150 g provides 3.6 g of dietary fibre (13% of the Daily Value).'))
  assert.ok(e.portion.some((p) => p.startsWith('150 g provides about 78 kcal')))
  assert.ok(e.notes.some((n) => n.includes('scaled from the per-100 g values')))
})

test('no serving size: no percentages, and the user is told a photo cannot measure weight', () => {
  const e = explainNutrition({ nutrients: apple, servingGrams: null, basis: 'per100g' })
  assert.ok(e.glance.every((g) => g.dvPercent === null))
  assert.equal(e.portion.length, 0)
  assert.ok(e.notes.some((n) => n.includes('cannot measure the weight of food from a photo')))
})

test('salt is derived from sodium only when the source gives no salt, and is labelled as calculated', () => {
  const e = explainNutrition({ nutrients: [{ key: 'sodium_mg', label: 'Sodium', unit: 'mg', per100: 800, perServing: null }], servingGrams: null, basis: 'per100g' })
  const salt = e.glance.find((g) => g.canon === 'salt')!
  assert.equal(salt.per100, 2)
  assert.match(salt.derived ?? '', /Calculated from sodium/)
  assert.ok(e.observations.some((o) => o.canon === 'salt' && o.level === 'high'))
})

test('a label whose salt and sodium disagree is reported, not silently combined', () => {
  const e = explainNutrition({ nutrients: [
    { key: 'sodium_mg', label: 'Sodium', unit: 'mg', per100: 400, perServing: null },
    { key: 'salt_g', label: 'Salt', unit: 'g', per100: 3, perServing: null }], servingGrams: null, basis: 'per100g' })
  assert.equal(e.glance.find((g) => g.canon === 'salt')!.per100, 3)
  assert.ok(e.notes.some((n) => n.includes('do not match the usual conversion')))
})

test('reference-criteria observations name their standard and are never health verdicts', () => {
  const chips: NutrientInput[] = [
    { key: 'energy_kcal', label: 'Energy', unit: 'kcal', per100: 536, perServing: null },
    { key: 'protein_g', label: 'Protein', unit: 'g', per100: 7, perServing: null },
    { key: 'total_fat_g', label: 'Total fat', unit: 'g', per100: 35, perServing: null },
    { key: 'saturated_fat_g', label: 'Saturated fat', unit: 'g', per100: 3.1, perServing: null },
    { key: 'total_sugars_g', label: 'Total sugars', unit: 'g', per100: 0.3, perServing: null },
    { key: 'dietary_fibre_g', label: 'Dietary fibre', unit: 'g', per100: 4.4, perServing: null },
  ]
  const e = explainNutrition({ nutrients: chips, servingGrams: null, basis: 'per100g' })
  const by = (c: string) => e.observations.find((o) => o.canon === c)!
  assert.equal(by('total_fat').level, 'high')
  assert.equal(by('saturated_fat').level, 'medium')
  assert.equal(by('total_sugars').level, 'low')
  assert.equal(by('fibre').level, 'source')
  assert.equal(e.observations.some((o) => o.canon === 'protein'), false) // 7 g x 4 / 536 kcal = 5% of energy: below 12%
  for (const o of e.observations) {
    assert.ok(o.standard.length > 0)
    assert.doesNotMatch(o.text, /\b(healthy|unhealthy|safe|dangerous|cure|prevent|treat)\b/i)
  }
})

test('fresh produce sugars are described as naturally occurring', () => {
  const e = explainNutrition({ nutrients: apple, servingGrams: null, basis: 'per100g', naturalSugars: true })
  assert.ok(e.observations.some((o) => o.canon === 'total_sugars' && o.text.includes('occur naturally')))
})

test('per-serving-only and unknown-basis values are not compared with per-100 g criteria', () => {
  const rows: NutrientInput[] = [{ key: 'total_fat_g', label: 'Total fat', unit: 'g', per100: null, perServing: 20 }]
  const perServing = explainNutrition({ nutrients: rows, servingGrams: 30, basis: 'perServing' })
  assert.equal(perServing.observations.length, 0)
  assert.equal(perServing.glance.find((g) => g.canon === 'total_fat')!.perServing, 20)
  const unknown = explainNutrition({ nutrients: [{ key: 'total_fat_g', label: 'Total fat', unit: 'g', per100: 20, perServing: null }], servingGrams: null, basis: 'unknown' })
  const fat = unknown.glance.find((g) => g.canon === 'total_fat')!
  assert.equal(fat.per100, null)
  assert.equal(fat.asPrinted, 20)
  assert.equal(unknown.observations.length, 0)
})

test('drinks skip the food criteria with an explanation', () => {
  const e = explainNutrition({ nutrients: [{ key: 'total_sugars_g', label: 'Total sugars', unit: 'g', per100: 10.6, perServing: null }],
    servingGrams: null, basis: 'per100g', liquid: true })
  assert.equal(e.observations.length, 0)
  assert.ok(e.notes.some((n) => n.includes('per 100 ml')))
})

test('kJ energy is converted to kcal, other incompatible units are not mixed', () => {
  const e = explainNutrition({ nutrients: [{ key: 'energy', label: 'Energy', unit: 'kJ', per100: 2092, perServing: null },
    { key: 'calcium', label: 'Calcium', unit: 'kcal', per100: 5, perServing: null }], servingGrams: null, basis: 'per100g' })
  assert.equal(e.glance.find((g) => g.canon === 'energy')!.per100, 500)
  assert.equal(e.meanings.find((m) => m.canon === 'calcium')!.available, false) // kcal cannot be converted to mg
})
