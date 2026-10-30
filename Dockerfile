# SmartPlateAI: one container serving the API and the built React app from the same HTTPS origin.
# Build context = project root. Run backend/scripts/prepare_deploy_data.py first (copies the reference CSVs into
# deploy/reference_data). Secrets are NEVER baked into the image: pass them as environment variables at run time.

# ---------- 1. frontend build
FROM node:22-slim AS frontend
WORKDIR /src/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Same-origin deployment: the app calls /api on the host that served it, so no API URL is compiled in.
RUN npm run build

# ---------- 2. runtime
FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 TF_CPP_MIN_LOG_LEVEL=2
# Tesseract OCR for packaged-food labels (the app calls the program; no Python package is needed).
RUN apt-get update \
 && apt-get install -y --no-install-recommends tesseract-ocr tesseract-ocr-eng \
 && rm -rf /var/lib/apt/lists/*
RUN useradd --create-home --uid 10001 app && mkdir -p /data && chown app:app /data
WORKDIR /app/backend
COPY backend/requirements-deploy.txt ./
RUN pip install -r requirements-deploy.txt
COPY backend/app ./app
COPY backend/models/production/food_classifier ./models/production/food_classifier
COPY backend/models/production/freshness ./models/production/freshness
COPY deploy/reference_data /app/reference_data
COPY --from=frontend /src/frontend/dist /app/frontend/dist
USER app
# The non-food check uses the original ImageNet MobileNetV2; download its weights now instead of on the first request.
RUN python -c "import tensorflow as tf; tf.keras.applications.MobileNetV2(weights='imagenet', include_top=True, input_shape=(224, 224, 3))"

ENV ENVIRONMENT=production \
    SERVE_FRONTEND_DIR=/app/frontend/dist \
    DATABASE_PATH=/data/smartplate.db \
    AUTH_DATABASE_PATH=/data/smartplate_users.db \
    FOOD_NUTRITION_CSV=/app/reference_data/final_food_nutrient_dataset.csv \
    PACKAGED_FOODS_CSV=/app/reference_data/packaged_foods_india_clean.csv \
    PACKAGED_ADDITIVES_CSV=/app/reference_data/packaged_food_additives.csv \
    ADDITIVE_REFERENCE_CSV=/app/reference_data/additive_reference_populated.csv \
    TESSERACT_CMD=/usr/bin/tesseract \
    MAX_UPLOAD_MB=8
# /data must be a persistent volume (accounts, history, cache). The process listens on $PORT (default 8000) behind an
# HTTPS reverse proxy; it is not meant to be exposed directly.
VOLUME ["/data"]
EXPOSE 8000
HEALTHCHECK --interval=60s --timeout=5s --start-period=120s CMD python -c "import urllib.request,os; urllib.request.urlopen('http://127.0.0.1:%s/health' % os.environ.get('PORT','8000'), timeout=4)"
# --proxy-headers: the client address comes from X-Forwarded-For, but only when the request arrives from an address in
# FORWARDED_ALLOW_IPS (uvicorn reads it from the environment; docker-compose.yml sets it to the private network Caddy is on).
# Default 127.0.0.1, so a container exposed directly cannot be fooled by a client-supplied header. --limit-concurrency
# answers 503 instead of queueing without bound; the app itself runs at most MAX_CONCURRENT_ANALYSES photo analyses at once.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000} --proxy-headers --limit-concurrency ${LIMIT_CONCURRENCY:-32} --timeout-keep-alive 5 --workers 1"]
