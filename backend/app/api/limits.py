"""Request guards: per-account / per-IP rate limits (HTTP 429), a bound on parallel photo analyses (HTTP 503) and a
request-body size limit (HTTP 413 / 411). Counting and policy live in app/services/usage_limits.py."""
from __future__ import annotations

import json
import logging
import math
import threading
from collections.abc import Iterator

from fastapi import Depends, HTTPException, Request

from app.api.deps import User, optional_user
from app.core.config import get_settings
from app.services import usage_limits as ul

log = logging.getLogger("smartplate.limits")

WHAT = {"analysis": "photo analyses", "chat": "chatbot messages", "signup": "account sign-ups",
        "login": "sign-in attempts", "lookup": "lookups"}


def client_host(request: Request) -> str | None:
    # Behind Caddy, uvicorn's --proxy-headers has already replaced the peer with the real client address, and only for
    # proxies listed in FORWARDED_ALLOW_IPS; a client cannot choose this value by sending its own X-Forwarded-For.
    return request.client.host if request.client else None


def rules_for(kind: str, user: User | None, ip_key: str) -> list[tuple[str, int, int]]:
    s = get_settings()
    if kind == "analysis":
        if user is not None:
            return [(f"analysis:u:{user.id}", s.rate_limit_user_analyses_per_hour, ul.HOUR),
                    (f"analysis:u:{user.id}:day", s.rate_limit_user_analyses_per_day, ul.DAY)]
        return [(f"analysis:ip:{ip_key}", s.rate_limit_anon_analyses_per_hour, ul.HOUR)]
    if kind == "chat":
        who = f"u:{user.id}" if user is not None else f"ip:{ip_key}"
        return [(f"chat:{who}", s.rate_limit_chat_per_hour, ul.HOUR)]
    per_ip = {"signup": s.rate_limit_signups_per_hour, "login": s.rate_limit_logins_per_hour, "lookup": s.rate_limit_lookups_per_hour}
    return [(f"{kind}:ip:{ip_key}", per_ip[kind], ul.HOUR)]


def check(kind: str, request: Request, user: User | None) -> None:
    """Count this request; raise HTTP 429 with Retry-After when over the limit. No-op when rate limits are off."""
    if not ul.rate_limits_enabled():
        return
    try:
        ip_key = ul.client_key(client_host(request))
        wait = ul.consume(rules_for(kind, user, ip_key))
    except Exception as exc:  # noqa: BLE001  (counter store failure must not take the site down; paid caps still fail closed)
        log.error("rate limit store unavailable (%s); request allowed", type(exc).__name__)
        return
    if wait is None:
        return
    log.warning("rate limited kind=%s who=%s", kind, "account" if user is not None else f"ip:{ip_key[:8]}")
    minutes = max(1, math.ceil(wait / 60))
    message = (f"Too many {WHAT[kind]} in a short time. Please try again in about {minutes} minute{'s' if minutes != 1 else ''}.")
    if kind == "analysis" and user is None:
        message += " Signed-in accounts have a higher limit."
    raise HTTPException(status_code=429, headers={"Retry-After": str(wait)},
                        detail={"success": False, "error_code": "RATE_LIMITED", "message": message, "retry_after_s": wait})


def limit(kind: str):
    """Dependency factory: `dependencies=[Depends(limit("lookup"))]` or a parameter `_: None = Depends(limit("chat"))`."""
    def dependency(request: Request, user: User | None = Depends(optional_user)) -> None:
        check(kind, request, user)
    dependency.__name__ = f"rate_limit_{kind}"
    return dependency


# ------------------------------------------------------------------ parallel photo analyses
_slots: threading.BoundedSemaphore | None = None
_slots_size = 0
_slots_lock = threading.Lock()


def _semaphore() -> threading.BoundedSemaphore:
    global _slots, _slots_size
    size = max(1, int(get_settings().max_concurrent_analyses))
    with _slots_lock:
        if _slots is None or _slots_size != size:
            _slots, _slots_size = threading.BoundedSemaphore(size), size
        return _slots


def analysis_guard(request: Request, user: User | None = Depends(optional_user)) -> Iterator[None]:
    """Rate limit first (cheap), then wait for one of the analysis slots so a burst cannot exhaust memory."""
    check("analysis", request, user)
    slots = _semaphore()
    if not slots.acquire(timeout=max(0.0, float(get_settings().analysis_queue_timeout_s))):
        raise HTTPException(status_code=503, headers={"Retry-After": "30"}, detail={
            "success": False, "error_code": "SERVER_BUSY",
            "message": "The server is busy analysing other photos. Please try again in a moment."})
    try:
        yield
    finally:
        slots.release()


# ------------------------------------------------------------------ request body size
class BodySizeLimit:
    """Pure ASGI middleware. Rejects a body larger than MAX_REQUEST_MB (multipart) or MAX_JSON_KB (anything else) from its
    Content-Length, before any of it is parsed. A body without Content-Length (chunked) is refused with 411; browsers always
    send the length for uploads and JSON, and the server (h11/httptools) enforces that the body matches it."""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            return await self.app(scope, receive, send)
        headers = dict(scope.get("headers") or [])
        s = get_settings()
        multipart = headers.get(b"content-type", b"").lower().startswith(b"multipart/form-data")
        limit = int(s.max_request_mb * 1024 * 1024) if multipart else int(s.max_json_kb) * 1024
        length = headers.get(b"content-length")
        if length is None:
            if b"transfer-encoding" in headers:
                return await _reject(send, 411, "LENGTH_REQUIRED", "The request must state its size (Content-Length).")
            return await self.app(scope, receive, send)  # no body
        try:
            size = int(length)
        except ValueError:
            return await _reject(send, 400, "INVALID_INPUT", "Invalid Content-Length header.")
        if size > limit:
            what = f"{s.max_request_mb:g} MB" if multipart else f"{s.max_json_kb:g} KB"
            return await _reject(send, 413, "REQUEST_TOO_LARGE", f"The request is larger than {what}. Please send smaller photos.")
        return await self.app(scope, receive, send)


async def _reject(send, status: int, code: str, message: str) -> None:
    body = json.dumps({"success": False, "error_code": code, "message": message}).encode()
    await send({"type": "http.response.start", "status": status, "headers": [
        (b"content-type", b"application/json"), (b"content-length", str(len(body)).encode()), (b"connection", b"close"),
        (b"x-content-type-options", b"nosniff")]})
    await send({"type": "http.response.body", "body": body})
