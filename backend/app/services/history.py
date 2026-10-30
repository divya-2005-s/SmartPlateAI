"""Persist successful analyses to the `scans` table (SQLite), owned by the signed-in user.

Used automatically by the analysis endpoints when a user is signed in (cookie or bearer session), and by
POST /api/history. Duplicate protection: the UNIQUE (user_id, analysis_id) constraint. The analysis id is the
client's Idempotency-Key header when given (so a retried request maps to the same row), otherwise the server's id.
Failed analyses are never passed here.
"""
from __future__ import annotations

import logging
import re
import sqlite3

from app.core.db import connect, jdump, jload, now_iso
from app.services.scan_summary import summarise

log = logging.getLogger("smartplate.history")
_KEY = re.compile(r"^[A-Za-z0-9_.:-]{8,64}$")


def clean_key(raw: str | None) -> str | None:
    """Accept only a safe idempotency key (e.g. a UUID); anything else is ignored."""
    return raw if raw and _KEY.fullmatch(raw) else None


def row_view(r: sqlite3.Row, full: bool = False) -> dict:
    d = {"id": r["id"], "kind": r["kind"], "title": r["title"], "created_at": r["created_at"], "summary": jload(r["summary"], {})}
    if full:
        d["details"] = jload(r["details"], {})
    return d


def save(conn: sqlite3.Connection, user_id: int, kind: str, result: dict, analysis_id: str) -> tuple[dict, bool]:
    """Insert one scan. Returns (scan, duplicate)."""
    existing = conn.execute("SELECT * FROM scans WHERE user_id = ? AND analysis_id = ?", (user_id, analysis_id)).fetchone()
    if existing:
        return row_view(existing), True
    summary = summarise(kind, result)
    details = {k: v for k, v in result.items() if k not in ("history",)}
    try:
        with conn:
            cur = conn.execute(
                "INSERT INTO scans (user_id, analysis_id, kind, title, summary, details, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (user_id, analysis_id, kind, summary["title"][:200], jdump(summary), jdump(details), now_iso()))
    except sqlite3.IntegrityError:  # a concurrent retry inserted the same key first
        existing = conn.execute("SELECT * FROM scans WHERE user_id = ? AND analysis_id = ?", (user_id, analysis_id)).fetchone()
        return row_view(existing), True
    return row_view(conn.execute("SELECT * FROM scans WHERE id = ?", (cur.lastrowid,)).fetchone()), False


def autosave(user, kind: str, result: dict, analysis_id: str, idempotency_key: str | None = None) -> dict:
    """Best-effort automatic save for a successful analysis. Never raises; reports the outcome to the client."""
    if user is None:
        return {"saved": False, "reason": "not_signed_in", "message": "Sign in to save analyses to your history automatically."}
    key = f"req:{idempotency_key}" if idempotency_key else analysis_id
    conn = connect()
    try:
        scan, dup = save(conn, user.id, kind, result, key)
        return {"saved": True, "scan_id": scan["id"], "duplicate": dup}
    except Exception:  # noqa: BLE001 - the analysis itself succeeded; report the storage failure honestly
        log.exception("history autosave failed")
        return {"saved": False, "reason": "storage_error", "message": "The analysis worked, but it could not be saved to your history. Try 'Save to history' again."}
    finally:
        conn.close()
