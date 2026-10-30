# Real-world evaluation plan (phone photos)

Dataset metrics (food classifier 92.0% top-1, freshness head 95.1%) come from public dataset photos. They do **not**
show how SmartPlateAI performs on your own phone photos. This plan measures that. Until it has been run on photos you
took, real-world accuracy is **unverified**.

## 1. Rules

- **Take new photos for the evaluation.** Do not reuse training or validation images, or photos you have already used
  to adjust thresholds or code.
- **Keep two sets: tuning and evaluation.** If a result leads you to change something, re-test on fresh photos. Never
  report results on the photos you tuned on.
- **Write the label down when you take the photo** (folder name = what the food really is), never after seeing the
  app's answer.
- **Report counts with the sample size.** With 20 photos per group, one error moves the result by 5 points. Treat
  small groups as indicative only.

## 2. Folder layout (used by `backend/scripts/evaluate_real_photos.py`)

```
D:\SmartPlateAI\real_eval\
  recognition\<true food name>\*.jpg      e.g. recognition\Apple\, recognition\Milk\, recognition\Paneer\, recognition\Masala dosa\
  freshness\<food>\fresh\*.jpg            only the 14 freshness foods are scored
  freshness\<food>\rotten\*.jpg
  nutrition_expected.csv                  optional: expected_food,expected_record  (the USDA record you expect)
```

`nutrition_expected.csv` example:

```
expected_food,expected_record
Milk,"Milk, NFS"
Paneer,"Cheese, paneer"
Dosa,"Dosa, plain"
```

## 3. What to photograph

| Set | Content | Suggested minimum |
|---|---|---|
| Recognition: 24 model classes | each class once on a plain background, once on a busy background or in a mixed meal, once in dim light | 3–5 per class (72–120) |
| Recognition: lookalikes | taco vs taquito, burger vs sandwich, hot dog, fries; tomato vs red bell pepper; potato vs baked potato | 5 per class |
| Recognition: outside the 24 classes | milk (glass, steel tumbler), paneer cubes, curd/dahi, rice (cooked), dal, roti/chapati, idli, plain and masala dosa, egg (boiled, fried), onion, kiwi, a beverage | 3–5 each |
| Multiple foods | thali or plate with 2–4 foods | 10 |
| Not food | phone, keys, an empty plate, a hand | 10 |
| Freshness | each of the 14 freshness foods: clearly fresh, visibly rotten, and borderline (bruised, overripe) | 5 fresh + 5 rotten per food you can obtain |
| Packaged (manual, section 5) | known product (in local dataset), unknown product, barcode close-up, unreadable/crumpled label, front only | 5 each |

For each photo, vary the phone, distance (close-up vs whole plate) and light (daylight, tube light, evening).

## 4. Run

```powershell
cd D:\SmartPlateAI\backend
# 1) Baseline: image model only (no external AI)
.\.venv\Scripts\python.exe scripts\evaluate_real_photos.py D:\SmartPlateAI\real_eval --image-model-only
# 2) Full pipeline with the configured providers (OpenAI, else Gemini); --delay respects provider rate limits
.\.venv\Scripts\python.exe scripts\evaluate_real_photos.py D:\SmartPlateAI\real_eval --delay 4
```

Each run writes `results_<time>.csv` (one row per photo: expected label, outcome, predicted food, source and provider,
image-model score, confirmation flag, freshness status and model confidence, nutrition record, photo quality, time and
a failure note) and `summary_<time>.json`.

## 5. What to report

- **Recognition (24 classes and others separately):**
  - correct and accepted automatically
  - **wrong but accepted without asking** (the most important failure)
  - asked to confirm
  - not identified
  - median time
- **Outside the 24 classes:** how often the food was named correctly; how often it was wrongly reported as one of the
  24 classes. The second should be close to zero when OpenAI or Gemini is available.
- **Freshness** (the 14 foods only):
  - accuracy on fresh vs rotten, and the confusion between them
  - how borderline photos were labelled
  - whether every rotten-labelled result showed the "do not eat" warning
- **Nutrition:**
  - share of identified foods whose USDA record is the right food and preparation (manual check, or
    `nutrition_expected.csv`)
  - share with an honest "no match / be more specific" message
- **Packaged** (manual, using the Scan packaged food page): for each pack, whether the product was identified, whether
  the nutrition came from the right product or the label in the photo, and that no other product's values were shown.
  Record barcode/text mismatches and unreadable labels.

## 6. Known limits to keep in mind

- The image-model score is not a probability. On held-out test images, scores of 70–80% were right about 65% of the
  time.
- Freshness is a visual estimate for 14 produce foods only. It cannot detect microbes, toxins or internal rot.
- Nutrition values are reference values per 100 g for the type of food, not measurements of the photographed portion.
