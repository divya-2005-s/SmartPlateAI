/** Plain-language nutrition explanations built only from the values a source actually provides.
 *
 *  Rules: a missing value is "Information unavailable", never 0; values are scaled only from per-100 g data; comparisons use
 *  named reference standards and are skipped when the basis does not fit them:
 *   - UK FSA/DH front-of-pack criteria for foods, per 100 g (fat, saturates, total sugars, salt) — the same standard the
 *     packaged-food precautions already use;
 *   - EU Regulation (EC) No 1924/2006 conditions for "source of protein / fibre" claims, per 100 g;
 *   - US FDA Daily Values (21 CFR 101.9, adults and children 4+ years, 2,000 kcal) for "% Daily Value" of a portion only.
 *  No food is called healthy or unhealthy. */

export type NutrientInput = { key: string; label: string; unit: string; per100: number | null; perServing: number | null }
export type ExplainInput = {
  nutrients: NutrientInput[]
  /** Grams the per-serving column refers to (user-entered or from the label), or null. */
  servingGrams: number | null
  /** 'per100g': `per100` holds per-100 g values. 'perServing': only `perServing` is known. 'unknown': basis not detected. */
  basis: 'per100g' | 'perServing' | 'unknown'
  /** Whole fruit or vegetable: its sugars are naturally occurring, not added. */
  naturalSugars?: boolean
  /** Drinks use different front-of-pack criteria (per 100 ml), so the per-100 g food comparison is skipped. */
  liquid?: boolean
}
export type Canon =
  | 'energy' | 'protein' | 'carbohydrate' | 'total_sugars' | 'added_sugars' | 'fibre' | 'total_fat' | 'saturated_fat' | 'trans_fat'
  | 'cholesterol' | 'sodium' | 'salt' | 'potassium' | 'calcium' | 'iron' | 'magnesium' | 'phosphorus' | 'zinc' | 'vitamin_a'
  | 'vitamin_c' | 'vitamin_d' | 'vitamin_e' | 'vitamin_k' | 'folate' | 'vitamin_b12' | 'water'

const PATTERNS: [Canon, RegExp][] = [
  ['energy', /^(energy|calor(ie|ies)|kcal)/], ['protein', /^protein/], ['added_sugars', /^added sugars?/],
  ['total_sugars', /^(total )?sugars?\b/], ['fibre', /^(dietary )?fib(re|er)/], ['saturated_fat', /^(fatty acids total )?saturated|^sat(urated)? fat/],
  ['trans_fat', /^(fatty acids total )?trans/], ['total_fat', /^(total )?(fat|lipid)s?( total)?$|^total lipid/],
  ['carbohydrate', /^(total )?carbohydrates?|^carbs?\b/], ['cholesterol', /^cholesterol/], ['sodium', /^sodium/], ['salt', /^salt/],
  ['potassium', /^potassium/], ['calcium', /^calcium/], ['iron', /^iron/], ['magnesium', /^magnesium/], ['phosphorus', /^phosphorus/],
  ['zinc', /^zinc/], ['vitamin_a', /^vitamin a/], ['vitamin_c', /^vitamin c|^ascorbic/], ['vitamin_d', /^vitamin d/],
  ['vitamin_e', /^vitamin e/], ['vitamin_k', /^vitamin k/], ['folate', /^folate|^folic/], ['vitamin_b12', /^vitamin b ?12/], ['water', /^water/],
]

export function canonical(keyOrLabel: string): Canon | null {
  const s = keyOrLabel.toLowerCase().replace(/_(kcal|kj|mg|ug|mcg|g|rae|dfe)\b/g, '').replace(/[^a-z0-9]+/g, ' ').trim()
  for (const [c, rx] of PATTERNS) if (rx.test(s)) return c
  return null
}

/** Everyday-language meaning of each nutrient. Short, no health claims. */
export const MEANING: Record<Canon, string> = {
  energy: 'Calories (kcal) measure the energy your body gets from food.',
  protein: 'Protein helps your body build and repair muscles and other tissues.',
  carbohydrate: "Carbohydrates are one of the body's main sources of energy. They include sugars and starch.",
  total_sugars: 'Total sugars count all sugars: those naturally present in fruit, vegetables and milk, and any sugar added during processing.',
  added_sugars: 'Added sugars are sugars and syrups put in during processing or cooking. Dietary guidelines generally advise limiting them.',
  fibre: 'Fibre supports digestion and can help you feel full.',
  total_fat: 'Fat provides energy and helps your body absorb vitamins A, D, E and K.',
  saturated_fat: 'Saturated fat is a type of fat. Eating too much over time can raise LDL ("bad") cholesterol.',
  trans_fat: 'Trans fat is a type of fat that raises LDL cholesterol; guidelines advise keeping it as low as possible.',
  cholesterol: 'Cholesterol is a fat-like substance found only in foods from animals.',
  sodium: 'Sodium is a mineral your body needs in small amounts. Too much sodium can contribute to high blood pressure.',
  salt: 'Salt is sodium chloride. Labels may show salt, sodium or both: 1 g of sodium is about 2.5 g of salt.',
  potassium: 'Potassium helps nerves and muscles work and helps balance fluids in the body.',
  calcium: 'Calcium helps build and maintain bones and teeth.',
  iron: 'Iron helps red blood cells carry oxygen around the body.',
  magnesium: 'Magnesium helps muscles and nerves work and supports energy production.',
  phosphorus: 'Phosphorus works with calcium to build bones and teeth.',
  zinc: 'Zinc supports the immune system and wound healing.',
  vitamin_a: 'Vitamin A supports vision, skin and the immune system.',
  vitamin_c: 'Vitamin C helps protect cells, supports the immune system and helps the body absorb iron from plant foods.',
  vitamin_d: 'Vitamin D helps the body absorb calcium for healthy bones.',
  vitamin_e: 'Vitamin E is an antioxidant that helps protect cells.',
  vitamin_k: 'Vitamin K helps blood clot normally.',
  folate: 'Folate is a B vitamin that helps the body make new cells, including red blood cells.',
  vitamin_b12: 'Vitamin B12 helps make red blood cells and keeps nerves healthy.',
  water: 'Water makes up much of the weight of fresh fruit and vegetables.',
}

export const UNIT_MEANING: Record<string, string> = {
  g: 'g = grams', mg: 'mg = milligrams (1/1,000 of a gram)', 'µg': 'µg = micrograms (1/1,000,000 of a gram)', kcal: 'kcal = kilocalories, the "calories" on food labels',
}

/** US FDA Daily Values (21 CFR 101.9(c), adults and children 4 years and older) in the unit given. */
export const FDA_DV: Partial<Record<Canon, [number, string]>> = {
  energy: [2000, 'kcal'], total_fat: [78, 'g'], saturated_fat: [20, 'g'], cholesterol: [300, 'mg'], sodium: [2300, 'mg'],
  carbohydrate: [275, 'g'], fibre: [28, 'g'], added_sugars: [50, 'g'], protein: [50, 'g'], vitamin_d: [20, 'µg'], calcium: [1300, 'mg'],
  iron: [18, 'mg'], potassium: [4700, 'mg'], vitamin_c: [90, 'mg'], vitamin_a: [900, 'µg'], magnesium: [420, 'mg'], folate: [400, 'µg'],
  vitamin_b12: [2.4, 'µg'], zinc: [11, 'mg'], phosphorus: [1250, 'mg'], vitamin_e: [15, 'mg'], vitamin_k: [120, 'µg'],
}
export const FDA_SOURCE = 'US FDA Daily Values (21 CFR 101.9), based on a 2,000 kcal diet'
export const FSA_SOURCE = 'UK FSA/DH front-of-pack criteria for foods, per 100 g'
export const EU_SOURCE = 'EU Regulation (EC) No 1924/2006 nutrition-claim conditions'
/** FSA per 100 g food: [low at or below, high above]. */
const FSA: Partial<Record<Canon, [number, number, string]>> = {
  total_fat: [3, 17.5, 'fat'], saturated_fat: [1.5, 5, 'saturated fat'], total_sugars: [5, 22.5, 'sugars'], salt: [0.3, 1.5, 'salt'],
}
export const GLANCE: Canon[] = ['energy', 'protein', 'carbohydrate', 'total_sugars', 'added_sugars', 'total_fat', 'saturated_fat', 'fibre', 'sodium', 'salt']

const UNIT_FACTOR: Record<string, number> = { 'g>mg': 1000, 'mg>g': 0.001, 'mg>µg': 1000, 'µg>mg': 0.001, 'g>µg': 1e6, 'µg>g': 1e-6, 'kj>kcal': 1 / 4.184 }
export function normUnit(u: string): string {
  const s = u.trim().toLowerCase()
  return ({ ug: 'µg', mcg: 'µg', 'μg': 'µg', gm: 'g' } as Record<string, string>)[s] ?? s
}
export function convert(v: number, from: string, to: string): number | null {
  const f = normUnit(from), t = normUnit(to)
  if (f === t) return v
  const k = UNIT_FACTOR[`${f}>${t}`]
  return k === undefined ? null : v * k
}

export function fmt(v: number): string {
  const a = Math.abs(v)
  if (a > 0 && a < 0.01) return 'less than 0.01' // a trace must not read as zero
  return a >= 100 ? String(Math.round(v)) : a >= 10 ? String(Math.round(v * 10) / 10) : String(Math.round(v * 100) / 100)
}

export type GlanceItem = { canon: Canon; label: string; unit: string; per100: number | null; perServing: number | null
  /** Value as printed when the basis (per 100 g or per serving) was not detected. */
  asPrinted: number | null; available: boolean; dvPercent: number | null; derived?: string }
export type Observation = { canon: Canon; level: 'high' | 'medium' | 'low' | 'source' | 'info'; text: string; standard: string }
export type Explanation = { glance: GlanceItem[]; observations: Observation[]; meanings: { canon: Canon; label: string; text: string; available: boolean }[]
  portion: string[]; notes: string[]; units: string[] }

const LABEL: Record<Canon, string> = {
  energy: 'Energy', protein: 'Protein', carbohydrate: 'Carbohydrate', total_sugars: 'Total sugars', added_sugars: 'Added sugars', fibre: 'Dietary fibre',
  total_fat: 'Total fat', saturated_fat: 'Saturated fat', trans_fat: 'Trans fat', cholesterol: 'Cholesterol', sodium: 'Sodium', salt: 'Salt',
  potassium: 'Potassium', calcium: 'Calcium', iron: 'Iron', magnesium: 'Magnesium', phosphorus: 'Phosphorus', zinc: 'Zinc', vitamin_a: 'Vitamin A',
  vitamin_c: 'Vitamin C', vitamin_d: 'Vitamin D', vitamin_e: 'Vitamin E', vitamin_k: 'Vitamin K', folate: 'Folate', vitamin_b12: 'Vitamin B12', water: 'Water',
}
const BASE_UNIT: Record<Canon, string> = {
  energy: 'kcal', protein: 'g', carbohydrate: 'g', total_sugars: 'g', added_sugars: 'g', fibre: 'g', total_fat: 'g', saturated_fat: 'g', trans_fat: 'g',
  cholesterol: 'mg', sodium: 'mg', salt: 'g', potassium: 'mg', calcium: 'mg', iron: 'mg', magnesium: 'mg', phosphorus: 'mg', zinc: 'mg', vitamin_a: 'µg',
  vitamin_c: 'mg', vitamin_d: 'µg', vitamin_e: 'mg', vitamin_k: 'µg', folate: 'µg', vitamin_b12: 'µg', water: 'g',
}

export function explainNutrition(input: ExplainInput): Explanation {
  // One value per canonical nutrient, converted to its base unit. The first source row wins; a listed-but-missing value stays null.
  const vals = new Map<Canon, { per100: number | null; perServing: number | null; asPrinted: number | null }>()
  for (const n of input.nutrients) {
    const c = canonical(n.key) ?? canonical(n.label)
    const prev = c ? vals.get(c) : undefined
    if (!c || (prev && (prev.per100 !== null || prev.perServing !== null || prev.asPrinted !== null))) continue
    const to = BASE_UNIT[c]
    const conv = (v: number | null) => (v === null || !Number.isFinite(v) ? null : convert(v, n.unit, to))
    vals.set(c, { per100: input.basis === 'per100g' ? conv(n.per100) : null, perServing: input.basis === 'unknown' ? null : conv(n.perServing),
      asPrinted: input.basis === 'unknown' ? conv(n.per100 ?? n.perServing) : null })
  }
  const notes: string[] = []
  // Salt from sodium (EU Regulation 1169/2011: salt = sodium x 2.5) when the source gives only sodium; flag labels whose two disagree.
  const na = vals.get('sodium'), salt = vals.get('salt')
  let saltDerived = false
  const has = (v?: { per100: number | null; perServing: number | null; asPrinted: number | null }) =>
    Boolean(v && (v.per100 !== null || v.perServing !== null || v.asPrinted !== null))
  if (has(na) && !has(salt)) {
    const s = (v: number | null) => (v === null ? null : (v / 1000) * 2.5)
    vals.set('salt', { per100: s(na!.per100), perServing: s(na!.perServing), asPrinted: s(na!.asPrinted) })
    saltDerived = true
  } else if (na && salt && na.per100 !== null && salt.per100 !== null && na.per100 > 0) {
    const expected = (na.per100 / 1000) * 2.5
    if (Math.abs(salt.per100 - expected) / expected > 0.25) {
      notes.push(`The salt (${fmt(salt.per100)} g) and sodium (${fmt(na.per100)} mg) values do not match the usual conversion (salt ≈ sodium × 2.5). Both are shown as given; check the label.`)
    }
  }

  const portionKnown = input.servingGrams !== null || input.basis === 'perServing'
  const glance: GlanceItem[] = GLANCE.map((c) => {
    const v = vals.get(c)
    const dv = FDA_DV[c]
    const perServing = v?.perServing ?? null
    return { canon: c, label: LABEL[c], unit: BASE_UNIT[c], per100: v?.per100 ?? null, perServing, asPrinted: v?.asPrinted ?? null,
      available: has(v),
      dvPercent: dv && perServing !== null && portionKnown ? Math.round((perServing / dv[0]) * 100) : null,
      derived: c === 'salt' && saltDerived ? 'Calculated from sodium (salt ≈ sodium × 2.5)' : undefined }
  })

  const observations: Observation[] = []
  const p100 = (c: Canon) => vals.get(c)?.per100 ?? null
  if (input.basis === 'per100g' && !input.liquid) {
    for (const [c, [low, high, word]] of Object.entries(FSA) as [Canon, [number, number, string]][]) {
      const v = p100(c)
      if (v === null) continue
      const unit = BASE_UNIT[c]
      if (v > high) observations.push({ canon: c, level: 'high', standard: FSA_SOURCE,
        text: `High in ${word}: ${fmt(v)} ${unit} per 100 g (more than ${high} ${unit}).` + (c === 'salt' ? ' Consider your overall daily intake.' : '') })
      else if (v <= low) observations.push({ canon: c, level: 'low', standard: FSA_SOURCE, text: `Low in ${word}: ${fmt(v)} ${unit} per 100 g (${low} ${unit} or less).` })
      else observations.push({ canon: c, level: 'medium', standard: FSA_SOURCE, text: `Medium ${word}: ${fmt(v)} ${unit} per 100 g (between ${low} and ${high} ${unit}).` })
    }
    const fib = p100('fibre'), pro = p100('protein'), kcal = p100('energy')
    if (fib !== null && fib >= 3) observations.push({ canon: 'fibre', level: 'source', standard: EU_SOURCE,
      text: fib >= 6 ? `Provides dietary fibre: ${fmt(fib)} g per 100 g meets the "high fibre" condition (6 g or more).`
        : `Provides dietary fibre: ${fmt(fib)} g per 100 g meets the "source of fibre" condition (3 g or more).` })
    if (pro !== null && kcal !== null && kcal > 0) {
      const share = (pro * 4) / kcal
      if (share >= 0.12) observations.push({ canon: 'protein', level: 'source', standard: EU_SOURCE,
        text: `Provides protein: about ${Math.round(share * 100)}% of its energy comes from protein, which meets the "${share >= 0.2 ? 'high protein' : 'source of protein'}" condition (${share >= 0.2 ? '20' : '12'}% or more).` })
    }
  } else if (input.basis === 'per100g' && input.liquid) {
    notes.push('This looks like a drink. Front-of-pack criteria for drinks are set per 100 ml and differ from those for foods, so no low/medium/high comparison is shown.')
  } else {
    notes.push('The values are not known to be per 100 g, so they are not compared with reference criteria.')
  }
  if (input.naturalSugars && p100('total_sugars') !== null) {
    observations.push({ canon: 'total_sugars', level: 'info', standard: 'Food type',
      text: 'The sugars in whole fresh fruit and vegetables occur naturally; they are not added sugars.' })
  }

  const portion: string[] = []
  if (portionKnown) {
    const size = input.servingGrams !== null ? `${fmt(input.servingGrams)} g` : 'one serving'
    const say = (c: Canon, verb: string) => {
      const g = glance.find((x) => x.canon === c)
      if (!g || g.perServing === null) return
      portion.push(`${size} ${verb} ${fmt(g.perServing)} ${g.unit} of ${LABEL[c].toLowerCase()}` + (g.dvPercent !== null ? ` (${g.dvPercent}% of the Daily Value).` : '.'))
    }
    const e = glance.find((x) => x.canon === 'energy')
    if (e?.perServing != null) portion.push(`${size} provides about ${fmt(e.perServing)} kcal` + (e.dvPercent !== null ? ` (${e.dvPercent}% of a 2,000 kcal day).` : '.'))
    say('protein', 'provides'); say('fibre', 'provides'); say('total_sugars', 'contains'); say('saturated_fat', 'contains'); say('sodium', 'contains')
    if (glance.some((g) => g.dvPercent !== null)) notes.push(`Daily Value percentages use ${FDA_SOURCE}. They are a general reference for labels, not a personal target.`)
    if (input.servingGrams !== null && input.basis === 'per100g') notes.push(`Portion values are scaled from the per-100 g values to the ${fmt(input.servingGrams)} g you entered; they are an estimate, not a measurement of your food.`)
  } else {
    notes.push('Enter a serving size in grams to see what your portion provides. SmartPlateAI cannot measure the weight of food from a photo.')
  }

  const meanings = [...vals.keys()].filter((c) => MEANING[c]).map((c) => ({
    canon: c, label: LABEL[c], text: MEANING[c], available: has(vals.get(c)) }))
  const units = [...new Set(input.nutrients.map((n) => normUnit(n.unit)))].filter((u) => UNIT_MEANING[u]).map((u) => UNIT_MEANING[u])
  return { glance, observations, meanings, portion, notes, units }
}
