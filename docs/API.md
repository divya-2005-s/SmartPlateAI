# SmartPlateAI API reference

Generated from the running FastAPI app (`/docs` shows the interactive version).

All errors use one shape: `{"success": false, "error_code": "...", "message": "..."}`.
Signed-in endpoints accept the original `smartplate_session` HTTP-only cookie. Bearer sessions returned for the v3 account contract remain supported as a compatibility path.

**Limits (production; see `DEPLOYMENT.md` section 3).** "Public" endpoints that would call a paid provider do so only for a
signed-in user: anonymous `/api/analyze/food` and `/api/analyze/packaged` use the image model / Tesseract only
(`openai_vision.reason = "login_required"`), and `/api/chat`, `/api/chat/stream` answer 401 `NOT_AUTHENTICATED`.
Additional error codes: 429 `RATE_LIMITED` (with `Retry-After` and `retry_after_s`), 413 `REQUEST_TOO_LARGE`, 411
`LENGTH_REQUIRED`, 503 `SERVER_BUSY` (too many parallel analyses), 503 `CHAT_DAILY_LIMIT`. A provider that reached its daily
cap reports `reason = "daily_limit_reached"`. `GET /api/chat/status` also returns `requires_login` and `signed_in`.

## account

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/allergens/options` | public | Allergen Options |
| GET | `/api/allergens/preferences` | signed-in | Get Allergen Prefs |
| PUT | `/api/allergens/preferences` | signed-in | Put Allergen Prefs |
| POST | `/api/auth/login` | public | Login |
| POST | `/api/auth/logout` | signed-in | Revokes the current cookie or bearer session |
| GET | `/api/auth/me` | signed-in | Current cookie user or bearer-session profile |
| POST | `/api/auth/signup` | public | Email/password uses cookie auth; a named v3 signup also returns a bearer session |
| GET | `/api/profile` | signed-in | Profile used by the application shell |
| PATCH | `/api/profile` | signed-in | Update Profile |
| POST | `/api/profile/delete` | signed-in | Delete Account |
| POST | `/api/profile/password` | signed-in | Change Password |

## analysis

| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/analyze/confirm` | public | Confirm Food |
| POST | `/api/analyze/food` | public | Analyze Food |
| GET | `/api/chemical/{food}` | public | Chemical |
| GET | `/api/foods/supported` | public | Supported Foods |
| GET | `/api/models/status` | public | Models Status |

`POST /api/analyze/food` keeps its existing response fields and adds `recognition` and `openai_vision` metadata. `recognition.status` is `verified_both`, `tensorflow_fallback`, or a confirmation/unsupported/non-food status. OpenAI never returns a confidence score; disagreement or unclear/unsupported food does not receive nutrition before user confirmation. A configured OpenAI rate limit also requires confirmation instead of accepting the TensorFlow result. Set `OPENAI_VISION_ENABLED=false` to retain the existing TensorFlow/Google Vision path.

## chat

| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/chat` | public; signed-in in production | Chat Reply |
| GET | `/api/chat/status` | public | Chat Status |
| POST | `/api/chat/stream` | public; signed-in in production | Streams the answer as SSE events: `chunk` {text}, then `done` {latency_ms, first_chunk_ms, cached} or `error` {error_code, message}. |

## history & nutrition

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/corrections` | signed-in | My Corrections |
| POST | `/api/corrections` | signed-in | Add Correction |
| GET | `/api/history` | signed-in | List Scans |
| POST | `/api/history` | signed-in | Save Scan |
| DELETE | `/api/history/{scan_id}` | signed-in | Delete Scan |
| GET | `/api/history/{scan_id}` | signed-in | Get Scan |
| GET | `/api/nutrition/day` | signed-in | Nutrition Day |
| POST | `/api/nutrition/entries` | signed-in | Add Entry |
| DELETE | `/api/nutrition/entries/{entry_id}` | signed-in | Delete Entry |
| PATCH | `/api/nutrition/entries/{entry_id}` | signed-in | Edit Entry |
| GET | `/api/nutrition/week` | signed-in | Nutrition Week |

## meal planner

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/meal-plans` | signed-in | List Plans |
| POST | `/api/meal-plans` | signed-in | Create Plan |
| DELETE | `/api/meal-plans/{plan_id}` | signed-in | Delete Plan |
| GET | `/api/meal-plans/{plan_id}` | signed-in | Get Plan |
| PUT | `/api/meal-plans/{plan_id}/meal` | signed-in | Edit Meal |
| POST | `/api/meal-plans/{plan_id}/regenerate` | signed-in | Regenerate |

## packaged

| Method | Path | Access | Notes |
|---|---|---|---|
| POST | `/api/analyze/packaged` | public (adds personal allergen alerts when signed in) | Analyze Packaged |
| GET | `/api/packaged/off/{barcode}` | public (adds personal allergen alerts when signed in) | Off Barcode |
| GET | `/api/packaged/products/{product_id}` | public (adds personal allergen alerts when signed in) | Packaged Product |
| GET | `/api/packaged/search` | public | Packaged Search |
| GET | `/api/packaged/status` | public | Packaged Status |

## reports

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/reports/nutrition` | signed-in | Nutrition Pdf |
| GET | `/api/reports/scans/{scan_id}` | signed-in | Scan Pdf |

## system

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/health` | public | Confirms that the API process is running. It does not check models or data. |
| GET | `/health` | public | Confirms that the API process is running. It does not check models or data. |

## tools

| Method | Path | Access | Notes |
|---|---|---|---|
| GET | `/api/packaged/compare` | public (adds personal allergen alerts when signed in) | Compare |
| GET | `/api/packaged/compare/options` | public | Compare Options |
| POST | `/api/tools/bmi` | public | Bmi |

## External services (server-side only)

| Service | Used for | Configuration | When unavailable |
|---|---|---|---|
| Google Cloud Vision | second opinion on food photos (labels, objects) | `GOOGLE_VISION_API_KEY` | image model only; result says so |
| OpenAI vision | Structured second opinion for fresh-food identification | `OPENAI_API_KEY`, `OPENAI_VISION_MODEL` (default `gpt-4.1-mini`), `OPENAI_VISION_ENABLED` | other provider outages use the existing path and are marked as fallback; rate limits require confirmation |
| Open Food Facts | barcode / brand+name product lookup | `OPENFOODFACTS_ENABLED` | 'external database unavailable' |
| PubChem PUG REST | compound identity (IUPAC name, formula, weight) | `PUBCHEM_ENABLED` | compounds listed without formula |
| USDA FoodData Central | nutrient amounts (CSV record; optional live API) | `USDA_FDC_API_KEY` (optional) | CSV record only |
| Google Gemini | chatbot (streaming) and meal planner | `GEMINI_API_KEY`, `GEMINI_MODEL` (sample/default: `gemma-4-26b-a4b-it`) | clear 'not configured' / 'unreachable' errors |
| Tesseract OCR | reading package labels | `TESSERACT_CMD` if not on PATH | `OCR_UNAVAILABLE` error |

External responses are cached in the `http_cache` table (Vision 7 days, Open Food Facts 3 days, PubChem and FDC 30 days).
