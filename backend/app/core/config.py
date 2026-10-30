from functools import lru_cache
from pathlib import Path
from typing import Any

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    app_name: str = "SmartPlateAI API"
    app_version: str = "0.1.0"
    environment: str = "development"
    # Comma-separated list of allowed browser origins (the local Vite frontend by default).
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    # Packaged-food OCR and data (optional; sensible defaults are used when empty).
    tesseract_cmd: str = ""
    packaged_foods_csv: str = ""
    packaged_additives_csv: str = ""
    additive_reference_csv: str = ""
    # Chatbot (Gemini). The key stays on the server; it is never sent to the browser.
    gemini_api_key: str = ""
    google_api_key: str = ""
    gemini_model: str = "gemma-4-26b-a4b-it"
    gemini_timeout_s: float = 30.0
    # Database and accounts (SQLite file; created automatically, never committed).
    database_path: str = ""
    password_iterations: int = 390000
    session_days: int = 14
    # Optional external data sources. All calls happen on the server; failures fall back gracefully.
    google_vision_api_key: str = ""
    vision_enabled: bool = True
    vision_min_score: float = 0.70
    openai_api_key: str = ""
    openai_vision_model: str = "gpt-4.1-mini"
    openai_vision_enabled: bool = True
    openai_vision_timeout_s: float = 30.0
    # What to do when OpenAI is configured but fails (timeout, auth, network, invalid reply) and Google Vision does not agree:
    # "threshold" = the 70% rule decides: image-model confidence >= 70% is accepted (labelled as not independently
    #               verified), below 70% the user confirms (default);
    # "confirm"   = always ask the user to confirm (stricter);
    # "fallback"  = accept the image model's answer unless OpenAI was rate-limited (the original behaviour).
    openai_failure_policy: str = "threshold"
    # Google Gemini food identification, used only when OpenAI Vision cannot answer (same prompt, fields and validation).
    # Uses GEMINI_API_KEY (or GOOGLE_API_KEY). Set GEMINI_VISION_ENABLED=false to never send food photos to Gemini.
    gemini_vision_enabled: bool = True
    gemini_vision_model: str = "gemini-3.1-flash-lite,gemini-flash-lite-latest"  # tried in order if one is busy/retired
    gemini_vision_timeout_s: float = 30.0
    openfoodfacts_enabled: bool = True
    pubchem_enabled: bool = True
    usda_fdc_api_key: str = ""
    http_timeout_s: float = 8.0
    # Abuse limits for a public deployment (app/services/usage_limits.py). "auto" = on when ENVIRONMENT=production,
    # off in local development; "true"/"false" force it. Any other value counts as "true".
    rate_limits_enabled: str = "auto"
    paid_providers_require_login: str = "auto"  # anonymous visitors get the image model only (no OpenAI/Gemini/Vision/chat)
    rate_limit_anon_analyses_per_hour: int = 10   # per client IP
    rate_limit_user_analyses_per_hour: int = 30   # per signed-in account
    rate_limit_user_analyses_per_day: int = 200
    rate_limit_chat_per_hour: int = 30            # per account (per IP when sign-in is not required)
    rate_limit_signups_per_hour: int = 5          # per client IP
    rate_limit_logins_per_hour: int = 30          # per client IP, on top of the per-email failed-login lock
    rate_limit_lookups_per_hour: int = 300        # per client IP: food confirmation, chemicals, Open Food Facts lookups
    # Global daily caps on paid provider requests (UTC day, all users together; always on). 0 blocks the provider.
    openai_daily_limit: int = 300
    gemini_daily_limit: int = 300
    google_vision_daily_limit: int = 300
    chat_daily_limit: int = 500
    # Request size and load limits (always on).
    max_request_mb: float = 30.0      # whole multipart body (a packaged scan sends up to three 8 MB photos)
    max_json_kb: int = 1024           # any other request body
    max_concurrent_analyses: int = 3  # photo analyses in parallel; a decoded 40 MP photo alone needs ~120 MB
    analysis_queue_timeout_s: float = 30.0
    usage_database_path: str = ""     # counters; default: smartplate_usage.db next to DATABASE_PATH

    def __init__(self, **values: Any) -> None:
        if values.get("_env_file") is not None:
            values.setdefault("_env_ignore_empty", True)
        super().__init__(**values)

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()