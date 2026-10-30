"""PDF downloads, generated from the signed-in user's own saved records only."""
from __future__ import annotations

import re
import sqlite3
from datetime import date, timedelta
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response

from app.api.deps import User, current_user
from app.api.routes.analyze import error, get_nutrition
from app.api.routes.user_data import day_entries, own_scan, totals
from app.core.db import get_db, jload
from app.services import nutrients as N
from app.services.nutrition import NutritionReference
from app.services.reports import nutrition_report, scan_report

router = APIRouter(prefix="/api/reports", tags=["reports"])


def _pdf(data: bytes, name: str) -> Response:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:80]
    return Response(content=data, media_type="application/pdf", headers={"Content-Disposition": f'attachment; filename="{safe}"'})


@router.get("/scans/{scan_id}")
def scan_pdf(scan_id: int, chemical: bool = True, user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db),
             nutrition: NutritionReference = Depends(get_nutrition)):
    r = own_scan(conn, user.id, scan_id)
    if r is None:
        return error("NOT_FOUND", "That scan was not found in your history.", 404)
    scan = {"id": r["id"], "created_at": r["created_at"], "summary": jload(r["summary"], {}), "details": jload(r["details"], {})}
    chem = None
    if chemical and scan["summary"].get("kind") == "fresh":
        from app.services.chemistry import chemical_profile  # noqa: PLC0415
        food = scan["summary"]["identity"]["food"]
        chem = chemical_profile(food, scan["details"].get("nutrition") or nutrition.lookup(food))
    return _pdf(scan_report(scan, chem), f"SmartPlateAI_{scan['summary']['title']}_{scan_id}.pdf")


@router.get("/nutrition")
def nutrition_pdf(period: Literal["day", "week"] = "day", day: date = Query(default_factory=date.today),
                  user: User = Depends(current_user), conn: sqlite3.Connection = Depends(get_db)):
    n = 1 if period == "day" else 7
    days = []
    for i in range(n - 1, -1, -1):
        d = day - timedelta(days=i)
        e = day_entries(conn, user.id, d)
        days.append({"date": d.isoformat(), "entry_count": len(e), "entries": e, "totals": totals(e, N.DASHBOARD_KEYS)})
    label = day.isoformat() if n == 1 else f"{(day - timedelta(days=6)).isoformat()} to {day.isoformat()}"
    return _pdf(nutrition_report(user["name"], label, days), f"SmartPlateAI_nutrition_{period}_{day.isoformat()}.pdf")
