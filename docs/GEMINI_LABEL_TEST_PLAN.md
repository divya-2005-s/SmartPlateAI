# Test plan: Gemini package-label reading on real photos (NOT RUN, awaiting approval)

Status: prepared 2026-10-27. No Gemini or OpenAI request has been made for this test. It runs only after explicit approval.

## What is tested
Whether the Gemini fallback label reader (`gemini_vision.read_package`, same prompt, schema and validation as the OpenAI
reader) reads real package photos correctly, and whether the app's merge rules keep wrong values off the screen.
Until now this path has only been tested with mocked replies.

## Exact inputs
`backend/data_eval/packaged/` (Open Food Facts, CC BY-SA 3.0; list and source pages in `MANIFEST.json`): 29 products,
12 + 14 Indian (barcodes 890…) and 3 European. Per product the app sends **two images in one request**: `front.jpg`
(the front of the pack) and `nutrition.jpg` (the nutrition table, as the "back" image). `ingredients.jpg` goes to Tesseract
only (close-up field), never to Gemini. Images are re-encoded as JPEG at most 2048 px on the long side, without EXIF data.

Recommended exclusion: `8901764042270` (Thums Up): its "front" photo is an advertisement showing a person. Running
without it gives 28 products.

## Number of requests
- One `generateContent` request per product: **28** (or 29).
- A request is repeated on the second configured model only if the first answers "busy" or "model unavailable", so the
  hard maximum is **2 per product = 56**.
- OpenAI is switched off for the run (`OPENAI_VISION_ENABLED=false`, process environment only), so no OpenAI request is
  made. Google Vision and the chatbot are not involved. `.env` is not changed.

Command (once approved):
```powershell
cd D:\SmartPlateAI\backend
$env:OPENAI_VISION_ENABLED="false"; $env:PYTHONIOENCODING="utf-8"
.\.venv\Scripts\python.exe scripts\eval_packaged_labels.py --allow-ai-readers --out ..\docs\gemini_label_eval_RESULT.json
```
(The script uses a throw-away database, so the run writes nothing into `backend/data`.)

## Expected information returned
Per product, the validated `package_reading`: brand, product name, variant, net quantity, claims (front); ingredients
text, serving size, nutrition rows (name, amount, unit, column basis such as "per 100 g" or "per serving"), allergen
statements, additives, manufacturer, warnings (back); and same_product yes/no/unclear.

## Cost
Pricing source: Google AI for Developers, "Gemini Developer API pricing" (https://ai.google.dev/gemini-api/docs/pricing),
read on 2026-10-27. Paid tier, **Gemini 3.1 Flash-Lite**: $0.25 per 1M input tokens (text/image), $1.50 per 1M output
tokens (including thinking). The free tier lists the same model as free of charge.
Image tokens (https://ai.google.dev/gemini-api/docs/image-understanding): 258 tokens per 768×768 tile; a 2048 px photo
is at most about 8 tiles (≈2,100 tokens). For Gemini 3 models a `media_resolution` setting caps tokens per image; its
default levels are not listed on that page, so the figure below is an estimate.

| per request (upper estimate) | tokens | cost |
|---|---|---|
| input: 2 images + prompt | ≤ 4,700 | ≤ $0.0012 |
| output: JSON + thinking | ≤ 3,000 | ≤ $0.0045 |
| **total** | | **≤ ~$0.006** |

**Whole test: about $0.05 typical, under $0.20 worst case for 28 requests (under $0.35 even if all 56 retries happened)**
on the paid tier; $0 on the free tier. The real token counts are in each response's `usageMetadata` and will be reported.

## Privacy
- The photos are public Open Food Facts images of products (no personal data), except the excluded Thums Up advert.
- Google states that on the **free tier**, content may be used to improve its products. On the paid tier it is not.
  Which tier the configured key uses cannot be seen from the code; check it in Google AI Studio before approving.
- The API key stays in the backend environment; it is sent in a request header and never logged.

## How results are compared
`eval_packaged_labels.py` compares every nutrient the app *shows* (after merging Gemini with Tesseract) against Open Food
Facts' contributor-entered per-100 g values: "correct" = within 5 % or 0.5 units, "wrong", "missing", or "shown on a
different/unknown basis". It also reports Gemini's own reading (`ai_value`) separately from the merged result, the
identified product, barcode, ingredients-text recall, and every warning. OFF values are crowd-sourced; any "wrong" value
will be checked by eye against the photo before it is counted as an app error.

Baseline to beat (Tesseract only, same photos, measured 2026-10-27): see `docs/PACKAGED_EVALUATION.md`.

## Success and failure criteria
Success (all required):
1. No value is shown under the wrong column basis (for example per-100 g numbers shown as per serving).
2. Wrong values shown ≤ 3 % of the compared reference values, each one explained after checking the photo.
3. At least 50 % of reference values on per-100 g labels are shown correctly.
4. No value is shown for a nutrient the label does not print (no invented values).

Failure (any): an invented value; a wrong basis shown without a warning; > 3 % wrong values; a request that sends anything
other than the two images and the prompt.

If it fails, Gemini label reading stays available only behind its switch, and the result is reported as is.
