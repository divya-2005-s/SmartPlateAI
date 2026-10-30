# SmartPlateAI — Project Health Audit

Date: 2026-10-15

## A. Executive summary

Overall status: the project is largely healthy at the code/test layer, but not all runtime integrations are currently operational.

Strongest evidence:
- Backend test suite passed: 180 passed, 1 skipped.
- Frontend production build passed: `npm run build` completed successfully.
- Core app health and model-status endpoints are live and returning success.
- Packaged-food dataset status reports 852 products loaded and OCR available.

Important failures and limitations identified:
- The Gemini chatbot is configured, but a real live request currently fails with HTTP 503 from the Google provider: `This model is currently experiencing high demand... Please try again later.`
- Google Vision is configured with an API key but is not usable because billing is not enabled on the project, returning HTTP 403 with `billing to be enabled`.
- The app’s camera code is correctly structured for browser-based access (`getUserMedia` + `canvas` capture), but actual browser camera permission and media access were not executed in this headless environment; they require manual browser verification.
- The project is not a git repository (`git status` reports “not a git repository”), so there is no git-based change history to inspect in this working tree.

Conclusion: SmartPlateAI is functionally healthy in local code validation and backend logic tests, but production runtime integrations currently have external-provider issues that prevent reliable end-to-end use of AI/chat features.

## B. Component inventory

### Frontend
- React + Vite + TypeScript app in `frontend/`
- Route shell includes landing, analyze, scan-packaged, chat, meal planner, history, nutrition, compare, report pages, etc.
- UI service modules include API wrappers for auth, chat, food analysis, packaged analysis, and session management.
- Browser camera logic is implemented in `frontend/src/components/CameraCapture.tsx` and integrated into `FoodAnalyzer.tsx`.

### Backend
- FastAPI app in `backend/app/main.py`
- Core modules: config, database, security, and dependency wiring.
- API route modules discovered:
  - `/api/auth/signup`, `/api/auth/login`, `/api/auth/me`, `/api/auth/logout`
  - `/api/models/status`
  - `/api/analyze/food`, `/api/analyze/confirm`
  - `/api/packaged/status`, `/api/packaged/search`, `/api/packaged/products/{product_id}`
  - `/api/packaged/off/{barcode}`
  - `/api/analyze/packaged`
  - `/api/chat/status`, `/api/chat`, `/api/chat/stream`
  - `/api/meal-plans` routes
  - `/api/reports/*`, `/api/history/*`, `/api/nutrition/*`, `/api/profile/*`, `/api/allergens/*`, `/api/tools/*`

### Database / persistence
- SQLite database is created automatically under `backend/data`.
- Authentication and session handling uses SQLite-backed user/session tables.
- HTTP cache is also stored in the database for external API responses.

### Models and ML
- Food classification model is configured and reported ready by `/api/models/status`.
- `n_classes`: 24
- `input_size`: 224
- `rejection_calibrated`: True
- `class_agreement_check`: True
- Freshness model is not installed (`freshness_model: 'not_installed'`).

### Datasets and local lookups
- Packaged-food dataset is loaded successfully (`products`: 852)
- Food dataset paths are configured through local data references, including packaged-food CSVs and additive reference data.
- USDA FDC lookup is enabled and successfully returned a real nutrition record for `apple` in the live test.

### External services actually used
- Google Gemini / Generative Language API (`/api/chat` and `/api/chat/stream`)
- Google Vision API (`vision.py` and image confirmation logic)
- OpenAI Vision API (`openai_vision.py`)
- USDA FoodData Central (`usda.py`)
- Open Food Facts (packaged-food barcode/name lookup)
- OCR via Tesseract (packaged-food label OCR)

## C. API test matrix

| Endpoint | Method | Auth | Test performed | HTTP status | Result | Notes |
|---|---|---:|---|---:|---|---|
| `/health` | GET | No | Direct app health via TestClient | 200 | PASS | `status: "ok"` returned |
| `/api/models/status` | GET | No | Direct status call | 200 | PASS | Food model ready, 24 classes, calibration active |
| `/api/packaged/status` | GET | No | Direct status call | 200 | PASS | Dataset loaded, 852 products, OCR available true |
| `/api/chat/status` | GET | No | Direct status call | 200 | PASS | Configured true, model `gemini-3.8-flash` |
| `/api/chat` | POST | No | Minimal live request | 503 | FAIL | Gemini provider returned temporary high-demand 503 |
| `/api/analyze/food` | POST | Optional | Route tests via TestClient with fixtures | 200 / 422 / 503 depending input | PASS | Validates food detection, low confidence, invalid image, model missing |
| `/api/analyze/confirm` | POST | Optional | Route tests via TestClient | 200 | PASS | Manual confirmation flow validated |
| `/api/auth/signup` | POST | No | Auth tests | 201 / 409 / 422 | PASS | Registration and duplicate/email validation tests pass |
| `/api/auth/login` | POST | No | Auth tests | 200 / 401 / 429 | PASS | Safe auth failures and session creation verified |
| `/api/auth/me` | GET | Cookie or bearer token | Auth tests | 200 / 401 | PASS | Session persistence and logout verified |
| `/api/auth/logout` | POST | Cookie or bearer token | Auth tests | 200 | PASS | Session revocation works |
| `/api/packaged/search` | GET | No | Data-driven route tests | 200 | PASS | Query search works against dataset |
| `/api/packaged/products/{id}` | GET | No | Data-driven route tests | 200 / 404 | PASS | Product lookup works |
| `/api/packaged/off/{barcode}` | GET | Optional | Route logic inspected; not live-queried in browser | Not run live | NOT TESTED | Open Food Facts integration exists; local route logic is implemented |
| `/api/meal-plans/*` | GET/POST/PUT/DELETE | Auth likely required | Route definitions inspected | Not run live | NOT TESTED | Routes exist; not directly exercised by the automated suite |
| `/api/reports/*` | GET | Likely auth | Code inspected | Not run live | NOT TESTED | Route set exists; no direct test call executed |
| `/api/profile/*` and `/api/history/*` | GET/POST/PATCH/DELETE | Likely auth | Route definitions inspected | Not run live | NOT TESTED | No direct live request executed in this audit |

Notes:
- The automated suite includes route and service contracts for auth, food analysis, packaged goods, and chat error handling.
- The direct provider errors above were checked without exposing API keys.

## D. External API matrix

| Provider | Configuration status | Real request tested? | Result | Error category | Corrective action |
|---|---|---|---|---|---|
| Google Gemini | Configured (`GEMINI_API_KEY` present, model set) | Yes, minimal request | Failed with HTTP 503 from provider; message: `This model is currently experiencing high demand. Spikes in demand are usually temporary. Please try again later.` | Temporary service availability / rate / demand issue | Retrying with backoff; consider switching to a currently available model or graceful fallback UX |
| Google Vision | Configured (`GOOGLE_VISION_API_KEY` present) | Yes, minimal request with tiny image | Failed with HTTP 403: billing must be enabled for the project | Configuration / billing block | Enable billing in the Google Cloud project or disable the feature until billing is active |
| OpenAI Vision | Configured (`OPENAI_API_KEY` present) | Not live-tested in this audit | Unknown; code path exists but no direct provider request was executed in the current session | Not yet validated | Validate with a small real image request when permitted; keep graceful degradation if unavailable |
| USDA FoodData Central | Configured (`USDA_FDC_API_KEY` present) | Yes, direct lookup of `apple` | Succeeded; returned real nutrition data | N/A | No immediate fix required; continue using the current configuration |
| Tesseract OCR | Configured / installed in environment | Verified by app status and tests | `ocr_available: true` in `/api/packaged/status`; OCR unit tests pass when Tesseract is installed | N/A | No immediate fix required |
| Open Food Facts | Service endpoint is configured in code | Not live-tested in this audit | Unknown; route exists and is implemented, but not live-called in this session | Not yet validated | Validate with a known UPC if needed |

## E. Camera and image-recognition report

### Browser camera access
- The frontend uses `navigator.mediaDevices.getUserMedia` and attaches the stream to a `<video>` element.
- It requests a rear camera when available (`facingMode: 'environment'` ideal) and includes a `SwitchCamera` option.
- It handles permission-denied, missing-camera, and busy-camera conditions with user-friendly error messages.
- It destroys/cleans up the stream when the component closes or remounts.
- A captured image is drawn onto a canvas and converted to a JPEG before upload.

### Observed status
- The code path is implemented correctly.
- Actual browser camera permission and hardware access were not tested in this headless environment because no interactive browser session was available.
- The camera feature is therefore marked: `MANUAL TEST REQUIRED`.

### Image upload status
- Frontend validation checks for image MIME type and file size (8 MB max on the frontend and backend guard at ~8 MB, plus server-side 413 error for oversized uploads).
- Uploads are sent as `FormData` to `/api/analyze/food` with an `Idempotency-Key` header.
- Invalid files, unsupported MIME types, empty files, and oversized images are rejected with explicit API errors.
- These flows are covered by backend tests and pass.

### Actual food recognition status
- The backend model itself is ready and the endpoint logic is valid.
- The app supports 24 food classes and uses a confidence threshold rule:
  - > 70% confidence is auto-accepted
  - <= 70% requires confirmation
  - invalid or missing confidence is treated as low confidence
- This logic is explicitly enforced in tests (`test_low_score_rejection_above_70_percent_is_accepted`, etc.) and passed.
- Real image calibration quality was not independently validated using a fresh external photo set in this audit; the project’s built-in tests use synthetic images and mocked recognizer objects.

## F. Nutrition and packaged-food report

### Nutrition flow
- The recognition-to-nutrition flow is implemented in the backend and frontend.
- Nutrition results can come from the project’s own dataset or from USDA FDC when a food is outside the 24 model classes.
- The logic intentionally distinguishes between verified nutrition and estimate-only data.
- The app enforces that missing nutrient fields are not treated as zero.

### Live validation
- USDA lookup for `apple` succeeded and returned valid nutrient data.
- This indicates the nutrition lookup path is operational for reference-data lookups when `USDA_FDC_API_KEY` is valid and the record match is accepted.

### Packaged-food OCR / label flow
- `/api/packaged/status` reported `dataset_loaded: true`, `products: 852`, and `ocr_available: true`.
- The packaged-food package is implemented as OCR -> label parsing -> product match -> additive analysis -> precaution checks.
- Tests cover:
  - label parsing and nutrient extraction
  - dataset matching
  - ambiguous and unreadable label handling
  - OCR failure handling
  - API responses
- These tests passed.

### Known limitations
- OCR is read-from-image and may produce errors; the app surfaces a warning and does not pretend the label is accurate.
- Dataset values are matched to product records, not necessarily the exact physical pack.
- Google Vision is not operational because the project lacks billing; therefore the second-opinion helper cannot independently validate food images until it is configured.

## G. Automated test results

### Backend
- Command run: `cd D:\SmartPlateAI\backend ; .\.venv\Scripts\python.exe -m pytest tests -q`
- Result: `180 passed, 1 skipped in 24.67s`
- Warning: one Keras warning about expected input structure for a real-model test; not a failure.

### Frontend
- Command run: `cd D:\SmartPlateAI\frontend ; npm run build`
- Result: build succeeded
- Output: Vite production bundle built successfully in 630 ms.

### Git
- `git status --short` returned: fatal, not a git repository.

## H. Prioritized defects

### 1) Critical — Chatbot runtime is failing currently
- Affected component: backend chat route and Google Gemini provider integration
- Evidence: `/api/chat` returned HTTP 503 from a live request; direct provider call returned `This model is currently experiencing high demand...`
- Likely root cause: provider overload / temporary service issue, not a local code logic failure
- Proposed fix: add user-facing retry/backoff and a graceful fallback path; if the configured model is under pressure, switch to a known-available model or present a clear transient-error message

### 2) High — Google Vision is effectively disabled because project billing is not enabled
- Affected component: backend `vision.py` + provider integration
- Evidence: direct Google Vision request returned HTTP 403 with “billing to be enabled”
- Likely root cause: API key exists, but Google Cloud project does not have billing enabled
- Proposed fix: enable billing for the project or disable the feature until it is configured; include “service unavailable” messaging rather than falsely claiming the second-opinion check works

### 3) Medium — Freshness model is not installed, so that feature is not available
- Affected component: model status endpoint and freshness pipeline
- Evidence: `/api/models/status` reported `freshness_model: 'not_installed'`
- Likely root cause: the model asset is absent or not deployed in this project snapshot
- Proposed fix: either deploy the model files or clearly disable the feature in the UI and API status messaging

### 4) Medium — Actual browser camera verification remains outstanding
- Affected component: `frontend/src/components/CameraCapture.tsx`
- Evidence: code appears correct, but no real browser permission/hardware tests were executed in this environment
- Likely root cause: headless environment prevented actual camera access testing
- Proposed fix: run manual verification in a browser on localhost with camera permissions enabled

### 5) Low — Some external services are configured but not yet live-validated
- Affected components: OpenAI Vision, Open Food Facts, related provider flows
- Evidence: route code exists and some env vars are set, but no live request was executed in this audit
- Likely root cause: audit scope prioritized safe minimal requests and avoided unnecessary provider spend or repeated external calls
- Proposed fix: validate these services with small, targeted requests on a case-by-case basis before relying on them in production

## I. Manual verification instructions

### 1) Browser camera verification
1. Start the frontend locally: `cd D:\SmartPlateAI\frontend` and `npm run dev`
2. Open `http://localhost:5173`
3. Navigate to the food analysis flow and choose the camera option.
4. Grant camera permission when prompted.
5. Confirm that the video preview starts and shows the live camera feed.
6. Click capture and confirm that the image is displayed in the preview area.
7. Save or upload the file, then verify the backend receives the image and the app shows a request result or error.
8. Close the camera component and verify the stream stops.
9. If the browser denies permission, confirm the UI shows the expected friendly message and that upload remains available as a fallback.

### 2) Food image upload verification
1. Use a clear photo of a supported food such as apple, banana, orange, tomato, or guava.
2. Upload the image through the analyzer.
3. Confirm the app sends the request to `/api/analyze/food`.
4. Verify that the returned prediction includes a food and a confidence value.
5. If the confidence is above 70%, confirm nutrition appears without additional confirmation.
6. If the confidence is 70% or lower, confirm the app asks the user to confirm or select the food.

### 3) Packaged-food analysis verification
1. Use a clear label image or product photo.
2. Upload the image to the packaged analyzer.
3. Confirm the OCR pipeline extracts text and the product match logic returns a result or an unmatched status.
4. Verify that ingredient names, allergens, and additives appear in the UI.
5. Confirm the product nutrition values make sense and are not presented as exact values for the photographed item unless they are clearly marked as dataset-based.

### 4) Chatbot verification
1. Open the chat UI in the browser.
2. Ask a simple question such as “What are the calories in this food?”
3. Confirm the app either returns a normal answer or a clear failure message if the provider is unavailable.
4. If the request fails, note whether the UI reports the failure instead of pretending the answer succeeded.
5. Verify that no raw API key or sensitive provider details are shown to the browser.

## Final assessment

The project is in a healthy state from a code-quality and automated-test perspective, but it is not fully operational end-to-end because the external AI provider integrations are not all healthy at the moment. The most meaningful blocker is the Gemini chatbot service returning temporary provider-side 503 errors, followed by the Google Vision requirement for billing. The app should be considered usable for local testing and offline/integrated logic validation, but not as a fully reliable production-grade AI workflow until these external dependencies are restored.
