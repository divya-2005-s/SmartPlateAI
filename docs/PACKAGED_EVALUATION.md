# Packaged food, false food claims and label reading: offline evaluation (2026-10-27)

All numbers below were measured on this machine with the production models, **without any paid provider** (OpenAI, Gemini
and Google Vision switched off for the evaluation process only; `.env` unchanged) and with throw-away databases. They show
the image model and the app's rules on their own, which is the worst case: when a provider answers, it can verify or correct
the result. Small sets: treat every rate as an estimate, not a guarantee.

Reproduce:
```powershell
cd D:\SmartPlateAI\backend
.\.venv\Scripts\python.exe scripts\eval_food_gate.py --api --out gate.json      # food / non-food / package decisions, end to end
.\.venv\Scripts\python.exe scripts\eval_packaged_labels.py --out labels.json   # label reading (Tesseract only)
```

## Evaluation data (all real photos; licences and sources listed next to the images)

| Set | n | Source | Correct outcome |
|---|---|---|---|
| supported_test | 360 | held-out test photos of the 24 classes (15 per class) | the right food |
| food_in_context | 12 | Openverse (CC0/PD/CC BY), people holding/eating supported foods | food, not rejected |
| food_with_packaging | 2 | Openverse: pizza in open boxes, donuts in an open box | food, not rejected |
| unsupported_food | 21 | Openverse: sushi, curry, cake, … | food (unsupported), not rejected |
| packaged_food | 29 | Open Food Facts package fronts (26 Indian, 3 European) | no food claim; route to label scanner |
| food_packaging_closed | 5 | Openverse: closed pizza boxes, donut boxes, potato sacks | no food claim |
| non_food | 64 | Openverse: people, phones, laptops, shoes, vehicles, scenery, … | not food |
| non_food_packaged | 27 | Openverse: medicine, cosmetics, toiletries, detergent, electronics boxes | not food |

Every image was reviewed by eye; mislabelled search results were removed or moved (for example, most "food with packaging"
results showed closed packaging and were moved to food_packaging_closed).
**Limitations of the data:** only 2 photos of food visible together with its packaging; 29 packaged products; no
photos of multiple foods in one image beyond the food_in_context set.

## Why packaged products were mishandled (root causes)

1. The 24-class model always names one of its 24 foods; a yellow chips packet is closest to "Fries" (98 % score). The score
   is not a probability and cannot say "this is not one of my classes".
2. The independent ImageNet signal sees no food in most package fronts (food mass below the calibrated floor), so the
   existing non-food gate called 18 of 29 package fronts "not food".
3. The gate requires two signals to agree before rejecting, so a package that is visually close to a class (Lay's -> Fries)
   was accepted with that food's nutrition.

## Decision strategy (implemented)

Signals kept separate: **food presence** (ImageNet food mass vs the existing calibrated floor), **packaging presence**
(ImageNet's top-1 class belongs to a generic container group: packet, carton, bottles, jugs, cans, bags, shop shelves),
**food identity** (24-class model), **label text** (only in the packaged scanner). No new numeric threshold was added; the
container group is fixed by ImageNet class meanings (`app/ml/imagenet_groups.py`), not tuned on these photos.

Applied only when **no vision provider identified anything** (a provider's answer, including "no food", always wins):
- **A. Package without food evidence** (container top-1 and food mass below the floor) -> `PACKAGED_PRODUCT`: "This looks
  like a packaged product … use Scan packaged food". No food name, nutrition or freshness; never counted as food.
  Specific non-food products (pill bottle, lotion, perfume, phone, books, …) are a separate group and are never routed.
- **B. Weak food evidence** (the 24-class model accepted a food, nothing verified it, food mass below the floor) ->
  `LOW_CONFIDENCE` with reason `weak_food_evidence`: the guess is offered for confirmation, its nutrition is not shown,
  and it is **not** turned into "non-food".

## End-to-end results (POST /api/analyze/food, providers off)

| Set | Before | After |
|---|---|---|
| non_food (64): shown as a food | 2 (phone, living room -> "Donut") | **0** |
| non_food_packaged (27): shown as a food | 3 (cosmetics, 2 electronics boxes) | **0** |
| packaged_food (29): shown as a food (false claim) | 2 (Lay's -> Fries, a second chips packet -> Fries) | **1** (the second packet: ImageNet food mass 0.115, above the floor) |
| packaged_food (29): "not food" | 18 | **8** |
| packaged_food (29): routed to the label scanner | 0 | **16** |
| food_packaging_closed (5): food claimed | 0 | 0 (3 routed to the scanner, 2 "not food") |
| non_food_packaged (27): routed to the label scanner (no food claimed, but a misleading suggestion) | 0 | 4 |
| supported_test (360): shown with the correct food | 280 | 267 |
| supported_test: **extra confirmation of a correct result** | 0 | **13** (11 weak evidence, 2 routed: a hot dog and a taquito in wrappers) = 3.6 % of photos, 4.5 % of shown results |
| supported_test: shown with a wrong food | 12 | 12 |
| supported_test / food_in_context / unsupported: called "not food" | 4 / 0 / 1 | 4 / 0 / 1 (unchanged) |
| food_with_packaging (2): called "not food" | 1 | 1 (unchanged; open pizza boxes, the model sees no food) |

False food claims across all non-food and packaged sets: **7 of 125 -> 1 of 125**. Cost: 13 correct food photos of 360 need
one confirmation click when no provider is available; with a working provider these are verified automatically.

## Packaged-label reading (Tesseract only, 29 products, 213 reference values from Open Food Facts)

| | Before (session start) | After |
|---|---|---|
| Values shown and correct | 3 | **6** |
| Values shown and wrong vs OFF | 3 | 2 |
| … of which genuine app errors after checking the photo | 2 (330 g and 4.5 g "sugar" read from ingredient lists) | **0** |
| Missing | 191 | 187 |
| Shown under another/unknown basis (not compared) | 16 | 18 |

The 2 remaining mismatches were checked against the photos: the label prints the value the app read (Thums Up: 42 kcal per
100 ml; Sting: sugars 7 g), so the Open Food Facts entries differ from these packs. Root causes fixed: the parser read
ingredient lists after the nutrition table, took numbers belonging to the next field ("SODIUM: … B3: 1.9mg"), read only one
value per line, and showed physically impossible per-100 g values with only a flag. A "per serve" heading merged into the
serving-size line no longer decides the column basis.
**Honest summary:** Tesseract alone reads very few values from real phone photos (6 of 213); the app now shows almost
nothing wrong, but packaged nutrition mostly stays missing unless an AI reader or a product database supplies it.
Barcode decoded: 3/29; product identified: 5/29.

## What would need approval

1. **Gemini label reading test** (28-29 paid requests, < $0.20): see `GEMINI_LABEL_TEST_PLAN.md`.
2. **Better package / food-with-packaging recognition** would need a model change, which was not done. Data required for a
   defensible version: at least ~300 labelled photos each of packaged foods (front, varied lighting/angles), non-food
   packages (medicine, cosmetics, toiletries, electronics), food together with its packaging, and plain food; split by
   product so the same pack never appears in training and test. Option: a small "food / packaged food / other" head on the
   existing MobileNetV2 features (no new download), trained and evaluated like the freshness head.
3. **Specific sandwich types (e.g. paneer)**: the 24-class model has one "Sandwich" class and cannot tell fillings apart.
   Distinguishing them needs labelled photos per type (≥ 150-200 each for paneer, vegetable, cheese, chicken, egg, …),
   and either retraining the classifier or a separate sandwich-type head evaluated on held-out photos. Until then the app
   asks the user to choose the type (implemented earlier) and Gemini, when allowed, can name it.
4. **Rule B (weak evidence)** is a policy choice with the measured cost above. It can be removed by deleting one branch in
   `analyze.py` if you prefer fewer confirmations over fewer false food claims.
