"""Evaluate the packaged-food pipeline on real label photos (data_eval/packaged, from Open Food Facts).

Runs each product through the real POST /api/analyze/packaged (Tesseract, barcode detection, local dataset, Open Food Facts
lookup) and compares with OFF's contributor-entered reference. By default the paid AI label readers (OpenAI, Gemini) are
switched off for this process only (.env is not changed); pass --allow-ai-readers to use the configured providers.

    python scripts/eval_packaged_labels.py [--out report.json] [--allow-ai-readers]

A nutrient counts as "correct" when the value read from the label is within 5% (or 0.5 units) of OFF's per-100 g value and the
label column was per 100 g/ml. OFF values are crowd-sourced, so a mismatch can also be an OFF error: check the photo.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DATA = BACKEND / "data_eval" / "packaged"


def close(a: float, b: float) -> bool:
    return abs(a - b) <= max(0.5, 0.05 * max(abs(a), abs(b)))


def tokens(s: str | None) -> set[str]:
    import re
    return {t for t in re.findall(r"[a-z]{3,}", (s or "").lower())}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--allow-ai-readers", action="store_true")
    ap.add_argument("--only", default=None, help="comma-separated barcodes")
    args = ap.parse_args()
    if not args.allow_ai_readers:
        os.environ["OPENAI_VISION_ENABLED"] = "false"
        os.environ["GEMINI_VISION_ENABLED"] = "false"
    # A throw-away database, so an evaluation never writes cache rows or anything else into backend/data/smartplate.db.
    import tempfile  # noqa: PLC0415
    tmp = tempfile.mkdtemp(prefix="smartplate_eval_")
    os.environ.setdefault("DATABASE_PATH", os.path.join(tmp, "eval.db"))
    os.environ.setdefault("AUTH_DATABASE_PATH", os.path.join(tmp, "eval_users.db"))
    sys.path.insert(0, str(BACKEND))
    from fastapi.testclient import TestClient  # noqa: PLC0415
    from app.main import app  # noqa: PLC0415

    client = TestClient(app)
    manifest = json.loads((DATA / "MANIFEST.json").read_text(encoding="utf-8"))
    if args.only:
        manifest = [m for m in manifest if m["barcode"] in args.only.split(",")]
    rows = []
    for m in manifest:
        d = DATA / m["barcode"]
        files = {"front": ("front.jpg", (d / "front.jpg").read_bytes(), "image/jpeg"),
                 "back": ("nutrition.jpg", (d / "nutrition.jpg").read_bytes(), "image/jpeg"),
                 "closeup": ("ingredients.jpg", (d / "ingredients.jpg").read_bytes(), "image/jpeg")}
        t0 = time.time()
        r = client.post("/api/analyze/packaged", files=files)
        secs = round(time.time() - t0, 1)
        j = r.json()
        row = {"barcode": m["barcode"], "product": m["product_name"], "http": r.status_code, "seconds": secs,
               "error_code": j.get("error_code")}
        if j.get("success"):
            ln = j.get("label_nutrition") or {}
            got = {x["key"]: x["value"] for x in ln.get("rows", []) if x.get("value") is not None}
            ai_got = {x["key"]: x["ai_value"] for x in ln.get("rows", []) if x.get("ai_value") is not None}
            basis = ln.get("basis")
            ref = dict(m["reference_per_100g"])
            if "sodium_g" in ref:
                ref["sodium_mg"] = ref.pop("sodium_g") * 1000
            compared = {}
            for k, v in ref.items():
                if k not in got:
                    compared[k] = "missing"
                elif basis not in ("per 100 g", "per 100 ml"):
                    compared[k] = f"basis:{basis}"
                else:
                    compared[k] = "correct" if close(got[k], v) else f"wrong (read {got[k]}, ref {round(v, 2)})"
            ai_compared = {k: ("missing" if k not in ai_got else "correct" if close(ai_got[k], v) else
                               f"wrong (read {ai_got[k]}, ref {round(v, 2)})") for k, v in ref.items()} if ai_got else None
            ident = j.get("identification") or {}
            ingr_ref, ingr_got = tokens(m.get("ingredients_text")), tokens((j.get("label") or {}).get("ingredients_text"))
            row.update({
                "barcode_detected": (j.get("barcode_detection") or {}).get("code"),
                "barcode_correct": (j.get("barcode_detection") or {}).get("code") == m["barcode"],
                "identification": ident.get("status"), "identified_as": ident.get("name") or ident.get("product_name"),
                "identified_source": ident.get("source"),
                "label_basis": basis, "nutrients": compared, "ai_reader_values": ai_compared,
                "ai_reader": (j.get("package_reading") or {}).get("provider"),
                "ingredients_found": bool(ingr_got),
                "ingredients_token_recall": round(len(ingr_ref & ingr_got) / len(ingr_ref), 2) if ingr_ref else None,
                "ocr_quality": (j.get("ocr") or {}).get("quality"), "ocr_words": (j.get("ocr") or {}).get("word_count"),
                "warnings": j.get("warnings", []),
            })
        rows.append(row)
        print(json.dumps({k: row.get(k) for k in ("barcode", "product", "seconds", "error_code", "barcode_correct", "identification",
                                                   "identified_as", "label_basis", "ingredients_token_recall")}, ensure_ascii=True))
        print("   nutrients:", json.dumps(row.get("nutrients"), ensure_ascii=True))
    ok = [r for r in rows if r.get("nutrients") is not None]
    vals = [v for r in ok for v in r["nutrients"].values()]
    summary = {
        "products": len(rows), "analysed": len(ok), "errors": {r["barcode"]: r["error_code"] for r in rows if r.get("error_code")},
        "barcode_correct": sum(bool(r.get("barcode_correct")) for r in rows),
        "identified": sum(r.get("identification") == "identified" for r in rows),
        "nutrient_values": {"compared": len(vals), "correct": sum(v == "correct" for v in vals),
                            "wrong": sum(str(v).startswith("wrong") for v in vals), "missing": sum(v == "missing" for v in vals),
                            "other_basis": sum(str(v).startswith("basis") for v in vals)},
        "ingredients_found": sum(bool(r.get("ingredients_found")) for r in ok),
        "ai_readers": "allowed" if args.allow_ai_readers else "disabled (Tesseract only)",
        "median_seconds": sorted(r["seconds"] for r in rows)[len(rows) // 2] if rows else None,
    }
    print(json.dumps(summary, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": summary, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")


if __name__ == "__main__":
    main()
