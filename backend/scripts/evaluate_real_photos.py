"""Real-world evaluation: run YOUR labelled photos through the real SmartPlateAI pipeline and record every result.

Folder layout (see docs/REAL_WORLD_EVALUATION.md):
  <root>/recognition/<expected food>/*.jpg            e.g. recognition/Milk/glass1.jpg, recognition/Apple/a1.jpg
  <root>/freshness/<food>/<fresh|rotten>/*.jpg        only the 14 freshness foods are scored
  <root>/nutrition_expected.csv  (optional)           columns: expected_food,expected_record  (USDA description to expect)

  cd D:\\SmartPlateAI\\backend
  .\\.venv\\Scripts\\python.exe scripts\\evaluate_real_photos.py D:\\SmartPlateAI\\real_eval
  (add --image-model-only to switch OpenAI/Gemini off for a baseline; --delay 4 spaces provider calls)

Writes <root>/results_<time>.csv (one row per photo) and <root>/summary_<time>.json. Uses the configured providers, so
OpenAI/Gemini calls are made (and billed) once per photo. Never tune the models or thresholds on these photos and then
report results on the same photos: keep a separate tuning set.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

BACKEND_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND_DIR))

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
FIELDS = ["set", "file", "expected", "expected_condition", "outcome", "predicted", "correct", "source", "provider", "score_percent",
          "requires_confirmation", "reason", "freshness", "freshness_confidence", "freshness_correct", "nutrition_record",
          "nutrition_correct", "quality", "quality_issues", "seconds", "failure_note"]


def words(text: str) -> set[str]:
    out = set()
    for w in re.findall(r"[a-z]+", (text or "").lower()):
        out.add(w[:-1] if w.endswith("s") and len(w) > 3 else w)
    return out


def name_matches(expected: str, predicted: str | None) -> bool:
    """'Milk' matches 'Whole milk' and 'Apple' matches 'apple': every word of the expected label must appear."""
    return bool(predicted) and words(expected) <= words(predicted)


def photos(folder: Path) -> list[Path]:
    return sorted(p for p in folder.rglob("*") if p.suffix.lower() in IMAGE_EXT) if folder.is_dir() else []


def run_one(client, path: Path) -> tuple[dict, float]:
    t0 = time.time()
    r = client.post("/api/analyze/food", files={"file": (path.name, path.read_bytes(), "image/jpeg")})
    return r.json(), time.time() - t0


def row_for(j: dict) -> dict:
    ok = j.get("success") is True
    ident, pred, fr = j.get("identification") or {}, j.get("prediction") or {}, j.get("freshness") or {}
    q = j.get("image_quality") or {}
    nut = j.get("nutrition") or {}
    return {
        "outcome": "accepted" if ok and not j.get("requires_confirmation") else "accepted_needs_confirmation" if ok else j.get("error_code"),
        "predicted": pred.get("food") if ok else ((j.get("general_candidate") or {}).get("food") or
                                                   ((j.get("candidates") or [{}])[0].get("food") if j.get("candidates") else None)),
        "source": ident.get("source"), "provider": ident.get("provider") or (j.get("openai_vision") or {}).get("provider"),
        "score_percent": pred.get("confidence_percent") if ok else j.get("confidence_percent"),
        "requires_confirmation": j.get("requires_confirmation"), "reason": j.get("reason") or (j.get("openai_vision") or {}).get("reason"),
        "freshness": fr.get("status"), "freshness_confidence": fr.get("confidence"),
        "nutrition_record": nut.get("matched_description") or (nut.get("reference") or {}).get("food"),
        "quality": q.get("level"), "quality_issues": ";".join(q.get("issues") or []),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("root", type=Path)
    ap.add_argument("--image-model-only", action="store_true", help="switch OpenAI and Gemini off (baseline)")
    ap.add_argument("--delay", type=float, default=0.0, help="seconds between photos (provider rate limits)")
    a = ap.parse_args()
    if a.image_model_only:
        os.environ.update({"OPENAI_VISION_ENABLED": "false", "GEMINI_VISION_ENABLED": "false"})
    from fastapi.testclient import TestClient  # noqa: PLC0415  (after the environment is set)

    from app.main import app  # noqa: PLC0415
    client = TestClient(app)
    expected_records = {}
    nfile = a.root / "nutrition_expected.csv"
    if nfile.is_file():
        with open(nfile, encoding="utf-8") as f:
            expected_records = {r["expected_food"].strip().casefold(): r["expected_record"].strip() for r in csv.DictReader(f)}

    jobs = [("recognition", p, p.relative_to(a.root / "recognition").parts[0], "") for p in photos(a.root / "recognition")]
    for p in photos(a.root / "freshness"):
        parts = p.relative_to(a.root / "freshness").parts
        if len(parts) >= 3 and parts[1].lower() in ("fresh", "rotten"):
            jobs.append(("freshness", p, parts[0], parts[1].lower()))
    if not jobs:
        sys.exit(f"No photos found under {a.root}\\recognition or {a.root}\\freshness (see docs/REAL_WORLD_EVALUATION.md).")

    rows = []
    for i, (kind, path, expected, cond) in enumerate(jobs, 1):
        try:
            j, secs = run_one(client, path)
            row = {"set": kind, "file": str(path), "expected": expected, "expected_condition": cond, **row_for(j), "seconds": round(secs, 1)}
        except Exception as exc:  # noqa: BLE001
            row = {"set": kind, "file": str(path), "expected": expected, "expected_condition": cond, "outcome": "script_error",
                   "failure_note": type(exc).__name__}
        row["correct"] = name_matches(expected, row.get("predicted"))
        if cond and row.get("freshness") in ("fresh", "possibly_spoiled"):
            row["freshness_correct"] = (row["freshness"] == "fresh") == (cond == "fresh")
        want = expected_records.get(expected.casefold())
        if want and row.get("nutrition_record"):
            row["nutrition_correct"] = row["nutrition_record"].casefold() == want.casefold()
        if not row.get("failure_note"):
            row["failure_note"] = ("wrong food accepted without asking" if row["outcome"] == "accepted" and not row["correct"] else
                                   "asked to confirm" if row["outcome"] in ("LOW_CONFIDENCE", "accepted_needs_confirmation") else
                                   "" if row["outcome"] == "accepted" else f"not identified ({row['outcome']})")
        rows.append(row)
        print(f"[{i}/{len(jobs)}] {kind:11} {expected:18} -> {row.get('outcome')}: {row.get('predicted')} "
              f"({'ok' if row['correct'] else 'WRONG'}) freshness={row.get('freshness')}")
        if a.delay:
            time.sleep(a.delay)

    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    with open(a.root / f"results_{stamp}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)
    rec = [r for r in rows if r["set"] == "recognition"]
    acc = [r for r in rec if r["outcome"] == "accepted"]
    fr = [r for r in rows if r.get("freshness_correct") is not None]
    summary = {
        "photos": len(rows), "image_model_only": a.image_model_only,
        "recognition": {"n": len(rec), "accepted_automatically": len(acc),
                        "correct_when_accepted": sum(r["correct"] for r in acc),
                        "wrong_but_accepted_without_asking": sum(not r["correct"] for r in acc),
                        "asked_to_confirm": sum(r["outcome"] in ("LOW_CONFIDENCE", "accepted_needs_confirmation") for r in rec),
                        "correct_food_named_in_any_outcome": sum(r["correct"] for r in rec)},
        "freshness": {"n_with_expected_condition": sum(1 for r in rows if r["set"] == "freshness"), "assessed": len(fr),
                      "correct_when_assessed": sum(r["freshness_correct"] for r in fr)},
        "nutrition": {"checked": sum(r.get("nutrition_correct") is not None for r in rows),
                      "correct_record": sum(r.get("nutrition_correct") is True for r in rows)},
        "note": "Counts from the photos supplied; small samples have wide uncertainty. Not usable for tuning AND reporting.",
    }
    (a.root / f"summary_{stamp}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
