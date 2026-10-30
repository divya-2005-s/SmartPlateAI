# SmartPlateAI

AI food recognition, nutrition analysis, packaged-label scanning and food-safety guidance.
Final-year project. Not a medical device: results are general information and always show their source.

- **Backend:** FastAPI (Python 3.12), TensorFlow/Keras food classifier (24 classes, MobileNetV2), SQLite, Tesseract OCR
- **Frontend:** React + Vite + TypeScript + Tailwind v4
- **External services (all optional, server-side only):** Google Gemini, Google Cloud Vision, Open Food Facts, PubChem, USDA FoodData Central

See `docs/FEATURES.md` for what each feature does, how it was tested, and its limitations, and `docs/API.md` for every endpoint.

## 1. Requirements
- Windows 10/11, Python 3.12 (`backend\.venv`), Node.js 20+.
- Tesseract OCR for Windows (for label scanning): https://github.com/UB-Mannheim/tesseract/wiki
- Not included in the project ZIP (restore them to these paths):
  - `D:\Food_Composition_Project\` (images and CSVs: `output\final_food_nutrient_dataset.csv`, `output\packaged_foods_india_clean.csv`,
    `output\packaged_food_additives.csv`, the OCR dataset)
  - Model runs other than production: `backend\models\food_head_full_01`, `backend\models\food_ft_01`, `pilot_head_01` (only `models\production\` is zipped)

## 2. Install
```powershell
cd D:\SmartPlateAI\backend
py -3.12 -m venv .venv                      # skip if .venv already exists
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m pip install tensorflow==2.19.1 keras pandas numpy pillow   # model + data stack
Copy-Item .env.example .env                 # then edit .env (only if you do not have one yet)

cd D:\SmartPlateAI\frontend
npm ci
```
No additional Python packages were added for accounts, history, PDF reports, Vision, Open Food Facts, PubChem or Gemini: they use the Python standard library.

## 3. Run
```powershell
# Terminal 1: backend (do not use --reload; it loads TensorFlow twice)
cd D:\SmartPlateAI\backend
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000

# Terminal 2: frontend
cd D:\SmartPlateAI\frontend
npm run dev          # open http://localhost:5173
```
Checks: `http://127.0.0.1:8000/health`, `/api/models/status`, `/api/packaged/status`, and `/api/chat/status`.
The SQLite database is created automatically at `backend\data\smartplate.db` on first start (migrations are additive).

Public HTTPS deployment (phones on any network): see [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) (Dockerfile, Caddy, PWA). With
`ENVIRONMENT=production` the app requires sign-in for paid AI providers and the chatbot, rate-limits requests and caps daily
provider calls (section 3 there); locally these are off unless you set `RATE_LIMITS_ENABLED` / `PAID_PROVIDERS_REQUIRE_LOGIN`.
Real-photo evaluations: `backend\scripts\eval_food_gate.py --api` (food / non-food / packaged decisions) and
`backend\scripts\eval_packaged_labels.py` (packaged labels); results in [docs/PACKAGED_EVALUATION.md](docs/PACKAGED_EVALUATION.md).
Paid Gemini label test (not run, needs approval): [docs/GEMINI_LABEL_TEST_PLAN.md](docs/GEMINI_LABEL_TEST_PLAN.md).

## 4. Test
```powershell
cd D:\SmartPlateAI\backend
.\.venv\Scripts\python.exe -m pytest tests -q        # external APIs are mocked; no keys needed
cd D:\SmartPlateAI\frontend
npm run build                                        # type-check + production build
node --test --experimental-strip-types tests/*.test.ts
npm run lint
```

## 5. Optional model/tooling scripts (backend\scripts)
| Script | Purpose |
|---|---|
| `calibrate_rejection.py` | Calibrate non-food / unsupported rejection on validation data (never the test split) |
| `diagnose_recognition.py` | Per-image and per-class decisions before/after the classifier-agreement check |
| `train_freshness_head.py` | Train the fresh / possibly spoiled head on the production model's embeddings (validation-calibrated) |
| `measure_chat_latency.py` | Measure real Gemini latency (streaming first chunk vs full answer) |
| `export_corrections.py` | Export user corrections for manual review |

## 6. Configuration
All variables are listed in `backend\.env.example` (placeholders only). Never commit `backend\.env`.
