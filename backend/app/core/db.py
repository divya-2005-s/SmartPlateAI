"""SQLite database (Python standard library only) with versioned, additive migrations.

The file lives at backend/data/smartplate.db by default (DATABASE_PATH overrides it). Migrations only ever add
tables, columns and indexes, so existing user records are preserved. Each request gets its own connection.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterator
from datetime import datetime, timezone
from pathlib import Path

from app.core.config import BACKEND_DIR, get_settings

_init_lock = threading.Lock()
_initialised: set[str] = set()

MIGRATIONS: list[tuple[int, str, str]] = [
    (1, "accounts, sessions and allergen preferences", """
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            email TEXT NOT NULL UNIQUE COLLATE NOCASE,
            name TEXT NOT NULL,
            password_hash TEXT NOT NULL,
            birth_year INTEGER,
            dietary_preferences TEXT NOT NULL DEFAULT '[]',
            disliked_foods TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS sessions (
            token_hash TEXT PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions(user_id);
        CREATE TABLE IF NOT EXISTS allergen_prefs (
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            allergen TEXT NOT NULL,
            severity TEXT NOT NULL DEFAULT 'avoid',
            PRIMARY KEY (user_id, allergen)
        );
    """),
    (2, "scan history, food log and corrections", """
        CREATE TABLE IF NOT EXISTS scans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            analysis_id TEXT NOT NULL,
            kind TEXT NOT NULL CHECK (kind IN ('fresh', 'packaged')),
            title TEXT NOT NULL,
            summary TEXT NOT NULL,
            details TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE (user_id, analysis_id)
        );
        CREATE INDEX IF NOT EXISTS ix_scans_user_time ON scans(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS food_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            logged_on TEXT NOT NULL,
            meal TEXT NOT NULL DEFAULT 'other',
            name TEXT NOT NULL,
            grams REAL,
            source TEXT NOT NULL,
            provenance TEXT NOT NULL,
            scan_id INTEGER REFERENCES scans(id) ON DELETE SET NULL,
            nutrients TEXT NOT NULL,
            client_ref TEXT,
            created_at TEXT NOT NULL,
            UNIQUE (user_id, client_ref)
        );
        CREATE INDEX IF NOT EXISTS ix_food_log_user_day ON food_log(user_id, logged_on);
        CREATE TABLE IF NOT EXISTS corrections (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            scan_id INTEGER REFERENCES scans(id) ON DELETE SET NULL,
            predicted TEXT,
            corrected TEXT,
            not_recognized INTEGER NOT NULL DEFAULT 0,
            note TEXT,
            status TEXT NOT NULL DEFAULT 'pending_review',
            created_at TEXT NOT NULL
        );
    """),
    (3, "meal plans and external-data cache", """
        CREATE TABLE IF NOT EXISTS meal_plans (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            title TEXT NOT NULL,
            request TEXT NOT NULL,
            plan TEXT NOT NULL,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS ix_meal_plans_user ON meal_plans(user_id, created_at DESC);
        CREATE TABLE IF NOT EXISTS http_cache (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL,
            expires_at TEXT NOT NULL
        );
    """),
]


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def db_path() -> Path:
    configured = get_settings().database_path
    return Path(configured) if configured else BACKEND_DIR / "data" / "smartplate.db"


def connect(path: Path | None = None) -> sqlite3.Connection:
    path = path or db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=10, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    key = str(path.resolve())
    if key not in _initialised:
        with _init_lock:
            if key not in _initialised:
                migrate(conn)
                _initialised.add(key)
    return conn


def migrate(conn: sqlite3.Connection) -> list[int]:
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations (version INTEGER PRIMARY KEY, name TEXT NOT NULL, applied_at TEXT NOT NULL)")
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    applied = []
    for version, name, sql in MIGRATIONS:
        if version in done:
            continue
        with conn:  # one transaction per migration
            for stmt in [s for s in sql.split(";") if s.strip()]:
                conn.execute(stmt)
            conn.execute("INSERT INTO schema_migrations (version, name, applied_at) VALUES (?, ?, ?)", (version, name, now_iso()))
        applied.append(version)
    return applied


def get_db() -> Iterator[sqlite3.Connection]:
    """FastAPI dependency: one connection per request."""
    conn = connect()
    try:
        yield conn
    finally:
        conn.close()


def jdump(v) -> str:
    return json.dumps(v, ensure_ascii=False, default=str, separators=(",", ":"))


def jload(s: str | None, default=None):
    if not s:
        return default
    try:
        return json.loads(s)
    except ValueError:
        return default
