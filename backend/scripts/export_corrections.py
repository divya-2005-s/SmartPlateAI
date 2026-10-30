"""Export user corrections for manual review (they are NOT training data until a person has checked each one).

  .\\.venv\\Scripts\\python.exe scripts\\export_corrections.py
Writes reports/corrections_for_review.csv (no emails or passwords; users are identified by an anonymous number).
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

from app.core.db import connect  # noqa: E402


def main() -> None:
    conn = connect()
    rows = conn.execute("SELECT c.id, c.user_id, c.scan_id, c.predicted, c.corrected, c.not_recognized, c.note, c.status, c.created_at, s.title "
                        "FROM corrections c LEFT JOIN scans s ON s.id = c.scan_id ORDER BY c.created_at").fetchall()
    out = BACKEND_DIR / "reports" / "corrections_for_review.csv"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["id", "user", "scan_id", "scan_title", "predicted", "corrected", "not_recognized", "note", "status", "created_at"])
        for r in rows:
            w.writerow([r["id"], f"user-{r['user_id']}", r["scan_id"], r["title"], r["predicted"], r["corrected"], bool(r["not_recognized"]),
                        r["note"], r["status"], r["created_at"]])
    print(f"{len(rows)} corrections -> {out}")


if __name__ == "__main__":
    main()
