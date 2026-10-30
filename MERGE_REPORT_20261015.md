# SmartPlateAI improvement merge report

Inspection date: 2026-10-15

## Project comparison

The source folder `D:\new\SmartPlateAI_freshness_nutrition_packaged` is a partial patch, not a complete project: it contains only `backend` and `frontend`, 23 files totaling approximately 0.36 MB. It has no databases, datasets, trained models, environment files, frontend manifests, or lockfiles. The destination contains the full application and persistent data.

The destination inventory contains 41,508 files (approximately 2.12 GB), including SQLite databases, model files, datasets, backups, the Python environment, and frontend dependencies. A full backup was created at `D:\SmartPlateAI_MergeBackup_20261015_151918` before this report or any merge changes. Robocopy copied all 41,508 files (2.121 GB); source and backup file counts match.

## Source-to-destination file comparison

The source contributes six paths not present in the destination:

- `backend/app/ml/condition.py`
- `backend/app/ml/condition_eval.py`
- `backend/app/ml/image_quality.py`
- `backend/scripts/check_image_quality.py`
- `backend/scripts/evaluate_condition_model.py`
- `backend/tests/test_freshness_nutrition_quality.py`

The following 17 paths exist in both projects but differ:

- Backend: `app/api/routes/analyze.py`, `app/api/routes/packaged.py`, `app/services/barcode_cv.py`, `app/services/nutrition.py`, `app/services/ocr.py`, `app/services/openai_vision.py`, `app/services/packaged.py`, `requirements.txt`, `tests/conftest.py`, `tests/test_packaged_recognition.py`, and `tests/test_recognition_packaged_history_fixes.py`.
- Frontend: `src/components/AnalysisExtras.tsx`, `src/components/CameraCapture.tsx`, `src/components/FoodAnalyzer.tsx`, `src/components/PackagedAnalyzer.tsx`, `src/lib/foodApi.ts`, and `src/lib/packagedApi.ts`.

No destination-only path is proposed for deletion. The source has no frontend manifest or lockfile to merge.

## Relevant existing destination behavior to preserve

- The destination already has a separate `app/ml/freshness.py` logistic head wired to food-recognizer embeddings. It is not interchangeable with the proposed food-independent condition classifier.
- The destination already has expanded packaged-product data matching, OCR/AI label reading, Open Food Facts integration, barcode lookup, authenticated history, allergen handling, user correction, and a frontend packaged scanner.
- The destination nutrition loader currently keeps the first exact-spelling row for each food, making values dependent on CSV row order and freshness-associated records. The source adds case-insensitive normalization and deterministic majority-FDC selection with conflict diagnostics; merge that implementation to remove this inconsistency.
- Existing authentication, SQLite data, model files, datasets, Gemini/OpenAI/USDA configuration, and package/environment manifests must remain untouched unless a compatibility need is demonstrated.

## Merge assessment and intended scope

- Add the source's condition-classifier and image-quality modules and compatible evaluation/diagnostic scripts and tests. The condition model must remain disabled unless its evaluated configuration and SHA-256-matched model are present; no model or evaluation artifact is copied from source.
- Integrate measured quality, conservative enhancement, and condition assessment into the existing `/api/analyze/food` contract while retaining destination OpenAI/Google Vision checks, confirmation flow, history, and user-entered food support. Poor-quality photos must not produce an accepted food prediction or nutrition.
- Merge the source's deterministic nutrition-reference implementation and verify regression coverage for food-name normalization and freshness-independent nutrition without overwriting existing FDC data or changing values based on freshness.
- Merge source packaged-recognition safeguards and optional close-up image support into existing routes/services and frontend types/UI only where compatible. Preserve destination matching, Open Food Facts, candidate selection, and manual re-search flows; reject generic-only product matches.
- Retain current OCR/barcode code unless source changes have a verified benefit and no regression to existing API behavior. OpenCV is optional in the source; dependency changes and installation are not assumed.
- Merge camera framing guidance and file-input fallback while preserving the existing upload path and mobile rear-camera behavior.

## Protected items and dependencies

No source environment file, database, model, data, credential, or dependency lockfile exists. The destination's `.env`, databases, trained models, dataset files, existing frontend manifest/lockfile, and Python environment are protected. Disk space at inspection: D: had approximately 290.99 GB free; C: had approximately 2.08 GB free. No dependency installation is planned without a demonstrated need.

## Completed merge and validation

### Added files

- `backend/app/ml/condition.py`
- `backend/app/ml/condition_eval.py`
- `backend/app/ml/image_quality.py`
- `backend/scripts/check_image_quality.py`
- `backend/scripts/evaluate_condition_model.py`
- `backend/tests/test_freshness_nutrition_quality.py`

### Modified files

- Backend: `app/api/routes/analyze.py`, `app/api/routes/packaged.py`, `app/services/barcode_cv.py`, `app/services/nutrition.py`, `app/services/ocr.py`, `app/services/openai_vision.py`, `app/services/packaged.py`, `tests/conftest.py`, and `tests/test_packaged_recognition.py`.
- Frontend: `src/components/AnalysisExtras.tsx`, `src/components/CameraCapture.tsx`, `src/components/FoodAnalyzer.tsx`, `src/components/PackagedAnalyzer.tsx`, `src/lib/foodApi.ts`, and `src/lib/packagedApi.ts`.

`backend/tests/test_recognition_packaged_history_fixes.py` was deliberately retained from the destination. A source test version conflicted with the destination's supported manual-food-entry behavior. The destination's existing user-entry behavior and tests were preserved.

### Integration decisions and dependencies

- Food quality assessment and freshness are separate from food identity. Poor-quality input is reported for retake rather than treated as a reliable accepted prediction. The existing food-independent condition model remains evaluation- and model-hash-gated; no model was copied, trained, or automatically activated.
- Nutrition selection is deterministic for normalized food names and does not vary with freshness.
- Packaged recognition retains the destination's OFF lookup, local product data, history, manual search, and confirmation. Brand-only evidence can produce uncertain candidates but cannot automatically identify a product. Ingredient OCR does not supply variant identity when front-of-pack evidence is available.
- Packaged scans accept front, back, and optional close-up photos. The endpoint retains its legacy `images` response shape when no close-up is provided; it includes `closeup: true` only when a close-up was actually sent.
- The existing food and packaged upload flows remain. Camera capture includes framing guidance and keeps file upload as a fallback. Quality feedback and a retake action are shown for food photos when the response contains quality metadata.
- No dependency manifests or lockfiles were changed and no packages were installed. OpenCV is not installed in the destination environment; OCR and barcode processing keep their non-OpenCV fallbacks.
- No `.env`, credential, database, model, dataset, authentication data, Gemini/USDA integration, or destination-only file was overwritten or deleted. The source's `requirements.txt` was not copied because OpenCV remains optional and the current implementation has a fallback.

### Validation results

- Targeted freshness/nutrition and packaged regressions: **56 passed**.
- Full backend suite, from `D:\SmartPlateAI\backend`: **238 passed, 1 skipped**. One existing Keras input-structure warning was emitted by `tests/test_real_model.py`.
- Frontend production build, from `D:\SmartPlateAI\frontend`: **passed** (`tsc -b && vite build`).
- FastAPI import: **passed** (`from app.main import app`).
- Live local startup and HTTP check: **passed** (`uvicorn app.main:app`; `/openapi.json` returned HTTP 200).
- No actual food or Maggi package photos were supplied or tested. Synthetic regression images and mocked OCR validate code behavior, not real-world recognition accuracy.

## Restart commands

Backend (from `D:\SmartPlateAI\backend`):

```powershell
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 0.0.0.0 --port 8000
```

Frontend (from `D:\SmartPlateAI\frontend`):

```powershell
npm run dev
```
