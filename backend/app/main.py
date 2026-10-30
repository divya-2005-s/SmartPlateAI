import os
import platform
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

from app.core.config import get_settings

settings = get_settings()

app = FastAPI(title=settings.app_name, version=settings.app_version)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
    first = exc.errors()[0] if exc.errors() else {}
    field = first.get("loc", ["request"])[-1]
    message = f"Invalid {field}: {first.get('msg', 'value is not valid')}."
    return JSONResponse(status_code=422, content={
        "success": False,
        "error_code": "INVALID_INPUT",
        "message": message,
    })


@app.exception_handler(HTTPException)
async def http_error_handler(request: Request, exc: HTTPException) -> JSONResponse:
    if isinstance(exc.detail, dict) and isinstance(exc.detail.get("error_code"), str):
        content = exc.detail
    elif exc.status_code == 401:
        content = {"success": False, "error_code": "NOT_AUTHENTICATED",
                   "message": "Please sign in to use this feature."}
    else:
        content = {"success": False, "error_code": "HTTP_ERROR", "message": str(exc.detail)}
    return JSONResponse(status_code=exc.status_code, content=content, headers=exc.headers)


from app.api.limits import BodySizeLimit  # noqa: E402

# Inside CORS, so a 413/411 still carries the CORS headers the browser needs to read it.
app.add_middleware(BodySizeLimit)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

from app.api.routes.analyze import router as analyze_router
from app.api.routes.accounts import router as accounts_router
from app.api.routes.auth import router as auth_router
from app.api.routes.chat import router as chat_router
from app.api.routes.meal_plans import router as meal_plans_router
from app.api.routes.packaged import router as packaged_router
from app.api.routes.reports import router as reports_router
from app.api.routes.tools import router as tools_router
from app.api.routes.user_data import router as user_data_router
app.include_router(analyze_router)
app.include_router(accounts_router)
app.include_router(auth_router)
app.include_router(meal_plans_router)
app.include_router(packaged_router)
app.include_router(reports_router)
app.include_router(tools_router)
app.include_router(user_data_router)
app.include_router(chat_router)

class HealthResponse(BaseModel):
    status: str
    service: str
    version: str
    environment: str
    python_version: str
    timestamp_utc: str


@app.get("/health", response_model=HealthResponse, tags=["system"])
@app.get("/api/health", response_model=HealthResponse, tags=["system"])
def health() -> HealthResponse:
    """Confirms that the API process is running. It does not check models or data."""
    return HealthResponse(
        status="ok",
        service=settings.app_name,
        version=settings.app_version,
        environment=settings.environment,
        python_version=platform.python_version(),
        timestamp_utc=datetime.now(timezone.utc).isoformat(),
    )

# ------------------------------------------------------------------ security headers
@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Permissions-Policy", "camera=(self), microphone=(), geolocation=()")
    if settings.environment.strip().lower() in {"production", "prod"}:
        response.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return response


# ------------------------------------------------------------------ built frontend (deployment only)
# SERVE_FRONTEND_DIR=/app/frontend/dist makes this one process serve the React app and the API from the same HTTPS origin, so
# no CORS is needed and the session cookie stays first-party. Unset in local development, where Vite serves the frontend.
_frontend_dir = os.environ.get("SERVE_FRONTEND_DIR", "").strip()
if _frontend_dir and (Path(_frontend_dir) / "index.html").is_file():
    _frontend_root = Path(_frontend_dir).resolve()

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        if path == "api" or path.startswith("api/"):
            raise HTTPException(status_code=404, detail="Not found.")
        target = (_frontend_root / path).resolve()
        if path and target.is_file() and _frontend_root in target.parents:
            immutable = path.startswith("assets/")  # Vite's content-hashed files
            return FileResponse(target, headers={"Cache-Control": "public, max-age=31536000, immutable" if immutable else "no-cache"})
        return FileResponse(_frontend_root / "index.html", headers={"Cache-Control": "no-cache"})  # client-side routes
