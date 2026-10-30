"""Abuse limits for a public deployment: request rate limits per account / per client IP, and global daily caps on
paid provider requests (OpenAI, Gemini, Google Vision, the chatbot).

Counters are fixed time windows (hour / UTC day) in their own SQLite file, so they survive restarts and never touch the
accounts, history or cache databases. Client IPs are never stored: only a salted hash (IPv6 grouped by /64 prefix, so one
connection cannot rotate addresses inside its own network). Standard library only.
"""
from __future__ import annotations

import hashlib
import ipaddress
import logging
import secrets
import sqlite3
import threading
import time
from pathlib import Path

from app.core.config import BACKEND_DIR, get_settings

log = logging.getLogger("smartplate.limits")
HOUR, DAY = 3600, 86400
TRUE, FALSE = {"1", "true", "yes", "on"}, {"0", "false", "no", "off"}
# Provider label used by the routes -> counter name and the setting holding its daily cap.
PROVIDER_CAPS = {"openai": "openai_daily_limit", "gemini": "gemini_daily_limit",
                 "google_vision": "google_vision_daily_limit", "chat": "chat_daily_limit"}
PROVIDER_KEYS = {"OpenAI Vision": "openai", "Google Gemini": "gemini"}
DAILY_LIMIT_REACHED = "daily_limit_reached"

_lock = threading.Lock()
_ready: dict[str, str] = {}  # database path -> salt


def production() -> bool:
    return get_settings().environment.strip().lower() in {"production", "prod"}


def _switch(value: str) -> bool:
    v = (value or "").strip().lower()
    if v in TRUE:
        return True
    if v in FALSE:
        return False
    return production() if v in ("", "auto") else True  # an unrecognised value fails safe (on)


def rate_limits_enabled() -> bool:
    return _switch(get_settings().rate_limits_enabled)


def paid_requires_login() -> bool:
    return _switch(get_settings().paid_providers_require_login)


def paid_allowed(user: object | None) -> bool:
    """May this request trigger paid provider calls? Signed-in users always; anonymous ones only when sign-in is not required."""
    return user is not None or not paid_requires_login()


def db_path() -> Path:
    s = get_settings()
    if s.usage_database_path.strip():
        return Path(s.usage_database_path)
    main = Path(s.database_path) if s.database_path else BACKEND_DIR / "data" / "smartplate.db"
    return main.with_name("smartplate_usage.db")


def _connect() -> tuple[sqlite3.Connection, str]:
    path = db_path()
    key = str(path)
    if key not in _ready:
        with _lock:
            if key not in _ready:
                path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(path, timeout=10)
                try:
                    with conn:
                        conn.executescript("""
                            CREATE TABLE IF NOT EXISTS counters (
                                bucket TEXT NOT NULL, window_start INTEGER NOT NULL, count INTEGER NOT NULL,
                                PRIMARY KEY (bucket, window_start));
                            CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);""")
                        conn.execute("INSERT OR IGNORE INTO meta VALUES ('salt', ?)", (secrets.token_hex(16),))
                    _ready[key] = conn.execute("SELECT value FROM meta WHERE key = 'salt'").fetchone()[0]
                finally:
                    conn.close()
    return sqlite3.connect(path, timeout=10, isolation_level=None), _ready[key]


def consume(rules: list[tuple[str, int, int]], now: float | None = None) -> int | None:
    """Count one use against every (bucket, limit, window_seconds) rule, atomically. If any rule is already at its limit,
    nothing is counted and the seconds until the blocking window ends are returned; otherwise None."""
    t = int(time.time() if now is None else now)
    conn, _ = _connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        wait = None
        for bucket, limit, window in rules:
            start = t - t % window
            row = conn.execute("SELECT count FROM counters WHERE bucket = ? AND window_start = ?", (bucket, start)).fetchone()
            if (row[0] if row else 0) >= limit:
                wait = max(wait or 1, start + window - t)
        if wait is None:
            for bucket, _limit, window in rules:
                conn.execute("INSERT INTO counters VALUES (?, ?, 1) ON CONFLICT (bucket, window_start) DO UPDATE SET count = count + 1",
                             (bucket, t - t % window))
            if secrets.randbelow(200) == 0:  # occasional clean-up of finished windows
                conn.execute("DELETE FROM counters WHERE window_start < ?", (t - 2 * DAY,))
        conn.execute("COMMIT")
        return wait
    except BaseException:
        if conn.in_transaction:
            conn.execute("ROLLBACK")
        raise
    finally:
        conn.close()


def used(bucket: str, window: int, now: float | None = None) -> int:
    t = int(time.time() if now is None else now)
    conn, _ = _connect()
    try:
        row = conn.execute("SELECT count FROM counters WHERE bucket = ? AND window_start = ?", (bucket, t - t % window)).fetchone()
        return row[0] if row else 0
    finally:
        conn.close()


def client_key(host: str | None) -> str:
    """Salted hash of the client address (never the address itself). IPv6 is grouped by its /64 network."""
    host = (host or "unknown").strip()
    try:
        ip = ipaddress.ip_address(host)
        if ip.version == 6:
            host = str(ip.ipv4_mapped) if ip.ipv4_mapped else str(ipaddress.ip_network(f"{ip}/64", strict=False))
    except ValueError:
        pass
    _, salt = _connect()
    return hashlib.sha256(f"{salt}|{host}".encode()).hexdigest()[:20]


def provider_call_allowed(provider: str) -> bool:
    """Reserve one request against the provider's global daily cap. False = cap reached (or the counter store failed:
    paid calls fail closed). Call it immediately before the provider request, and only on a cache miss."""
    limit = int(getattr(get_settings(), PROVIDER_CAPS[provider]))
    try:
        blocked = consume([(f"provider:{provider}", limit, DAY)])
    except Exception as exc:  # noqa: BLE001
        log.error("usage counter unavailable (%s); %s calls blocked", type(exc).__name__, provider)
        return False
    if blocked is not None:
        log.warning("daily cap reached provider=%s limit=%d", provider, limit)
        return False
    return True
