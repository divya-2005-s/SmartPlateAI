"""Small HTTP helper for external APIs: timeouts, one bounded retry, and a persistent SQLite cache.

Standard library only. Errors are converted to ExternalError with a code the API can show to users. URLs and
response bodies may be logged at debug level, but API keys are never logged (they are sent as headers).
"""
from __future__ import annotations

import hashlib
import json
import logging
import socket
import ssl
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone

from app.core.config import get_settings

log = logging.getLogger("smartplate.http")
USER_AGENT = "SmartPlateAI/0.2 (final-year student project; contact via project repository)"


class ExternalError(Exception):
    """`code` is the stable category callers branch on; `cause` optionally says why a connection failed
    ('tls_certificate', 'dns', 'connection'), so a message can be specific without adding new codes."""

    def __init__(self, code: str, message: str, status: int | None = None, cause: str | None = None) -> None:
        super().__init__(message)
        self.code, self.message, self.status, self.cause = code, message, status, cause


def request_json(url: str, *, method: str = "GET", payload: dict | None = None, headers: dict | None = None,
                 timeout: float | None = None, retries: int = 1) -> dict:
    timeout = timeout or get_settings().http_timeout_s
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    hdrs = {"User-Agent": USER_AGENT, "Accept": "application/json", **(headers or {})}
    if data is not None:
        hdrs["Content-Type"] = "application/json"
    attempt = 0
    while True:
        attempt += 1
        try:
            req = urllib.request.Request(url, data=data, method=method, headers=hdrs)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            body = ""
            try:
                body = exc.read().decode("utf-8", "ignore")[:500]
            except Exception:  # noqa: BLE001
                pass
            if exc.code in (429, 500, 502, 503, 504) and attempt <= retries:
                time.sleep(min(2.0, 0.6 * attempt))
                continue
            if exc.code == 404:
                raise ExternalError("NOT_FOUND", "Not found in the external database.", 404) from None
            if exc.code in (401, 403):
                lower = body.lower()
                if "billing" in lower or "billed" in lower or "enable billing" in lower:
                    raise ExternalError(
                        "BILLING_REQUIRED",
                        "Google Cloud billing is not enabled for the Vision project, or the API key is blocked. Enable billing in the Google Cloud project and ensure the key is allowed to use the Cloud Vision API.",
                        exc.code,
                    ) from None
                raise ExternalError("AUTH_FAILED", "The external service rejected the credentials or the API is not enabled/billed.", exc.code) from None
            if exc.code == 429:
                raise ExternalError("RATE_LIMITED", "The external service quota or rate limit was reached.", 429) from None
            if exc.code == 400 and ("API key" in body or "API_KEY" in body):
                raise ExternalError("AUTH_FAILED", "The external API key is invalid.", 400) from None
            raise ExternalError("BAD_RESPONSE", f"The external service returned HTTP {exc.code}.", exc.code) from None
        except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError, OSError) as exc:
            if attempt <= retries:
                time.sleep(0.4)
                continue
            reason = getattr(exc, "reason", exc)
            if isinstance(exc, (socket.timeout, TimeoutError)) or isinstance(reason, (socket.timeout, TimeoutError)):
                raise ExternalError("TIMEOUT", "The external service did not answer in time.") from exc
            if isinstance(reason, ssl.SSLCertVerificationError) or isinstance(exc, ssl.SSLCertVerificationError):
                # Seen on some networks (e.g. a phone hotspot or a filtering proxy) that present an untrusted certificate.
                raise ExternalError("UNREACHABLE", "A secure connection to the external service could not be verified "
                                    "(certificate problem on the server's network).", cause="tls_certificate") from exc
            if isinstance(reason, socket.gaierror):
                raise ExternalError("UNREACHABLE", "The external service's address could not be resolved (DNS or no internet).",
                                    cause="dns") from exc
            raise ExternalError("UNREACHABLE", "The external service could not be reached (network error).", cause="connection") from exc
        except ValueError as exc:
            raise ExternalError("BAD_RESPONSE", "The external service returned invalid data.") from exc


def build_url(base: str, params: dict) -> str:
    return base + ("?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None}) if params else "")


# ------------------------------------------------------------------ persistent cache (http_cache table)
def cache_key(*parts: str) -> str:
    return hashlib.sha256("\x1f".join(parts).encode("utf-8")).hexdigest()


def cache_get(key: str):
    from app.core.db import connect  # noqa: PLC0415
    conn = connect()
    try:
        row = conn.execute("SELECT value, expires_at FROM http_cache WHERE key = ?", (key,)).fetchone()
        if row and row["expires_at"] > datetime.now(timezone.utc).isoformat():
            return json.loads(row["value"])
        return None
    except Exception:  # noqa: BLE001 - a cache failure must never break a request
        log.debug("cache read failed", exc_info=True)
        return None
    finally:
        conn.close()


def cache_set(key: str, value, ttl_s: int) -> None:
    from app.core.db import connect  # noqa: PLC0415
    conn = connect()
    try:
        exp = (datetime.now(timezone.utc) + timedelta(seconds=ttl_s)).isoformat()
        with conn:
            conn.execute("INSERT OR REPLACE INTO http_cache (key, value, expires_at) VALUES (?, ?, ?)", (key, json.dumps(value), exp))
    except Exception:  # noqa: BLE001
        log.debug("cache write failed", exc_info=True)
    finally:
        conn.close()
