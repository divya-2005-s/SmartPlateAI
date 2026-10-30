"""Deployment preflight: checks the running configuration before the site goes public. Read-only; never prints secrets.

On the server:  docker compose -f deploy/docker-compose.yml run --rm --no-deps app python -m app.core.preflight
Exit code 0 = no FAIL (WARN lines still deserve a look), 1 = at least one FAIL.
"""
from __future__ import annotations

import ipaddress
import os
import shutil
import sys
from pathlib import Path

from app.core.config import get_settings
from app.services import usage_limits as ul

PROVIDER_KEYS = {"OPENAI_API_KEY": "openai_api_key", "GEMINI_API_KEY": "gemini_api_key", "GOOGLE_API_KEY": "google_api_key",
                 "GOOGLE_VISION_API_KEY": "google_vision_api_key", "USDA_FDC_API_KEY": "usda_fdc_api_key"}


def run() -> list[tuple[str, str]]:
    s = get_settings()
    out: list[tuple[str, str]] = []

    def check(ok: bool, good: str, bad: str, level: str = "FAIL") -> None:
        out.append(("OK", good) if ok else (level, bad))

    check(ul.production(), "ENVIRONMENT=production", f"ENVIRONMENT is '{s.environment}', not production (limits and Secure cookies stay off)")
    try:
        from app.api.routes.auth import _cookie_options  # noqa: PLC0415
        secure, same_site, _ = _cookie_options(s)
        check(secure, f"session cookie Secure, SameSite={same_site}", "AUTH_COOKIE_SECURE is off")
    except RuntimeError as exc:
        out.append(("FAIL", f"cookie settings invalid: {exc}"))
    check(ul.paid_requires_login(), "paid providers and chatbot require sign-in", "PAID_PROVIDERS_REQUIRE_LOGIN is off: anonymous users can trigger paid calls")
    check(ul.rate_limits_enabled(), "rate limits on", "RATE_LIMITS_ENABLED is off")
    limits = {k: getattr(s, k) for k in type(s).model_fields if k.startswith("rate_limit_") and k.endswith(("_hour", "_day"))}
    check(all(isinstance(v, int) and v > 0 for v in limits.values()), "rate limits: " + ", ".join(f"{k[11:]}={v}" for k, v in limits.items()),
          "a rate limit is 0 or negative: " + ", ".join(f"{k}={v}" for k, v in limits.items() if not v or v < 0))

    keys = {name: bool(getattr(s, attr).strip()) for name, attr in PROVIDER_KEYS.items()}
    out.append(("INFO", "keys present (values not shown): " + ", ".join(f"{k}={'yes' if v else 'no'}" for k, v in keys.items())))
    caps = {"OPENAI_DAILY_LIMIT": (s.openai_daily_limit, keys["OPENAI_API_KEY"] and s.openai_vision_enabled),
            "GEMINI_DAILY_LIMIT": (s.gemini_daily_limit, (keys["GEMINI_API_KEY"] or keys["GOOGLE_API_KEY"]) and s.gemini_vision_enabled),
            "GOOGLE_VISION_DAILY_LIMIT": (s.google_vision_daily_limit, keys["GOOGLE_VISION_API_KEY"] and s.vision_enabled),
            "CHAT_DAILY_LIMIT": (s.chat_daily_limit, keys["GEMINI_API_KEY"] or keys["GOOGLE_API_KEY"])}
    for name, (cap, active) in caps.items():
        check(cap >= 0, f"{name}={cap} ({'provider active' if active else 'provider off or no key'})", f"{name} is negative")
    if any(active for _, active in caps.values()):
        out.append(("WARN", "a paid provider is active: confirm a budget alert and spending limit exist in its console (cannot be checked from here)"))

    trusted = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1,::1")
    try:
        nets = [ipaddress.ip_network(t.strip(), strict=False) for t in trusted.split(",") if t.strip()]
        narrow = all(n.num_addresses <= 256 for n in nets)
    except ValueError:
        narrow = False
    check(narrow, f"FORWARDED_ALLOW_IPS={trusted}", f"FORWARDED_ALLOW_IPS={trusted!r} trusts too much (clients could fake their IP)")

    cors = s.cors_origin_list
    check(bool(cors) and all(o.startswith("https://") and "example" not in o for o in cors),
          f"CORS_ORIGINS={','.join(cors)}", f"CORS_ORIGINS={','.join(cors)!r} is not your https:// site", "WARN")

    data_files = {"DATABASE_PATH": s.database_path, "AUTH_DATABASE_PATH": os.environ.get("AUTH_DATABASE_PATH", "")}
    for name, value in data_files.items():
        p = Path(value) if value else None
        check(p is not None and p.is_absolute(), f"{name}={value}", f"{name} not set: data would be written inside the container")
        if p is not None and p.is_absolute():
            check(p.parent.is_dir() and os.access(p.parent, os.W_OK), f"{p.parent} writable", f"{p.parent} missing or not writable")
    check(str(ul.db_path().parent) == str(Path(s.database_path or "").parent), f"rate-limit counters in {ul.db_path()}",
          f"rate-limit counters at {ul.db_path()} are not next to DATABASE_PATH", "WARN")
    if os.path.ismount("/data") is False and Path("/data").exists() and sys.platform != "win32":
        out.append(("WARN", "/data is not a mount point: accounts are lost when the container is recreated"))

    for name in ("FOOD_NUTRITION_CSV", "PACKAGED_FOODS_CSV", "PACKAGED_ADDITIVES_CSV", "ADDITIVE_REFERENCE_CSV"):
        v = os.environ.get(name, "")
        check(bool(v) and Path(v).is_file(), f"{name} found", f"{name} missing ({v or 'not set'})")
    from app.ml.recognizer import DEFAULT_MODEL_DIR  # noqa: PLC0415
    model_dir = Path(os.environ.get("FOOD_MODEL_DIR") or DEFAULT_MODEL_DIR)
    need = ["best.keras", "class_names.json", "rejection_config.json", "rejection_stats.npz"]
    check(all((model_dir / f).is_file() for f in need), f"food model files in {model_dir}", f"food model files missing in {model_dir}")
    tess = s.tesseract_cmd or os.environ.get("TESSERACT_CMD", "")
    check(bool(tess) and (Path(tess).is_file() or shutil.which(tess) is not None), f"Tesseract at {tess}", "Tesseract not found", "WARN")
    front = os.environ.get("SERVE_FRONTEND_DIR", "")
    check(bool(front) and (Path(front) / "index.html").is_file(), f"frontend served from {front}", "SERVE_FRONTEND_DIR not set or no index.html", "WARN")
    return out


def main() -> int:
    results = run()
    for level, text in results:
        print(f"{level:4}  {text}")
    fails = sum(1 for level, _ in results if level == "FAIL")
    print(f"\n{fails} FAIL, {sum(1 for level, _ in results if level == 'WARN')} WARN")
    return 1 if fails else 0


if __name__ == "__main__":
    sys.exit(main())
