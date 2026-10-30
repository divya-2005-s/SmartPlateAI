"""Offline evaluation of the food / non-food / packaged-product decision on every local evaluation set (image model only:
no OpenAI, Gemini or Google Vision calls, no database writes).

Sets (each image keeps its source/licence in the folder's ATTRIBUTION.csv or MANIFEST.json):
  supported_test        held-out photos of the 24 classes (data_prep/split_manifest.csv, 15 per class, seed 7)
  food_in_context       supported foods held/eaten by people          data_eval/food_in_context
  food_with_packaging   unwrapped food next to its packaging          data_eval/food_with_packaging
  unsupported_food      food outside the 24 classes                   data_eval/unsupported_food
  packaged_food         package fronts (Open Food Facts)              data_eval/packaged
  food_packaging_closed closed take-away boxes/sacks, no food visible data_eval/food_packaging_closed
  non_food              people, phones, laptops, scenery, ...         data_nonfood/general
  non_food_packaged     medicine, cosmetics, toiletries, boxes        data_nonfood/packaged_objects

    python scripts/eval_food_gate.py --out report.json
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def load_sets(per_class: int) -> dict[str, list[tuple[Path, str]]]:
    import pandas as pd
    sets: dict[str, list[tuple[Path, str]]] = {}
    m = pd.read_csv(BACKEND / "data_prep" / "split_manifest.csv", low_memory=False)
    t = m[(m.new_split == "test") & (~m.is_augmented_copy.astype(bool))]
    sets["supported_test"] = [(Path(p), f) for f, g in t.groupby("food") for p in g.sample(min(len(g), per_class), random_state=7).image_path]
    for name, folder in [("food_in_context", "data_eval/food_in_context"), ("food_with_packaging", "data_eval/food_with_packaging"),
                         ("unsupported_food", "data_eval/unsupported_food"), ("food_packaging_closed", "data_eval/food_packaging_closed"),
                         ("non_food", "data_nonfood/general"),
                         ("non_food_packaged", "data_nonfood/packaged_objects")]:
        d = BACKEND / folder
        f = d / "ATTRIBUTION.csv"
        sets[name] = [(d / r["file"], r["category"]) for r in csv.DictReader(open(f, encoding="utf-8"))] if f.is_file() else []
    man = BACKEND / "data_eval" / "packaged" / "MANIFEST.json"
    sets["packaged_food"] = [(BACKEND / "data_eval" / "packaged" / p["barcode"] / "front.jpg", p["product_name"])
                             for p in json.loads(man.read_text(encoding="utf-8"))] if man.is_file() else []
    return sets


EXPECTED = {  # what a correct outcome is for each set
    "supported_test": "food", "food_in_context": "food", "food_with_packaging": "food", "unsupported_food": "food",
    "packaged_food": "packaged_food", "food_packaging_closed": "packaged_food", "non_food": "not_food",
    "non_food_packaged": "not_food",
}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None)
    ap.add_argument("--per-class", type=int, default=15)
    ap.add_argument("--api", action="store_true", help="also post every image to /api/analyze/food (paid providers OFF, temp DB)")
    args = ap.parse_args()
    if args.api:  # set before the app is imported; .env is not changed
        import os
        import tempfile
        tmp = tempfile.mkdtemp(prefix="smartplate_gate_")
        os.environ.update({"OPENAI_VISION_ENABLED": "false", "GEMINI_VISION_ENABLED": "false", "VISION_ENABLED": "false",
                           "DATABASE_PATH": os.path.join(tmp, "eval.db"), "AUTH_DATABASE_PATH": os.path.join(tmp, "users.db")})
    from app.ml.recognizer import FoodRecognizer, decode_upload
    rec = FoodRecognizer()
    assert rec.load(), rec.status_message
    client = None
    if args.api:
        from fastapi.testclient import TestClient
        from app.api.routes import analyze
        from app.main import app
        app.dependency_overrides[analyze.get_recognizer] = lambda: rec
        client = TestClient(app)
    rows = []
    for set_name, items in load_sets(args.per_class).items():
        for path, label in items:
            r = rec.analyze_image(decode_upload(path.read_bytes()))
            s = r["signals"]
            rows.append({"set": set_name, "file": path.name, "label": label, "decision": r["decision"], "top1": r["top_k"][0]["food"],
                         "confidence": round(r["confidence"], 4), "food_mass": round(s["imagenet_food_mass"], 5),
                         "imagenet_top1": s.get("imagenet_top1"), "imagenet_group": s.get("imagenet_group"),
                         "packaged_product": r.get("packaged_product", False),
                         "api": api_outcome(client, path) if client else None})
    report = summarise(rows, rec.thresholds.food_mass_low)
    if client:
        report["api"] = api_metrics(rows)
    print(json.dumps(report, indent=1))
    if args.out:
        Path(args.out).write_text(json.dumps({"summary": report, "rows": rows}, indent=1, ensure_ascii=False), encoding="utf-8")


def api_outcome(client, path: Path) -> dict:
    j = client.post("/api/analyze/food", files={"file": (path.name, path.read_bytes(), "image/jpeg")}).json()
    if j.get("success"):
        pred = j.get("prediction") or {}
        shown = bool(j.get("nutrition")) or bool(j.get("nutrition_choice"))
        return {"outcome": "food_shown", "food": pred.get("food"), "nutrition_or_choice": shown}
    return {"outcome": j.get("error_code"), "reason": j.get("reason")}


def api_metrics(rows: list[dict]) -> dict:
    """End-to-end outcomes. 'food_shown' = a food name was presented as the result (with nutrition or a type choice)."""
    out = {}
    for name in EXPECTED:
        rs = [r for r in rows if r["set"] == name and r.get("api")]
        if not rs:
            continue
        c = Counter(r["api"]["outcome"] + (":" + r["api"]["reason"] if r["api"].get("reason") in ("weak_food_evidence",) else "")
                    for r in rs)
        m = {"n": len(rs), "outcomes": dict(c)}
        if EXPECTED[name] == "food":
            m["false_reject_non_food"] = c.get("NON_FOOD_IMAGE", 0)
            m["routed_to_package_scanner"] = c.get("PACKAGED_PRODUCT", 0)
        if name == "supported_test":
            shown = [r for r in rs if r["api"]["outcome"] == "food_shown"]
            m["shown_correct"] = sum(r["api"]["food"] == r["label"] for r in shown)
            m["shown_wrong"] = sum(r["api"]["food"] != r["label"] for r in shown)
            m["extra_confirmation_weak_evidence"] = c.get("LOW_CONFIDENCE:weak_food_evidence", 0)
        if EXPECTED[name] in ("not_food", "packaged_food"):
            m["false_food_claims"] = c.get("food_shown", 0)
        out[name] = m
    return out


def summarise(rows: list[dict], floor: float) -> dict:
    out: dict = {"food_mass_floor": floor, "sets": {}}
    by = defaultdict(list)
    for r in rows:
        by[r["set"]].append(r)
    for name, rs in by.items():
        acc = [r for r in rs if r["decision"] == "accept"]
        out["sets"][name] = {
            "n": len(rs), "expected": EXPECTED[name],
            "decisions": dict(Counter(r["decision"] for r in rs)),
            "packaged_product_flag": sum(bool(r["packaged_product"]) for r in rs),
            "imagenet_groups": dict(Counter(r["imagenet_group"] for r in rs)),
            "accepted": len(acc),
            "accepted_correct_class": sum(r["top1"] == r["label"] for r in acc) if name == "supported_test" else None,
            "accepted_with_food_mass_below_floor": sum(r["food_mass"] < floor for r in acc),
            "accepted_with_container_top1_and_low_food_mass": sum(r["imagenet_group"] == "container" and r["food_mass"] < floor for r in acc),
        }
    return out


if __name__ == "__main__":
    main()
