"""Signed-in features: scan history, food log / nutrition dashboard and recognition corrections.
Every query is scoped to the signed-in user (taken from the session, never from the request body)."""
from __future__ import annotations

import sqlite3
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.deps import User, current_user
from app.api.routes.analyze import error
from app.core.db import get_db, jdump, jload, now_iso
from app.services import analysis_store, history
from app.services import nutrients as N

router = APIRouter(prefix="/api", tags=["history & nutrition"])
Meal = Literal["breakfast", "lunch", "dinner", "snack", "other"]


# ================================================================== scan history
class SaveScanIn(BaseModel):
    analysis_id: str = Field(min_length=8, max_length=64)


def _scan_row(r: sqlite3.Row, full: bool = False) -> dict:
    d = {"id": r["id"], "kind": r["kind"], "title": r["title"], "created_at": r["created_at"], "summary": jload(r["summary"], {})}
    if full:
        d["details"] = jload(r["details"], {})
    return d


@router.post("/history", status_code=201)
def save_scan(body: SaveScanIn, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    """Manual save (analyses are also saved automatically for signed-in users; see app/services/history.py)."""
    existing = conn.execute("SELECT * FROM scans WHERE user_id = ? AND analysis_id = ?", (user.id, body.analysis_id)).fetchone()
    if existing:
        return {"success": True, "duplicate": True, "scan": _scan_row(existing)}
    item = analysis_store.get(body.analysis_id)
    if item is None:
        return error("ANALYSIS_EXPIRED", "This analysis is no longer available to save (it expires after 3 hours or a server restart). "
                     "Please analyse the photo again.", 410)
    scan, duplicate = history.save(conn, user.id, item["kind"], item["result"], body.analysis_id)
    return {"success": True, "duplicate": duplicate, "scan": scan}


@router.get("/history")
def list_scans(q: str | None = Query(None, max_length=100), kind: Literal["fresh", "packaged"] | None = None,
               date_from: date | None = None, date_to: date | None = None, page: int = Query(1, ge=1), page_size: int = Query(10, ge=1, le=50),
               user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    where, args = ["user_id = ?"], [user.id]
    if q:
        where.append("title LIKE ? ESCAPE '\\'")
        args.append("%" + q.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%")
    if kind:
        where.append("kind = ?"); args.append(kind)
    if date_from:
        where.append("substr(created_at, 1, 10) >= ?"); args.append(date_from.isoformat())
    if date_to:
        where.append("substr(created_at, 1, 10) <= ?"); args.append(date_to.isoformat())
    w = " AND ".join(where)
    total = conn.execute(f"SELECT COUNT(*) FROM scans WHERE {w}", args).fetchone()[0]  # noqa: S608 (fixed clauses, bound values)
    rows = conn.execute(f"SELECT * FROM scans WHERE {w} ORDER BY created_at DESC, id DESC LIMIT ? OFFSET ?",  # noqa: S608
                        (*args, page_size, (page - 1) * page_size)).fetchall()
    return {"success": True, "items": [_scan_row(r) for r in rows], "total": total, "page": page, "page_size": page_size}


def own_scan(conn: sqlite3.Connection, user_id: int, scan_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM scans WHERE id = ? AND user_id = ?", (scan_id, user_id)).fetchone()


@router.get("/history/{scan_id}")
def get_scan(scan_id: int, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    r = own_scan(conn, user.id, scan_id)
    if r is None:
        return error("NOT_FOUND", "That scan was not found in your history.", 404)
    return {"success": True, "scan": _scan_row(r, full=True)}


@router.delete("/history/{scan_id}")
def delete_scan(scan_id: int, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    with conn:
        n = conn.execute("DELETE FROM scans WHERE id = ? AND user_id = ?", (scan_id, user.id)).rowcount
    if not n:
        return error("NOT_FOUND", "That scan was not found in your history.", 404)
    return {"success": True}


# ================================================================== food log & dashboard
class EntryIn(BaseModel):
    logged_on: date
    meal: Meal = "other"
    scan_id: int | None = None
    grams: float | None = Field(default=None, gt=0, le=5000)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    nutrients: dict[str, float | None] | None = None  # manual entries: amounts for the portion eaten
    client_ref: str | None = Field(default=None, max_length=64)


class EntryPatch(BaseModel):
    logged_on: date | None = None
    meal: Meal | None = None
    grams: float | None = Field(default=None, gt=0, le=5000)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    nutrients: dict[str, float | None] | None = None


def _validate_manual(nut: dict[str, float | None] | None) -> tuple[dict | None, str | None]:
    if not nut:
        return None, "Enter at least one nutrient amount for a manual entry."
    bad = [k for k in nut if k not in N.CANONICAL]
    if bad:
        return None, f"Unknown nutrient key(s): {', '.join(bad)}."
    if any(v is not None and (v < 0 or v > 100000) for v in nut.values()):
        return None, "Nutrient amounts must be between 0 and 100000."
    return {k: v for k, v in nut.items()}, None


def _entry(r: sqlite3.Row) -> dict:
    n = jload(r["nutrients"], {})
    return {"id": r["id"], "logged_on": r["logged_on"], "meal": r["meal"], "name": r["name"], "grams": r["grams"], "source": r["source"],
            "provenance": r["provenance"], "scan_id": r["scan_id"], "amounts": n.get("amounts", {}), "per_100g": n.get("per100")}


@router.post("/nutrition/entries", status_code=201)
def add_entry(body: EntryIn, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    if body.client_ref:
        dup = conn.execute("SELECT * FROM food_log WHERE user_id = ? AND client_ref = ?", (user.id, body.client_ref)).fetchone()
        if dup:
            return {"success": True, "duplicate": True, "entry": _entry(dup)}
    if body.scan_id is not None:
        scan = conn.execute("SELECT * FROM scans WHERE id = ? AND user_id = ?", (body.scan_id, user.id)).fetchone()
        if scan is None:
            return error("NOT_FOUND", "That scan was not found in your history.", 404)
        s = jload(scan["summary"], {})
        per100 = (s.get("nutrition") or {}).get("per_100g")
        if not per100 or not s["nutrition"].get("basis_known"):
            return error("BASIS_UNKNOWN", "This scan has no per-100 g nutrition, so it cannot be scaled to a portion. Add it as a manual entry instead.", 422)
        if body.grams is None:
            return error("GRAMS_REQUIRED", "Enter how many grams you ate.", 422)
        amounts = N.scale(per100, body.grams)
        name, source, provenance = body.name or scan["title"], "scan", f"{s['nutrition'].get('provenance')}: {s['nutrition'].get('source')}"
        stored = {"per100": per100, "amounts": amounts}
    else:
        if not body.name:
            return error("NAME_REQUIRED", "Enter a name for the food.", 422)
        amounts, msg = _validate_manual(body.nutrients)
        if msg:
            return error("INVALID_NUTRIENTS", msg, 422)
        name, source, provenance, stored = body.name, "manual", "user-entered", {"per100": None, "amounts": amounts}
    with conn:
        cur = conn.execute(
            "INSERT INTO food_log (user_id, logged_on, meal, name, grams, source, provenance, scan_id, nutrients, client_ref, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (user.id, body.logged_on.isoformat(), body.meal, " ".join(name.split()), body.grams, source, provenance, body.scan_id,
             jdump(stored), body.client_ref, now_iso()))
    return {"success": True, "duplicate": False, "entry": _entry(conn.execute("SELECT * FROM food_log WHERE id = ?", (cur.lastrowid,)).fetchone())}


@router.patch("/nutrition/entries/{entry_id}")
def edit_entry(entry_id: int, body: EntryPatch, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    r = conn.execute("SELECT * FROM food_log WHERE id = ? AND user_id = ?", (entry_id, user.id)).fetchone()
    if r is None:
        return error("NOT_FOUND", "That entry was not found.", 404)
    stored = jload(r["nutrients"], {})
    grams = r["grams"]
    if body.grams is not None:
        grams = body.grams
        if stored.get("per100"):
            stored["amounts"] = N.scale(stored["per100"], grams)
    if body.nutrients is not None:
        if r["source"] != "manual":
            return error("NOT_EDITABLE", "Nutrients of a scan-based entry come from the scan; change the grams instead.", 422)
        amounts, msg = _validate_manual(body.nutrients)
        if msg:
            return error("INVALID_NUTRIENTS", msg, 422)
        stored["amounts"] = amounts
    with conn:
        conn.execute("UPDATE food_log SET logged_on = ?, meal = ?, name = ?, grams = ?, nutrients = ? WHERE id = ? AND user_id = ?",
                     ((body.logged_on or date.fromisoformat(r["logged_on"])).isoformat(), body.meal or r["meal"],
                      " ".join((body.name or r["name"]).split()), grams, jdump(stored), entry_id, user.id))
    return {"success": True, "entry": _entry(conn.execute("SELECT * FROM food_log WHERE id = ?", (entry_id,)).fetchone())}


@router.delete("/nutrition/entries/{entry_id}")
def delete_entry(entry_id: int, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    with conn:
        n = conn.execute("DELETE FROM food_log WHERE id = ? AND user_id = ?", (entry_id, user.id)).rowcount
    return {"success": True} if n else error("NOT_FOUND", "That entry was not found.", 404)


def totals(entries: list[dict], keys: list[str] | None = None) -> list[dict]:
    keys = keys or list(N.CANONICAL)
    out = []
    for k in keys:
        known = [e["amounts"][k] for e in entries if e["amounts"].get(k) is not None]
        missing = len(entries) - len(known)
        out.append({"key": k, "label": N.CANONICAL[k][0], "unit": N.CANONICAL[k][1],
                    "total": round(sum(known), 2) if known else None, "entries_with_value": len(known), "entries_missing": missing,
                    "complete": missing == 0 and bool(entries)})
    return out


def day_entries(conn: sqlite3.Connection, user_id: int, d: date) -> list[dict]:
    return [_entry(r) for r in conn.execute("SELECT * FROM food_log WHERE user_id = ? AND logged_on = ? ORDER BY created_at", (user_id, d.isoformat()))]


@router.get("/nutrition/day")
def nutrition_day(day: date = Query(default_factory=date.today), user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    entries = day_entries(conn, user.id, day)
    return {"success": True, "date": day.isoformat(), "entries": entries, "totals": totals(entries),
            "notes": ["Totals add only the values that are known. 'Incomplete' means some entries have no value for that nutrient, "
                      "so the real total is higher than shown.",
                      "Reference values describe a typical food, not the exact item you ate."]}


@router.get("/nutrition/week")
def nutrition_week(end: date = Query(default_factory=date.today), user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    days = []
    for i in range(6, -1, -1):
        d = end - timedelta(days=i)
        e = day_entries(conn, user.id, d)
        days.append({"date": d.isoformat(), "entry_count": len(e), "totals": totals(e, N.DASHBOARD_KEYS)})
    return {"success": True, "start": (end - timedelta(days=6)).isoformat(), "end": end.isoformat(), "days": days}


# ================================================================== corrections (review queue, not training data)
class CorrectionIn(BaseModel):
    scan_id: int | None = None
    predicted: str | None = Field(default=None, max_length=100)
    corrected: str | None = Field(default=None, max_length=100)
    not_recognized: bool = False
    note: str | None = Field(default=None, max_length=500)


@router.post("/corrections", status_code=201)
def add_correction(body: CorrectionIn, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    if body.scan_id is not None and own_scan(conn, user.id, body.scan_id) is None:
        return error("NOT_FOUND", "That scan was not found in your history.", 404)
    if not body.corrected and not body.not_recognized:
        return error("INVALID_CORRECTION", "Choose the correct food or mark the image as not recognised.", 422)
    with conn:
        cur = conn.execute("INSERT INTO corrections (user_id, scan_id, predicted, corrected, not_recognized, note, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                           (user.id, body.scan_id, body.predicted, body.corrected, int(body.not_recognized), body.note, now_iso()))
    return {"success": True, "id": cur.lastrowid, "status": "pending_review",
            "message": "Thank you. Corrections are reviewed before they are ever used for training."}


@router.get("/corrections")
def my_corrections(user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    rows = conn.execute("SELECT * FROM corrections WHERE user_id = ? ORDER BY created_at DESC LIMIT 100", (user.id,)).fetchall()
    return {"success": True, "items": [dict(r) for r in rows]}
